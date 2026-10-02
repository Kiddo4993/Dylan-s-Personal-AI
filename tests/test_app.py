from fixel import app as app_module
from fixel.app import FixelApp
from fixel.brain import ProviderError
from fixel.brain.fake import FakeProvider
from fixel.casefile import CaseFile
from fixel.config import Config
from fixel.ui import UI

ERR = (
    "MODE: error\nKEY: ModuleNotFoundError: No module named 'numpy'\n---\n"
    "**Cause:** wrong venv.\n**Fix:**\n```bash\npip install numpy\n```\n"
)


def make_app(tmp_path, console, provider, shot_bytes=b"PNG", screen_text=""):
    cfg = Config(home=tmp_path, notes_dir=tmp_path / "notes")

    async def fake_ocr(path):
        return screen_text

    async def fake_capture(dest):
        if shot_bytes is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(shot_bytes)
        return shot_bytes

    app = FixelApp(
        cfg, UI(console),
        provider_factory=lambda alias, cfg: provider,
        capture=fake_capture,
        ocr=fake_ocr,
        casefile=CaseFile(tmp_path / "c.db"),
    )
    app.select_model("sonnet")
    return app


async def test_capture_then_ask_sends_screenshot_and_saves_case(tmp_path, console):
    provider = FakeProvider([ERR])
    app = make_app(tmp_path, console, provider)
    await app.capture_once()
    assert app.ui.status.tray == 1
    assert await app.ask("") == ""
    turns, system, deep = provider.calls[0]
    assert turns[0].images == [b"PNG"] and "MODE:" in system
    assert deep is False  # normal questions get quick answers
    assert app.session.case.header.mode == "error"
    assert app.casefile.get(app.session.case.case_id).answer.startswith("**Cause:**")
    assert app.ui.status.tray == 0


async def test_cancelled_capture_leaves_tray_empty(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider(), shot_bytes=None)
    await app.capture_once()
    assert app.session.tray == []


async def test_capture_blocked_without_screen_permission(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    app.screen_ok = False
    await app.capture_once()
    assert app.session.tray == [] and "Screen Recording" in app.ui.status.flash


async def test_provider_failure_mid_stream_restores_tray_and_text(tmp_path, console):
    provider = FakeProvider([ERR], error=ProviderError("Can't reach Anthropic."), error_after=2)
    app = make_app(tmp_path, console, provider)
    await app.capture_once()
    assert await app.ask("why?") == "why?"
    assert len(app.session.tray) == 1 and app.session.case.turns == []
    assert "still in the tray" in console.file.getvalue()


NUMPY_SCREEN = "$ python3 app.py\nModuleNotFoundError: No module named 'numpy'"


async def test_past_fix_is_sent_to_the_model_for_a_repeat_problem(tmp_path, console):
    provider = FakeProvider([ERR, ERR])
    app = make_app(tmp_path, console, provider, screen_text=NUMPY_SCREEN)
    await app.capture_once()
    await app.ask("")
    first_id = app.session.case.case_id
    assert "[Fixel memory" not in provider.calls[0][0][-1].text  # nothing to remember yet
    await app.capture_once()
    await app.ask("")
    sent = provider.calls[1][0][-1].text
    assert sent.startswith("[Fixel memory") and "pip install numpy" in sent and sent.endswith("Figure this out.")
    assert app.session.case.question == "Figure this out."
    assert app.last_recall.id == first_id
    assert "🧠" in console.file.getvalue()


async def test_follow_ups_do_not_repeat_memory(tmp_path, console):
    provider = FakeProvider([ERR, ERR, ERR])
    app = make_app(tmp_path, console, provider, screen_text=NUMPY_SCREEN)
    await app.capture_once()
    await app.ask("")
    await app.capture_once()
    await app.ask("")
    await app.ask("and why?")
    assert provider.calls[2][0][-1].text == "and why?"


async def test_screen_text_is_saved_with_the_case(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR]), screen_text=NUMPY_SCREEN)
    await app.capture_once()
    await app.ask("")
    assert app.casefile.get(app.session.case.case_id).screen_text == NUMPY_SCREEN


async def test_mark_worked(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR]))
    await app.handle_action("worked")
    assert "Nothing to mark yet" in console.file.getvalue()
    await app.ask("why?")
    await app.handle_action("worked")
    assert app.casefile.get(app.session.case.case_id).worked is True


async def test_about_me_notes_reach_the_model(tmp_path, console):
    provider = FakeProvider()
    app = make_app(tmp_path, console, provider)
    await app.handle_command("/remember I use Python 3.12 and zsh")
    await app.handle_command("/remember I'm in AP Calc BC")
    await app.handle_command("/memory")
    assert "1. I use Python 3.12 and zsh" in console.file.getvalue()
    await app.ask("hi")
    assert "- I use Python 3.12 and zsh" in provider.calls[0][1]
    await app.handle_command("/forget 1")
    await app.ask("again")
    assert "Python 3.12" not in provider.calls[1][1] and "AP Calc BC" in provider.calls[1][1]


async def test_forget_needs_a_valid_number(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_command("/forget 3")
    await app.handle_command("/forget")
    assert console.file.getvalue().count("Usage: /forget") == 2


async def test_copy_action_copies_fix(tmp_path, console, monkeypatch):
    copied = []
    monkeypatch.setattr(app_module.actions, "copy_to_clipboard", copied.append)
    app = make_app(tmp_path, console, FakeProvider([ERR]))
    await app.capture_once()
    await app.ask("")
    await app.handle_action("copy")
    assert copied == ["pip install numpy"]


async def test_run_action_needs_confirmation(tmp_path, console, monkeypatch):
    ran = []

    async def fake_run(cmd, **kwargs):
        ran.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(app_module.actions, "run_command", fake_run)
    app = make_app(tmp_path, console, FakeProvider([ERR]))
    await app.capture_once()
    await app.ask("")

    async def decline(question):
        return False

    async def accept(question):
        return True

    app.ui.confirm = decline
    await app.handle_action("run")
    assert ran == []
    app.ui.confirm = accept
    await app.handle_action("run")
    assert ran == ["pip install numpy"]


async def test_save_action_writes_note(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR]))
    await app.capture_once()
    await app.ask("numpy broke")
    await app.handle_action("save")
    notes = list((tmp_path / "notes").glob("*.md"))
    assert len(notes) == 1 and "pip install numpy" in notes[0].read_text()


async def test_learn_mode_changes_system_prompt(tmp_path, console):
    provider = FakeProvider()
    app = make_app(tmp_path, console, provider)
    await app.handle_action("learn")
    await app.ask("2+2?")
    assert "Learn mode is ON" in provider.calls[0][1]


async def test_commands(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    assert await app.handle_command("/quit") is False
    assert await app.handle_command("/nope") is True
    assert "Unknown command" in console.file.getvalue()


async def test_unexpected_provider_error_keeps_fixel_alive_and_tray(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR], error=RuntimeError("weird SDK failure"), error_after=1))
    await app.capture_once()
    assert await app.ask("why?") == "why?"
    assert len(app.session.tray) == 1 and app.session.case.turns == []
    assert "weird SDK failure" in console.file.getvalue()


async def test_ctrl_c_stops_a_running_command_not_fixel(tmp_path, console, monkeypatch):
    import asyncio
    import os
    import signal

    async def slow_run(cmd, **kwargs):
        await asyncio.sleep(5)
        return 0, "finished"

    monkeypatch.setattr(app_module.actions, "run_command", slow_run)
    app = make_app(tmp_path, console, FakeProvider([ERR]))
    await app.capture_once()
    await app.ask("")

    async def accept(question):
        return True

    app.ui.confirm = accept
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGINT)
    await asyncio.wait_for(app.handle_action("run"), 2)
    assert "Stopped" in console.file.getvalue()


async def test_startup_banner_comes_before_model_errors(tmp_path, console, monkeypatch):
    def no_key(alias, cfg):
        raise ProviderError("No Anthropic API key yet. Run `fixel setup`.")

    monkeypatch.setattr(app_module.permissions, "input_monitoring_granted", lambda: False)
    monkeypatch.setattr(app_module.permissions, "screen_recording_granted", lambda: True)
    app = FixelApp(Config(home=tmp_path), UI(console), provider_factory=no_key, casefile=CaseFile(tmp_path / "c.db"))
    await app.startup()
    out = console.file.getvalue()
    assert out.index("Fixel") < out.index("No Anthropic API key")
    assert "claude-sonnet-5-5" in out


ERR2 = "MODE: error\nKEY: ModuleNotFoundError: No module named 'numpy'\n---\n**Cause:** deeper look.\n"


async def test_think_harder_reasks_same_question_with_deep_thinking(tmp_path, console):
    provider = FakeProvider([ERR, ERR2])
    app = make_app(tmp_path, console, provider)
    await app.capture_once()
    await app.ask("why?")
    await app.handle_action("deeper")
    turns, _, deep = provider.calls[1]
    assert deep is True and [t.role for t in turns] == ["user"]
    assert [t.role for t in app.session.case.turns] == ["user", "assistant"]
    assert app.session.case.answer == "**Cause:** deeper look.\n"
    assert "deep thinking" in console.file.getvalue()


async def test_think_harder_failure_keeps_the_first_answer(tmp_path, console):
    provider = FakeProvider([ERR])
    app = make_app(tmp_path, console, provider)
    await app.ask("why?")
    provider.error = ProviderError("Google's Gemini models are all busy right now.")
    await app.handle_action("deeper")
    assert len(app.session.case.turns) == 2 and app.session.case.answer.startswith("**Cause:** wrong venv")
    assert "all busy" in console.file.getvalue()


async def test_think_harder_needs_a_question_first(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_action("deeper")
    assert "Ask something first" in console.file.getvalue()


async def test_footer_reports_busy_fallback(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR], answered_by="backup-model"))
    await app.ask("why?")
    assert "fake was busy, answered by backup-model" in console.file.getvalue()
