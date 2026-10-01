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


def make_app(tmp_path, console, provider, shot_bytes=b"PNG"):
    cfg = Config(home=tmp_path, notes_dir=tmp_path / "notes")

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
    turns, system = provider.calls[0]
    assert turns[0].images == [b"PNG"] and "MODE:" in system
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


async def test_repeat_problem_shows_seen_before(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider([ERR, ERR]))
    await app.capture_once()
    await app.ask("")
    first_id = app.session.case.case_id
    await app.capture_once()
    await app.ask("")
    assert app.last_recall.id == first_id
    assert "Seen before" in console.file.getvalue()


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
