from fixel.brain.base import Turn
from fixel.brain.fake import FakeProvider
from fixel.parse import Header
from fixel.ui import UI, Status, toolbar_text


def test_toolbar_idle_and_tray():
    assert toolbar_text(Status()).startswith("⌥⌥ screenshot")
    assert "2 shots in tray" in toolbar_text(Status(tray=2))
    assert "follow-up: on" in toolbar_text(Status(tray=1, follow_up=True))
    assert "hotkey off" in toolbar_text(Status(hotkey_ok=False))


def test_toolbar_flash_expires():
    status = Status()
    status.flash_msg("Tray full", seconds=10)
    assert toolbar_text(status) == "Tray full"
    status.flash_until = 0
    assert toolbar_text(status) != "Tray full"


async def test_stream_answer_parses_and_renders(console):
    ui = UI(console)
    provider = FakeProvider(["MODE: error\nKEY: Boom\n---\n**Cause:** gremlins"], chunk=4)
    header, raw, body = await ui.stream_answer(provider.stream([Turn("user", "q")], "s"))
    assert header == Header("error", "Boom")
    assert body == "**Cause:** gremlins" and raw.startswith("MODE:")
    out = console.file.getvalue()
    assert "ERROR" in out and "gremlins" in out and "MODE:" not in out


def test_messages_keep_square_brackets(console):
    ui = UI(console)
    ui.error("Fix [models] in ~/.fixel/config.toml")
    ui.warn("content[1] is bad")
    ui.info("[x] done")
    out = console.file.getvalue()
    assert "[models]" in out and "content[1]" in out and "[x] done" in out


def test_case_text_keeps_square_brackets(console):
    from datetime import datetime

    from fixel.casefile import CaseRecord

    ui = UI(console)
    record = CaseRecord(1, datetime(2026, 9, 12), "error", "KeyError: cfg[bold]", "q", "a", [])
    ui.recall_line(record)
    ui.show_cases([record])
    assert console.file.getvalue().count("cfg[bold]") == 2


def test_help_puts_screenshot_and_ask_on_separate_lines(console):
    UI(console).help()
    lines = [line.strip() for line in console.file.getvalue().splitlines()]
    assert any(line.startswith("Screenshot:") for line in lines)
    assert any(line.startswith("Ask:") for line in lines)


def test_thinking_spinner_shows_elapsed_and_stop_hint(console):
    from fixel.ui import Thinking

    console.print(Thinking())
    assert "thinking… 0s · ⌃C to stop" in console.file.getvalue()


def test_answer_footer_shows_model_time_and_fallback(console):
    ui = UI(console)
    ui.answer_footer("gemini-3.5-flash", "gemini-3.6-flash", 1.84, deep=True)
    out = console.file.getvalue()
    assert "gemini-3.6-flash was busy, answered by gemini-3.5-flash" in out
    assert "gemini-3.5-flash · 1.8s · deep thinking" in out


def test_answer_footer_without_fallback(console):
    UI(console).answer_footer("gemini-3.6-flash", "gemini-3.6-flash", 2.0, deep=False)
    out = console.file.getvalue()
    assert "busy" not in out and "gemini-3.6-flash · 2.0s" in out and "deep" not in out


def test_help_and_toolbar_mention_think_harder(console):
    UI(console).help()
    assert "⌃T" in console.file.getvalue()
    assert "⌃T deeper" in toolbar_text(Status())
