"""/code: a full-screen code editor in the terminal, with an output pane and a Run key."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import merge_styles, style_from_pygments_cls
from prompt_toolkit.widgets import TextArea
from pygments.styles import get_style_by_name

from .attachment import CodeAttachment
from .langs import LANGS, RUNNABLE
from .runner import RunnerError, RunResult
from .scratch import Scratch

RunFn = Callable[[str, str, str], Awaitable[RunResult]]  # (code, lang, stdin)


@dataclass(frozen=True)
class EditorResult:
    lang: str
    code: str
    attachment: CodeAttachment | None  # set when the user pressed ⌃A


def format_result(result: RunResult) -> str:
    status = "stopped" if result.exit_code is None else f"exit {result.exit_code}"
    return f"{result.output.rstrip() or '(no output)'}\n── {status} · {result.seconds:.1f}s"


class Editor:
    def __init__(self, scratch: Scratch, lang: str, code: str, run: RunFn, *, input=None, output=None) -> None:
        self.scratch = scratch
        self.lang = lang
        self.last: RunResult | None = None
        self.show_input = False
        self._run = run
        self._opened_with = code
        self._ran_code: str | None = None  # the code `last` came from
        self._task: asyncio.Task | None = None
        self.code = TextArea(text=code, lexer=self._lexer(), line_numbers=True, scrollbar=True)
        self.stdin = TextArea(height=Dimension(preferred=3, max=6), prompt="stdin› ")
        self.output = TextArea(
            text="F5 runs your code.", read_only=True, scrollbar=True, height=Dimension(preferred=8, max=12)
        )
        rule = lambda: Window(height=1, char="─", style="class:rule")  # noqa: E731
        body = HSplit([
            self.code,
            rule(),
            ConditionalContainer(HSplit([self.stdin, rule()]), filter=Condition(lambda: self.show_input)),
            self.output,
            Window(FormattedTextControl(self._status_text), height=1, style="reverse"),
        ])
        self.app = Application(
            layout=Layout(body, focused_element=self.code),
            key_bindings=self._bindings(),
            style=merge_styles([style_from_pygments_cls(get_style_by_name("monokai"))]),
            full_screen=True,
            mouse_support=True,
            input=input,
            output=output,
        )
        self.app.ttimeoutlen = 0.05  # Esc closes without a half-second wait

    async def edit(self) -> EditorResult:
        return await self.app.run_async()

    # ---- pieces

    def _lexer(self) -> PygmentsLexer:
        return PygmentsLexer.from_filename(LANGS[self.lang].filename)

    def _status_text(self) -> str:
        running = " · running… ⌃C stops" if self._running else ""
        return f" {LANGS[self.lang].label} · F5 run · F3 input · F2 language · ⌃A ask Fixel · Esc back{running} "

    @property
    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _attachment(self) -> CodeAttachment:
        code = self.code.text
        if self.last is None or self._ran_code != code:  # never run, or edited since: old output would mislead
            return CodeAttachment(self.lang, code)
        return CodeAttachment(self.lang, code, self.last.output, self.last.exit_code, ran=True)

    def _close(self, attach: bool) -> None:
        if self._running:
            self._task.cancel()
        if self.code.text != self._opened_with or self.last is not None:
            self.scratch.save(self.lang, self.code.text)
        self.app.exit(result=EditorResult(self.lang, self.code.text, self._attachment() if attach else None))

    async def _run_now(self) -> None:
        code = self.code.text
        self.scratch.save(self.lang, code)
        self.output.text = "Running…"
        self.app.invalidate()
        try:
            result = await self._run(code, self.lang, self.stdin.text)
        except RunnerError as e:
            self.output.text = str(e)
        except asyncio.CancelledError:
            self.output.text = "Stopped."
            raise
        else:
            self.last, self._ran_code = result, code
            self.output.text = format_result(result)
        finally:
            self.app.invalidate()

    def _switch_language(self) -> None:
        self.scratch.save(self.lang, self.code.text)
        self.lang = RUNNABLE[(RUNNABLE.index(self.lang) + 1) % len(RUNNABLE)]
        text = self.scratch.load(self.lang)
        self.code.text, self._opened_with = text, text
        self.code.lexer = self._lexer()  # TextArea reads it through a DynamicLexer
        self.last, self._ran_code = None, None
        self.output.text = "F5 runs your code."

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("f5")
        def _(event) -> None:
            if not self._running:
                self._task = asyncio.ensure_future(self._run_now())

        @kb.add("c-c")
        def _(event) -> None:
            if self._running:
                self._task.cancel()

        @kb.add("f3")
        def _(event) -> None:
            self.show_input = not self.show_input
            event.app.layout.focus(self.stdin if self.show_input else self.code)

        @kb.add("f2")
        def _(event) -> None:
            if not self._running:
                self._switch_language()

        @kb.add("c-a")
        def _(event) -> None:
            self._close(attach=True)

        @kb.add("escape", eager=True)
        def _(event) -> None:
            self._close(attach=False)

        @kb.add("tab", filter=has_focus(self.code))
        def _(event) -> None:
            event.current_buffer.insert_text("    ")

        return kb
