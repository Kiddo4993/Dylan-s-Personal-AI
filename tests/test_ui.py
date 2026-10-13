from fixel.brain.base import Turn
from fixel.brain.fake import FakeProvider
from fixel.parse import Header
from fixel.ui import UI, Status, toolbar_text


def test_toolbar_idle_and_tray():
    assert toolbar_text(Status()).startswith("⌥⌥ screenshot")
    assert "2 shots in tray" in toolbar_text(Status(tray=2))
    assert "adding to this case" in toolbar_text(Status(tray=1, follow_up=True))
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
    ui.memory_line([record], 0)
    ui.show_cases([record])
    assert console.file.getvalue().count("cfg[bold]") == 2


def test_help_puts_screenshot_and_ask_on_separate_lines(console):
    UI(console).help()
    lines = [line.strip() for line in console.file.getvalue().splitlines()]
    assert any(line.startswith("Screenshot:") for line in lines)
    assert any(line.startswith("Ask:") for line in lines)



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


def test_help_lists_every_command_and_the_hidden_shortcuts(console):
    from fixel.commands import COMMANDS

    UI(console).help()
    out = console.file.getvalue()
    assert all(c.name in out for c in COMMANDS)
    assert "Ctrl+T" in out and "⌃" not in out


def test_nothing_on_screen_uses_the_control_symbol(console):
    from datetime import datetime

    from fixel.casefile import CaseRecord
    from fixel.ui import Thinking

    ui = UI(console)
    ui.action_bar()
    ui.memory_line([CaseRecord(1, datetime(2026, 10, 2), "error", "k", "q", "a", [])], 1)
    console.print(Thinking(images=True))
    toolbars = [toolbar_text(Status()), toolbar_text(Status(tray=2)), toolbar_text(Status(hotkey_ok=False))]
    out = console.file.getvalue() + "".join(toolbars)
    assert "⌃" not in out
    assert "/deeper" in toolbar_text(Status()) and "/ for commands" in toolbar_text(Status())
    assert "/follow" in toolbar_text(Status(tray=2))
    assert "/open" in out and "Ctrl+C to stop" in out


def test_thinking_line_has_pix_verb_timer_and_stop_hint(console):
    from fixel.ui import Thinking

    console.print(Thinking(images=True))
    out = console.file.getvalue()
    assert "⌜•‿•⌝  Squinting at your screenshot… 0s · Ctrl+C to stop" in out


def test_thinking_line_holds_still_when_animations_are_off(console):
    from fixel.ui import Thinking

    thinking = Thinking(images=True, animated=False)
    thinking.started -= 10  # 10 seconds in: an animated Pix would have moved on
    console.print(thinking)
    assert "⌜•‿•⌝  Squinting at your screenshot… 10s" in console.file.getvalue()


def test_errors_get_a_sad_pix_and_reactions_a_happy_one(console):
    ui = UI(console)
    ui.error("Can't reach Google.")
    ui.react("Nice. Marked as worked.")
    out = console.file.getvalue()
    assert "⌜•⁀•⌝ Can't reach Google." in out and "⌜^‿^⌝ Nice. Marked as worked." in out


def test_pix_never_touches_the_words_and_only_pix_is_colored():
    from fixel.ui import Thinking

    for tenth in range(80):  # 8 seconds: rests, blinks, zooms, glances
        thinking = Thinking(images=True)
        thinking.started -= tenth / 10
        line = next(iter(thinking.__rich_console__(None, None)))
        assert line.plain[7] == " ", line.plain  # a gap after Pix's 7-cell face, always
        assert not line.style  # no colour on the whole line...
        assert line.spans[0].end == 7  # ...just on Pix's face


def test_every_mode_has_a_badge_and_a_color():
    from fixel.home import MODE_COLORS
    from fixel.parse import MODES
    from fixel.ui import BADGES

    assert set(BADGES) == set(MODES)
    assert set(MODE_COLORS) == set(MODES)
