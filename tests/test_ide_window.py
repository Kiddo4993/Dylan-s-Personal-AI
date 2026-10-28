import asyncio
import stat

from fixel import terminal
from fixel.config import Config
from fixel.playground.attachment import CodeAttachment
from fixel.playground.editor import EditorResult
from fixel.playground.scratch import Scratch
from fixel.playground.server import PlaygroundServer
from fixel.playground.window import NOT_OPEN, read_link, remove_link, run_window, send_to_fixel, write_link


def test_ide_command_runs_this_python_and_exits_after(monkeypatch):
    monkeypatch.setattr(terminal.sys, "executable", "/Users/d/Personal Projects/x/.venv/bin/python")
    assert terminal.ide_command("java") == "clear; '/Users/d/Personal Projects/x/.venv/bin/python' -m fixel ide java; exit"
    assert terminal.ide_command(None).endswith("-m fixel ide; exit")
    assert "fixel ide java" in terminal.launch_script(terminal.ide_command("java"))


def test_link_file_is_private_and_round_trips(tmp_path):
    path = write_link(tmp_path, "http://127.0.0.1:5", "secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_link(tmp_path) == {"ask": "http://127.0.0.1:5/api/ask", "token": "secret"}
    write_link(tmp_path, "http://127.0.0.1:6", "new")  # a restarted Fixel replaces it
    assert read_link(tmp_path)["token"] == "new"
    remove_link(tmp_path)
    assert read_link(tmp_path) is None


def test_a_broken_link_file_reads_as_no_fixel(tmp_path):
    (tmp_path / "ide-link.json").write_text("[1, 2]")
    assert read_link(tmp_path) is None
    assert send_to_fixel(None, CodeAttachment("python", "x")) == NOT_OPEN


async def test_ctrl_a_in_the_window_lands_in_fixels_tray(tmp_path):
    """End to end over 127.0.0.1: the IDE window's send reaches the real playground server."""
    asked = []
    server = PlaygroundServer(asyncio.get_running_loop(), Scratch(tmp_path / "pg"), None, asked.append, token="tok")
    server.start()
    try:
        link = read_link(tmp_path) if write_link(tmp_path, server.origin, server.token) else None
        att = CodeAttachment("java", "class Main {}", "boom", 1, ran=True)
        assert await asyncio.to_thread(send_to_fixel, link, att) is None
        await asyncio.sleep(0.05)  # the server hands it to Fixel's loop
        assert asked == [att]
        wrong = {**link, "token": "guess"}
        assert await asyncio.to_thread(send_to_fixel, wrong, att) == NOT_OPEN and len(asked) == 1
    finally:
        server.stop()
    assert await asyncio.to_thread(send_to_fixel, link, att) == NOT_OPEN  # Fixel closed


class ScriptedEditor:
    """Plays back one EditorResult per open, recording what each open was given."""

    def __init__(self, results):
        self.results, self.opens = list(results), []

    def __call__(self, scratch, lang, code, run, *, note=""):
        self.opens.append((lang, code, note))
        result = self.results.pop(0)
        editor = type("E", (), {})()

        async def edit():
            return result

        editor.edit = edit
        return editor


async def test_window_sends_each_ctrl_a_and_reopens_until_esc(tmp_path):
    cfg = Config(home=tmp_path)
    Scratch(cfg.playground_dir).save("java", "class Main {}")
    att = CodeAttachment("java", "class Main { }")
    editor = ScriptedEditor([EditorResult("java", "class Main { }", att), EditorResult("java", "class Main { }", None)])
    sent = []
    assert await run_window(cfg, "java", editor_factory=editor, send=lambda link, a: sent.append(a)) == 0
    assert sent == [att]
    (lang1, code1, note1), (lang2, code2, note2) = editor.opens
    assert (lang1, code1) == ("java", "class Main {}") and "⌃A sends" in note1
    assert code2 == "class Main { }" and note2.startswith("Sent to Fixel")


async def test_window_says_when_fixel_is_gone_and_ignores_html(tmp_path):
    cfg = Config(home=tmp_path)
    editor = ScriptedEditor([EditorResult("python", "x", CodeAttachment("python", "x")), EditorResult("python", "x", None)])
    await run_window(cfg, "html", editor_factory=editor)  # no link file: nothing to send to
    assert editor.opens[0][0] != "html" and editor.opens[1][2] == NOT_OPEN
