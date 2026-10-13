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
