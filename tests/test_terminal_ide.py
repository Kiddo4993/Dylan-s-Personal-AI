import asyncio

import pytest
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput

from fixel.playground.editor import Editor
from fixel.playground.runner import RunResult
from fixel.playground.scratch import Scratch

DOWN, ENTER, F4, ESC, CTRL_A = "\x1b[B", "\r", "\x1bOS", "\x1b", "\x01"


async def fake_run(code, lang, stdin):
    return RunResult(0, "", 0.1)


async def until(predicate, timeout=2.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


@pytest.fixture
def pipe():
    with create_pipe_input() as inp:
        yield inp


def start(tmp_path, pipe, lang="python", code="print(x)"):
    editor = Editor(Scratch(tmp_path), lang, code, fake_run, input=pipe, output=DummyOutput())
    return editor, asyncio.create_task(editor.edit())


async def finish(pipe, task):
    pipe.send_text(CTRL_A)
    return await asyncio.wait_for(task, 2)


# ---- keys that must keep working


async def test_option_arrow_moves_by_word_instead_of_closing(tmp_path, pipe):
    editor, task = start(tmp_path, pipe)
    pipe.send_text("\x1bf")  # Terminal.app's ⌥→
    await asyncio.sleep(0.4)
    assert not task.done() and editor.code.buffer.cursor_position == len("print")
    await finish(pipe, task)


# ---- file sidebar


def sidebar(editor):
    return "".join(fragment[1] for fragment in editor.sidebar_fragments())


async def test_sidebar_lists_the_scratch_files_and_marks_the_open_one(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, lang="java", code="class A {}")
    text = sidebar(editor)
    for name in ("main.py", "Main.java", "main.js", "main.cpp"):
        assert name in text
    assert "▸ Main.java" in text and "▸ main.py" not in text
    await finish(pipe, task)


async def test_sidebar_keys_switch_files_and_return_to_the_code(tmp_path, pipe):
    editor, task = start(tmp_path, pipe)
    pipe.send_text(F4)
    await until(lambda: editor.app.layout.has_focus(editor.sidebar))
    pipe.send_text(DOWN + ENTER)
    await until(lambda: editor.lang == "java")
    assert "public class Main" in editor.code.text
    assert editor.app.layout.has_focus(editor.code)
    assert Scratch(tmp_path).load("python") == "print(x)"  # the file left behind was saved
    await finish(pipe, task)


async def test_clicking_a_file_in_the_sidebar_opens_it(tmp_path, pipe):
    editor, task = start(tmp_path, pipe)
    handlers = {text.strip(" ▸●\n"): handler for _, text, *rest in editor.sidebar_fragments() if rest
                for handler in rest}
    click = MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset())
    handlers["main.cpp"](click)
    assert editor.lang == "cpp" and "#include" in editor.code.text
    await finish(pipe, task)


# ---- status bar


async def test_status_bar_shows_position_and_modified(tmp_path, pipe):
    scratch = Scratch(tmp_path)
    editor = Editor(scratch, "python", scratch.load("python"), fake_run, input=pipe, output=DummyOutput())
    task = asyncio.create_task(editor.edit())
    await asyncio.sleep(0.05)
    status = editor.status_text()
    assert "Python" in status and "Ln 1, Col 1" in status and "modified" not in status
    pipe.send_text("ab")
    await until(lambda: "Col 3" in editor.status_text())
    assert "modified" in editor.status_text()
    pipe.send_text("\x1b[15~")  # F5 saves before running
    await until(lambda: "modified" not in editor.status_text())
    await finish(pipe, task)


async def test_code_handed_in_is_modified_only_once_edited(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="from ctrl+p")
    assert "modified" not in editor.status_text()  # Esc now wouldn't save it, so nothing is unsaved
    pipe.send_text("x")
    await until(lambda: "modified" in editor.status_text())
    await finish(pipe, task)


# ---- completion

CTRL_SPACE, TAB = "\x00", "\t"


def offered(editor):
    state = editor.code.buffer.complete_state
    return [c.text for c in state.completions] if state else []


def at_end(editor):
    editor.code.buffer.cursor_position = len(editor.code.text)


async def test_ctrl_space_offers_words_from_the_code_and_tab_picks_one(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="counter = 1\ncou")
    at_end(editor)
    pipe.send_text(CTRL_SPACE)
    await until(lambda: "counter" in offered(editor))
    pipe.send_text(TAB)
    await until(lambda: editor.code.text.endswith("\ncounter"))
    pipe.send_text(ENTER)  # accepts: closes the menu without a new line
    await until(lambda: editor.code.buffer.complete_state is None)
    assert editor.code.text == "counter = 1\ncounter"
    await finish(pipe, task)


async def test_completion_offers_the_languages_keywords(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, lang="java", code="Sys")
    at_end(editor)
    pipe.send_text(CTRL_SPACE)
    await until(lambda: "System" in offered(editor))
    await finish(pipe, task)


async def test_tab_without_a_menu_still_indents(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="")
    pipe.send_text(TAB)
    await until(lambda: editor.code.text == "    ")
    await finish(pipe, task)


# ---- indentation

SHIFT_TAB = "\x1b[Z"


async def test_enter_keeps_indentation_and_indents_after_a_colon(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="if x:")
    at_end(editor)
    pipe.send_text(ENTER)
    await until(lambda: editor.code.text == "if x:\n    ")
    pipe.send_text("y" + ENTER)
    await until(lambda: editor.code.text == "if x:\n    y\n    ")
    await finish(pipe, task)


async def test_enter_indents_after_an_opening_brace(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, lang="java", code="  class A {")
    at_end(editor)
    pipe.send_text(ENTER)
    await until(lambda: editor.code.text == "  class A {\n      ")
    await finish(pipe, task)


async def test_shift_tab_dedents_the_current_line(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="a\n        z")
    at_end(editor)
    pipe.send_text(SHIFT_TAB)
    await until(lambda: editor.code.text == "a\n    z")
    assert editor.code.text[: editor.code.buffer.cursor_position] == "a\n    z"  # cursor stays put on the text
    editor.code.buffer.text = "  q"
    pipe.send_text(SHIFT_TAB)
    await until(lambda: editor.code.text == "q")
    await finish(pipe, task)


# ---- find and go to line

CTRL_F, CTRL_G = "\x06", "\x07"


async def test_ctrl_f_finds_each_match_in_turn_and_esc_only_closes_the_bar(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="a\nfoo\nbar FOO")
    pipe.send_text(CTRL_F)
    await until(lambda: editor.app.layout.has_focus(editor.bar))
    pipe.send_text("foo" + ENTER)
    await until(lambda: editor.code.buffer.cursor_position == 2)
    pipe.send_text(ENTER)
    await until(lambda: editor.code.buffer.cursor_position == 10)  # case doesn't matter
    pipe.send_text(ENTER)
    await until(lambda: editor.code.buffer.cursor_position == 2)  # wraps around
    pipe.send_text(ESC)
    await until(lambda: editor.bar_mode is None)
    assert editor.app.layout.has_focus(editor.code) and not task.done()
    await finish(pipe, task)


async def test_find_with_no_match_says_so_and_stays_put(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="hello")
    pipe.send_text(CTRL_F + "zzz" + ENTER)
    await until(lambda: "no match" in editor.bar_prompt())
    assert editor.code.buffer.cursor_position == 0
    await finish(pipe, task)


async def test_ctrl_g_goes_to_a_line(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="1\n2\n  three\n4\n5")
    pipe.send_text(CTRL_G)
    await until(lambda: editor.app.layout.has_focus(editor.bar))
    pipe.send_text("3" + ENTER)
    await until(lambda: editor.bar_mode is None)
    assert editor.code.document.cursor_position_row == 2
    assert editor.app.layout.has_focus(editor.code)
    pipe.send_text(CTRL_G + "99" + ENTER)  # past the end: the last line
    await until(lambda: editor.code.document.cursor_position_row == 4)
    await finish(pipe, task)


async def test_go_to_line_ignores_digits_that_are_not_numbers(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="1\n2")
    pipe.send_text(CTRL_G)
    await until(lambda: editor.app.layout.has_focus(editor.bar))
    pipe.send_text("²" + ENTER)  # isdigit() says yes, int() says no
    await until(lambda: editor.bar_mode is None)
    assert editor.code.document.cursor_position_row == 0 and not task.done()
    await finish(pipe, task)


async def test_enter_inside_the_indentation_does_not_indent_twice(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="if x:\n    y")
    editor.code.buffer.cursor_position = len("if x:\n")  # start of the indented line: open a line above
    pipe.send_text(ENTER)
    await until(lambda: editor.code.text == "if x:\n\n    y")
    await finish(pipe, task)


async def test_esc_closes_the_completion_menu_not_the_editor(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, code="value = 1\nva")
    at_end(editor)
    pipe.send_text(CTRL_SPACE)
    await until(lambda: "value" in offered(editor))
    pipe.send_text(ESC)
    await until(lambda: editor.code.buffer.complete_state is None)
    await asyncio.sleep(0.1)
    assert not task.done()
    await finish(pipe, task)


# ---- /ide terminal


async def test_ide_here_opens_the_terminal_ide_in_this_window(tmp_path, console):
    from test_app_playground import FakeEditor, FakeServer, make_app

    app = make_app(tmp_path, console)
    await app.handle_command("/ide here")
    await app.handle_command("/ide here java")
    assert [lang for lang, _ in FakeEditor.opened] == ["python", "java"]
    assert FakeServer.instances == [] and app.windows == []  # no browser, no new window


async def test_ide_here_rejects_html_and_unknown_languages(tmp_path, console):
    from test_app_playground import FakeEditor, make_app

    app = make_app(tmp_path, console)
    await app.handle_command("/ide here html")
    await app.handle_command("/ide here rust")
    out = console.file.getvalue()
    assert "/ide web html" in out and "Unknown language 'rust'" in out and FakeEditor.opened == []


def test_help_mentions_every_ide(console):
    from fixel.ui import UI

    UI(console).help()
    out = console.file.getvalue()
    assert "/ide [here|web]" in out and "own Terminal window" in out
