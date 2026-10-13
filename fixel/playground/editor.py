"""/code: a full-screen code editor in the terminal, with an output pane and a Run key."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import merge_styles, style_from_pygments_cls
from prompt_toolkit.widgets import TextArea
from pygments.styles import get_style_by_name

from .attachment import CodeAttachment
from .keywords import CodeCompleter
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
        self._saved = scratch.load(lang)  # what's in the scratch file, for the modified marker
        self._ran_code: str | None = None  # the code `last` came from
        self._task: asyncio.Task | None = None
        self.code = TextArea(
            text=code, lexer=self._lexer(), line_numbers=True, scrollbar=True,
            completer=CodeCompleter(lambda: self.lang), complete_while_typing=False,
        )
        self.stdin = TextArea(height=Dimension(preferred=3, max=6), prompt="stdin› ")
        self.output = TextArea(
            text="F5 runs your code.", read_only=True, scrollbar=True, height=Dimension(preferred=8, max=12)
        )
        self._picked = RUNNABLE.index(lang)  # the sidebar's highlighted row while it has focus
        self.sidebar = FormattedTextControl(
            self.sidebar_fragments, focusable=True, show_cursor=False, key_bindings=self._sidebar_bindings()
        )
        rule = lambda: Window(height=1, char="─", style="class:rule")  # noqa: E731
        main = HSplit([
            self.code,
            rule(),
            ConditionalContainer(HSplit([self.stdin, rule()]), filter=Condition(lambda: self.show_input)),
            self.output,
        ])
        body = FloatContainer(
            HSplit([
                VSplit([Window(self.sidebar, width=14), Window(width=1, char="│", style="class:rule"), main]),
                Window(FormattedTextControl(self.status_text), height=1, style="reverse"),
            ]),
            floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8, scroll_offset=1))],
        )
        self.app = Application(
            layout=Layout(body, focused_element=self.code),
            key_bindings=self._bindings(),
            style=merge_styles([style_from_pygments_cls(get_style_by_name("monokai"))]),
            full_screen=True,
            mouse_support=True,
            input=input,
            output=output,
        )
        self.app.ttimeoutlen = 0.05  # how long a lone Esc byte waits to become part of an escape sequence
        self.app.timeoutlen = 0.25  # how long Esc waits for a following key (Esc+f is ⌥→) before closing

    async def edit(self) -> EditorResult:
        return await self.app.run_async()

    # ---- pieces

    def _lexer(self) -> PygmentsLexer:
        return PygmentsLexer.from_filename(LANGS[self.lang].filename)

    def status_text(self) -> str:
        doc = self.code.document
        where = f"Ln {doc.cursor_position_row + 1}, Col {doc.cursor_position_col + 1}"
        modified = " · modified" if self.code.text != self._saved else ""
        running = " · running… ⌃C stops" if self._running else ""
        keys = "F5 run · F3 input · F4 files · ⌃A ask Fixel · Esc back"
        return f" {LANGS[self.lang].label} · {where}{modified}{running}   {keys} "

    def _save(self) -> None:
        self.scratch.save(self.lang, self.code.text)
        self._saved = self.code.text

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
            self._save()
        self.app.exit(result=EditorResult(self.lang, self.code.text, self._attachment() if attach else None))

    async def _run_now(self) -> None:
        code = self.code.text
        self._save()
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

    def sidebar_fragments(self):
        """One row per scratch file; the open one is marked, and each row opens its file on click."""
        focused = self.app.layout.has_focus(self.sidebar) if hasattr(self, "app") else False
        fragments = [("class:sidebar.title", " Files\n")]
        for i, lang in enumerate(RUNNABLE):
            style = "class:sidebar.current" if lang == self.lang else "class:sidebar"
            if focused and i == self._picked:
                style += " reverse"
            marker = "▸ " if lang == self.lang else "  "
            fragments.append((style, f" {marker}{LANGS[lang].filename}\n", self._on_click(lang)))
        return fragments

    def _on_click(self, lang: str):
        def handler(mouse_event) -> None:
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._open_file(lang)
            else:
                return NotImplemented

        return handler

    def _open_file(self, lang: str) -> None:
        if not self._running and lang != self.lang:
            self._switch_to(lang)
        self.app.layout.focus(self.code)

    def _switch_language(self) -> None:
        self._switch_to(RUNNABLE[(RUNNABLE.index(self.lang) + 1) % len(RUNNABLE)])

    def _switch_to(self, lang: str) -> None:
        self._save()
        self.lang = lang
        self._picked = RUNNABLE.index(lang)
        text = self.scratch.load(self.lang)
        self._saved = text
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

        @kb.add("f4")
        def _(event) -> None:
            on_sidebar = event.app.layout.has_focus(self.sidebar)
            self._picked = RUNNABLE.index(self.lang)
            event.app.layout.focus(self.code if on_sidebar else self.sidebar)

        @kb.add("escape")  # not eager: ⌥←/⌥→ arrive as Esc+b / Esc+f and must stay word jumps
        def _(event) -> None:
            self._close(attach=False)

        in_code = has_focus(self.code)

        @kb.add("c-space", filter=in_code)
        def _(event) -> None:
            event.current_buffer.start_completion(select_first=False)

        @kb.add("tab", filter=in_code)
        def _(event) -> None:
            buffer = event.current_buffer
            if buffer.complete_state:
                buffer.complete_next()
            else:
                buffer.insert_text("    ")

        @kb.add("enter", filter=in_code)
        def _(event) -> None:
            buffer = event.current_buffer
            state = buffer.complete_state
            buffer.complete_state = None
            if state is None or state.current_completion is None:  # nothing picked: a normal new line
                buffer.newline(copy_margin=False)

        return kb

    def _sidebar_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _(event) -> None:
            self._picked = (self._picked - 1) % len(RUNNABLE)

        @kb.add("down")
        def _(event) -> None:
            self._picked = (self._picked + 1) % len(RUNNABLE)

        @kb.add("enter")
        def _(event) -> None:
            self._open_file(RUNNABLE[self._picked])

        return kb
