import asyncio

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from fixel.playground.editor import Editor, format_result
from fixel.playground.runner import RunnerError, RunResult
from fixel.playground.scratch import Scratch

F2, F3, F5, CTRL_A, ESC = "\x1bOQ", "\x1bOR", "\x1b[15~", "\x01", "\x1b"


class FakeRun:
    def __init__(self, result=RunResult(1, "NameError: x\n", 0.2), error=None):
        self.calls, self.result, self.error = [], result, error

    async def __call__(self, code, lang, stdin):
        self.calls.append((code, lang, stdin))
        if self.error:
            raise self.error
        return self.result


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


def start(tmp_path, pipe, run, lang="python", code="print(x)"):
    editor = Editor(Scratch(tmp_path), lang, code, run, input=pipe, output=DummyOutput())
    return editor, asyncio.create_task(editor.edit())


def test_format_result():
    assert format_result(RunResult(0, "hi\n", 0.42)) == "hi\n── exit 0 · 0.4s"
    assert format_result(RunResult(None, "", 10.0)) == "(no output)\n── stopped · 10.0s"


async def test_f5_runs_and_ctrl_a_attaches_code_and_output(tmp_path, pipe):
    run = FakeRun()
    editor, task = start(tmp_path, pipe, run)
    pipe.send_text(F5)
    await until(lambda: editor.last is not None)
    assert "NameError" in editor.output.text and "exit 1" in editor.output.text
    pipe.send_text(CTRL_A)
    result = await asyncio.wait_for(task, 2)
    assert run.calls == [("print(x)", "python", "")]
    assert result.attachment.failed and result.attachment.output == "NameError: x\n"
    assert Scratch(tmp_path).load("python") == "print(x)"


async def test_attach_after_edit_drops_stale_output(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun())
    pipe.send_text(F5)
    await until(lambda: editor.last is not None)
    pipe.send_text("# changed")
    await until(lambda: "# changed" in editor.code.text)
    pipe.send_text(CTRL_A)
    att = (await asyncio.wait_for(task, 2)).attachment
    assert att.ran is False and att.output == "" and "# changed" in att.code  # cursor opens at the top


async def test_input_pane_feeds_stdin(tmp_path, pipe):
    run = FakeRun(RunResult(0, "", 0.1))
    editor, task = start(tmp_path, pipe, run)
    pipe.send_text(F3)
    await until(lambda: editor.show_input)
    pipe.send_text("5 7")
    await until(lambda: editor.stdin.text == "5 7")
    pipe.send_text(F5)
    await until(lambda: run.calls)
    assert run.calls[0][2] == "5 7"
    pipe.send_text(CTRL_A)
    await asyncio.wait_for(task, 2)


async def test_runner_error_is_shown(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun(error=RunnerError("Java isn't installed.")), lang="java")
    pipe.send_text(F5)
    await until(lambda: "isn't installed" in editor.output.text)
    pipe.send_text(CTRL_A)
    assert (await asyncio.wait_for(task, 2)).attachment.ran is False


async def test_f2_switches_language_and_saves(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun())
    pipe.send_text(F2)
    await until(lambda: editor.lang == "java")
    assert "public class Main" in editor.code.text
    assert Scratch(tmp_path).load("python") == "print(x)"
    pipe.send_text(CTRL_A)
    assert (await asyncio.wait_for(task, 2)).lang == "java"


async def test_esc_closes_without_attaching_and_leaves_untouched_scratch(tmp_path, pipe):
    Scratch(tmp_path).save("python", "old")
    editor, task = start(tmp_path, pipe, FakeRun(), code="handed off by ctrl+p")
    pipe.send_text(ESC)
    result = await asyncio.wait_for(task, 2)
    assert result.attachment is None
    assert Scratch(tmp_path).load("python") == "old"


async def test_option_arrow_word_jump_does_not_close_the_editor(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun(), code="print(x)")
    pipe.send_text("\x1bf")  # what Terminal.app sends for ⌥→ (word forward)
    await asyncio.sleep(0.3)
    assert not task.done()
    assert editor.code.buffer.cursor_position == len("print")
    pipe.send_text(ESC)
    assert (await asyncio.wait_for(task, 2)).attachment is None
