import io
from datetime import datetime

from rich.console import Console

from fixel.casefile import CaseRecord
from fixel.home import Check, HomeInfo, first_name, render_home, wordmark


def render(info, width):
    console = Console(file=io.StringIO(), width=width, force_terminal=False, color_system=None)
    console.print(render_home(info, width))
    return console.file.getvalue()


def case(day, mode, key):
    return CaseRecord(1, datetime(2026, 10, day), mode, key, "q", "a", [])


def info(**overrides):
    base = dict(
        name="Dylan",
        model="gemini-3.6-flash",
        checks=[Check("⌥⌥ hotkey", True), Check("screenshots", True), Check("API key", True)],
        solved=14,
        worked=3,
        notes=2,
        recent=[case(2, "error", "No module named pandas"), case(1, "math", "Integrate x² sin x")],
        tip="Press ⌃T to re-answer with deep thinking.",
    )
    base.update(overrides)
    return HomeInfo(**base)


def test_wordmark_is_two_pixel_rows_shaded_left_to_right():
    rows = wordmark()
    assert len(rows) == 2 and all("█" in row.plain for row in rows)
    styles = [span.style for span in rows[0].spans]
    assert styles[0] != styles[-1]  # gradient, not one flat color


def test_wide_window_puts_columns_side_by_side():
    lines = render(info(), 100).splitlines()
    assert any("⌜" in line and "Ready" in line for line in lines)
    out = "\n".join(lines)
    assert "Welcome back, Dylan" in out and "gemini-3.6-flash" in out
    assert "14 solved, 3 confirmed working" in out and "2 notes about you" in out
    assert "Oct 02" in out and "No module named pandas" in out
    assert "Tip: Press ⌃T to re-answer with deep thinking." in " ".join(out.split())


def test_narrow_window_stacks_columns():
    lines = render(info(), 60).splitlines()
    assert not any("⌜" in line and "Ready" in line for line in lines)
    assert "Welcome back, Dylan" in "\n".join(lines)


def test_first_run_invites_a_first_screenshot():
    out = render(info(solved=0, worked=0, notes=0, recent=[], name=None), 100)
    assert "Welcome to Fixel" in out
    assert "Nothing yet. Double-tap ⌥ on something you're stuck on." in out
    assert "No notes yet. Add one with /remember" in out


def test_problems_get_a_fix_line_under_the_panel():
    checks = [Check("⌥⌥ hotkey", True), Check("API key", False, "No Gemini API key yet. Run `fixel setup`.")]
    out = render(info(checks=checks), 100)
    assert "✗ API key" in out and "✓ ⌥⌥ hotkey" in out
    assert out.index("No Gemini API key yet") > out.index("╰")


def test_long_recent_items_are_trimmed_not_wrapped():
    out = render(info(recent=[case(2, "doc", "word " * 40)]), 100)
    assert "…" in out
    assert sum("word word" in line for line in out.splitlines()) == 1


def test_case_text_is_shown_literally():
    out = render(info(recent=[case(2, "error", "KeyError: cfg[bold]")]), 100)
    assert "cfg[bold]" in out


def test_first_name():
    assert first_name("Dylan Duan") == "Dylan"
    assert first_name("  ") is None


def test_panel_stays_card_sized_in_wide_windows():
    lines = render(info(), 200).splitlines()
    assert max(len(line) for line in lines) <= 100


def test_homepage_shows_pix_above_the_wordmark():
    out = render(info(), 100)
    assert "●   ●" in out
    assert out.index("●   ●") < out.index("█▀▀")
