from fixel.app import FixelApp
from fixel.brain.fake import FakeProvider
from fixel.casefile import CaseFile
from fixel.config import Config
from fixel.parse import Header
from fixel.playground.attachment import CodeAttachment
from fixel.playground.editor import EditorResult
from fixel.ui import UI

WEB = "MODE: web\nKEY: Acme landing page\n---\n**Design**\n- Type: Inter\n**Code:**\n```html\n<!doctype html><h1>Acme</h1>\n```\n"
PY = "MODE: error\nKEY: NameError\n---\n**Cause:** typo.\n**Fix:**\n```python\nprint(x)\n```\n"
BASH = "MODE: error\nKEY: numpy\n---\n**Fix:**\n```bash\npip install numpy\n```\n"


class FakeEditor:
    opened = []
    attach = None

    def __init__(self, scratch, lang, code, run):
        FakeEditor.opened.append((lang, code))
        self.lang, self.code = lang, code

    async def edit(self):
        return EditorResult(self.lang, self.code, FakeEditor.attach)


class FakeServer:
    instances = []

    def __init__(self, loop, scratch, run, on_ask):
        self.on_ask, self.handoffs, self.started, self.stopped = on_ask, [], 0, False
        self.url, self.origin, self.token = "http://127.0.0.1:9/#tok", "http://127.0.0.1:9", "tok"
        FakeServer.instances.append(self)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped = True

    def hand_off(self, lang, code):
        self.handoffs.append((lang, code))


def make_app(tmp_path, console, replies=(), window_opens=True):
    FakeEditor.opened, FakeEditor.attach, FakeServer.instances = [], None, []
    opened_urls, windows = [], []

    def ide_window(lang):
        windows.append(lang)
        return window_opens

    app = FixelApp(
        Config(home=tmp_path, notes_dir=tmp_path / "notes"), UI(console),
        provider_factory=lambda alias, cfg: FakeProvider(list(replies)),
        casefile=CaseFile(tmp_path / "c.db"),
        editor_factory=FakeEditor, server_factory=FakeServer, open_url=opened_urls.append, ide_window=ide_window,
    )
    app.select_model("sonnet")
    app.opened_urls, app.windows = opened_urls, windows
    return app


async def test_code_command_opens_editor_in_last_or_named_language(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/code")
    await app.handle_command("/code c++")
    assert [lang for lang, _ in FakeEditor.opened] == ["python", "cpp"]
    assert "public" not in FakeEditor.opened[0][1]  # python starter, not java


async def test_code_command_rejects_html_and_unknown(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/code html")
    await app.handle_command("/code rust")
    out = console.file.getvalue()
    assert "/web" in out and "Unknown language 'rust'" in out and FakeEditor.opened == []


async def test_ctrl_a_in_editor_puts_code_in_tray_and_enter_asks(tmp_path, console):
    app = make_app(tmp_path, console, [PY])
    FakeEditor.attach = CodeAttachment("python", "print(x)", "NameError", 1, ran=True)
    await app.handle_command("/code")
    assert app.ui.status.code == "Python" and app.session.code is not None
    assert await app.ask("") == ""
    sent = app.provider.calls[0][0][-1].text
    assert "[Code from Fixel playground · python]" in sent and sent.endswith("Why doesn't this work?")
    assert app.ui.status.code == ""


async def test_web_command_starts_one_server_and_opens_browser(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/web")
    await app.handle_command("/web")
    (server,) = FakeServer.instances
    assert server.started == 1 and app.opened_urls == [server.url, server.url]


async def test_browser_ask_attaches_code(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/web")
    FakeServer.instances[0].on_ask(CodeAttachment("javascript", "console.log(1)"))
    assert app.ui.status.code == "JavaScript" and "Enter" in app.ui.status.flash


async def test_ctrl_p_routes_html_to_web_and_code_to_editor(tmp_path, console):
    app = make_app(tmp_path, console, [WEB, PY])
    await app.ask("clone this")
    assert "/play opens this code" in console.file.getvalue()
    await app.handle_action("play")
    assert FakeServer.instances[0].handoffs == [("html", "<!doctype html><h1>Acme</h1>")]
    await app.ask("and this?")
    await app.handle_action("play")
    assert FakeEditor.opened == [("python", "print(x)")]


async def test_ctrl_p_without_playground_code(tmp_path, console):
    app = make_app(tmp_path, console, [BASH])
    await app.handle_action("play")
    assert "Ask something first" in console.file.getvalue()
    await app.ask("numpy?")
    await app.handle_action("play")
    assert "no code the playground can open" in console.file.getvalue()
    assert FakeEditor.opened == [] and FakeServer.instances == []


async def test_server_bind_failure_is_reported(tmp_path, console):
    app = make_app(tmp_path, console)

    class Broken(FakeServer):
        def start(self):
            raise OSError("Address in use")

    app._server_factory = Broken
    await app.handle_command("/web")
    assert "Couldn't start the web playground (Address in use)" in console.file.getvalue()
    assert app.web is None and app.opened_urls == []


async def test_new_case_clears_attached_code(tmp_path, console):
    app = make_app(tmp_path, console)
    app.attach_code(CodeAttachment("python", "x"))
    await app.handle_action("new")
    assert app.session.code is None and app.ui.status.code == ""


async def test_ide_command_opens_the_ide_in_a_new_terminal_window(tmp_path, console):
    from fixel.playground.window import read_link

    app = make_app(tmp_path, console)
    await app.handle_command("/ide")
    await app.handle_command("/ide java")
    await app.handle_command("/ide terminal c++")
    assert app.windows == [None, "java", "cpp"] and FakeEditor.opened == [] and app.opened_urls == []
    (server,) = FakeServer.instances  # started once, so ⌃A in the window has somewhere to land
    assert read_link(tmp_path) == {"ask": "http://127.0.0.1:9/api/ask", "token": "tok"}
    assert "own Terminal window" in console.file.getvalue()


async def test_ide_falls_back_to_this_window_when_terminal_cant_open_one(tmp_path, console):
    app = make_app(tmp_path, console, window_opens=False)
    await app.handle_command("/ide java")
    assert FakeEditor.opened[0][0] == "java" and "opens here instead" in console.file.getvalue()


async def test_ide_here_uses_this_window_and_ide_web_the_browser(tmp_path, console):
    app = make_app(tmp_path, console)
    app.scratch.save("java", "class Hello {}")
    await app.handle_command("/ide here java")
    await app.handle_command("/ide web java")
    await app.handle_command("/ide HTML")  # HTML needs the live preview: always the browser
    assert app.windows == [] and FakeEditor.opened[0][0] == "java"
    assert FakeServer.instances[0].handoffs[0] == ("java", "class Hello {}")
    assert FakeServer.instances[0].handoffs[1][0] == "html" and len(app.opened_urls) == 2


async def test_ide_command_rejects_unknown_language(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/ide rust")
    await app.handle_command("/ide web rust")
    out = console.file.getvalue()
    assert out.count("Unknown language 'rust'") == 2 and FakeServer.instances == [] and app.windows == []


async def test_failed_ask_says_the_code_is_still_in_the_tray(tmp_path, console):
    from fixel.brain import ProviderError

    app = make_app(tmp_path, console)
    app.provider = FakeProvider(error=ProviderError("Can't reach Anthropic."))
    app.attach_code(CodeAttachment("python", "print(x)"))
    assert await app.ask("") == ""
    assert app.session.code is not None and "still in the tray" in console.file.getvalue()
