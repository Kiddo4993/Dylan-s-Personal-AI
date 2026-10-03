"""Everything Fixel draws in the terminal."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncIterator

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from . import pix
from .home import PIX_COLOR, HomeInfo, render_home
from .parse import Header, split_header

BADGES = {
    "error": "bold white on red",
    "math": "bold black on cyan",
    "doc": "bold black on yellow",
    "ui": "bold white on blue",
    "general": "bold black on white",
}
ACTION_KEYS = (
    ("c-t", "deeper"),
    ("c-g", "worked"),
    ("c-y", "copy"),
    ("c-r", "run"),
    ("c-s", "save"),
    ("c-l", "learn"),
    ("c-f", "follow"),
    ("c-o", "open"),
    ("c-n", "new"),
)
HELP = """\
**Screenshot:** double-tap **Right Option ⌥**, then drag over anything. Shots wait in the tray; \
double-tap again to add more (up to 5).

**Ask:** press **Enter**, or type a question first. Typing after an answer asks a follow-up.

| Key | Does |
|---|---|
| ⌃T | think harder: re-answer the last question with deep thinking |
| ⌃G | that worked: Fixel reaches for this fix first next time |
| ⌃Y | copy the fix / answer / draft |
| ⌃R | run the suggested shell command (asks first) |
| ⌃S | save this case as a note in ~/Fixel Notes |
| ⌃L | learn mode: hints instead of answers (`/answer` reveals) |
| ⌃F | attach the tray to the current case instead of starting a new one |
| ⌃O | open the past case Fixel used |
| ⌃N | new case |

**Commands:** `/model sonnet|opus|gemini` · `/answer` · `/remember <fact>` · `/memory` · `/forget <n>` · \
`/cases <words>` · `/open <number>` · `/help` · `/quit`
"""


@dataclass(frozen=True)
class KeyAction:
    name: str
    buffer: str  # whatever was typed, restored after the action


@dataclass
class Status:
    """What the bottom toolbar shows. The app writes it; the toolbar reads it every refresh."""

    tray: int = 0
    follow_up: bool = False
    hotkey_ok: bool = True
    flash: str = ""
    flash_until: float = 0.0

    def flash_msg(self, msg: str, seconds: float = 4.0) -> None:
        self.flash = msg
        self.flash_until = time.monotonic() + seconds


def toolbar_text(status: Status) -> str:
    if status.flash and time.monotonic() < status.flash_until:
        return status.flash
    if status.tray:
        plural = "" if status.tray == 1 else "s"
        follow = "on" if status.follow_up else "off"
        return f"📸 {status.tray} shot{plural} in tray · ⏎ ask · ⌥⌥ add more · ⌃F follow-up: {follow}"
    hotkey = "⌥⌥ screenshot" if status.hotkey_ok else "⚠ hotkey off (run fixel setup)"
    return f"{hotkey} · ⌃T deeper · ⌃Y copy · ⌃R run · ⌃S save · ⌃N new · /help"


class Thinking:
    """Pix's thinking line, shown until the first words arrive: face, verb, seconds waited."""

    def __init__(self, *, images: bool = False, deep: bool = False, animated: bool = True) -> None:
        self.started = time.monotonic()
        self.images = images
        self.deep = deep
        self.animated = animated

    def __rich_console__(self, console, options):
        seconds = time.monotonic() - self.started
        moment = seconds if self.animated else 0.0  # animations off: Pix holds still, verb stays put
        line = Text()
        line.append(pix.mini_frame(moment), style=f"bold {PIX_COLOR}")  # colour on Pix only
        line.append(f" {pix.verb(moment, images=self.images, deep=self.deep)}… ")
        line.append(f"{seconds:.0f}s · ⌃C to stop", style="dim")
        yield line


class UI:
    def __init__(self, console: Console | None = None, *, animations: bool = True) -> None:
        self.console = console or Console()
        self.animations = animations
        self.status = Status()
        self._session: PromptSession | None = None

    # ---- input

    def _prompt_session(self) -> PromptSession:
        if self._session is None:
            bindings = KeyBindings()
            for key, name in ACTION_KEYS:
                bindings.add(key)(self._action_handler(name))
            self._session = PromptSession(
                key_bindings=bindings, bottom_toolbar=lambda: toolbar_text(self.status), refresh_interval=0.3
            )
        return self._session

    @staticmethod
    def _action_handler(name: str):
        def handler(event) -> None:
            event.app.exit(result=KeyAction(name, event.app.current_buffer.text))

        return handler

    async def prompt(self, default: str = "") -> str | KeyAction | None:
        """Read one line. ⌃-keys return a KeyAction; ⌃D returns None; ⌃C clears the line."""
        with patch_stdout(raw=True):
            try:
                return await self._prompt_session().prompt_async(HTML("<ansicyan><b>›</b></ansicyan> "), default=default)
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return None

    async def confirm(self, question: str) -> bool:
        try:
            reply = await PromptSession().prompt_async(question)
        except (KeyboardInterrupt, EOFError):
            return False
        return reply.strip().lower() in ("y", "yes")

    # ---- output

    def home(self, info: HomeInfo) -> None:
        width = self.console.width
        if self.animations and self.console.is_terminal:
            # The once-per-launch moment: Pix's corners focus in, then its eyes open.
            with Live(console=self.console, transient=True, auto_refresh=False) as live:
                for face in pix.startup_frames():
                    live.update(render_home(info, width, face=face), refresh=True)
                    time.sleep(0.07)
        self.console.print(render_home(info, width))

    def banner(self, model: str, learn: bool) -> None:
        self.console.rule(f"[bold cyan]Fixel[/] · {model} · learn: {'on' if learn else 'off'}")

    def info(self, msg: str) -> None:
        self.console.print(f"[cyan]›[/] {escape(msg)}")

    def warn(self, msg: str) -> None:
        self.console.print(f"[yellow]⚠ {escape(msg)}[/]")

    def error(self, msg: str) -> None:
        self.console.print(f"[bold red]{pix.SAD} {escape(msg)}[/]")

    def react(self, msg: str) -> None:
        """A happy Pix for good news, like a fix that worked."""
        self.console.print(f"[bold {PIX_COLOR}]{pix.HAPPY}[/] {escape(msg)}")

    def help(self) -> None:
        self.console.print(Markdown(HELP))

    @staticmethod
    def answer_view(header: Header | None, body: str):
        if header is None:
            return Thinking(animated=False)
        title = Text(f" {header.mode.upper()} ", style=BADGES.get(header.mode, BADGES["general"]))
        if header.key:
            title.append(f"  {header.key}", style="dim")
        return Group(title, Text(""), Markdown(body, code_theme="monokai"))

    async def stream_answer(
        self, chunks: AsyncIterator[str], *, images: bool = False, deep: bool = False
    ) -> tuple[Header, str, str]:
        """Render a streaming reply live, hiding the header. Returns (header, raw reply, body)."""
        raw = ""
        thinking = Thinking(images=images, deep=deep, animated=self.animations)
        with Live(thinking, console=self.console, refresh_per_second=12, vertical_overflow="visible") as live:
            async for chunk in chunks:
                raw += chunk
                parsed = split_header(raw)
                if parsed is not None:
                    live.update(self.answer_view(*parsed))
            header, body = split_header(raw, final=True)
            live.update(self.answer_view(header, body))
        return header, raw, body

    def memory_line(self, records, notes: int) -> None:
        """Show which past cases Fixel is handing the model before it answers."""
        for record in records:
            proven = " ✅" if record.worked else ""
            self.console.print(
                f"[magenta]🧠 Using your past case from {record.created_at:%b %d}{proven}: {escape(record.key or record.question)}[/]"
            )
        about = f" · plus {notes} note{'' if notes == 1 else 's'} about you" if notes else ""
        self.console.print(f"[dim]   ⌃O opens it{about}[/]")

    def answer_footer(self, model: str, configured: str, seconds: float, deep: bool) -> None:
        if model != configured:
            self.console.print(f"[yellow]⚡ {escape(configured)} was busy, answered by {escape(model)}[/]")
        detail = " · deep thinking" if deep else ""
        self.console.print(f"[dim]{escape(model)} · {seconds:.1f}s{detail}[/]")

    def action_bar(self) -> None:
        self.console.print(Text("─" * min(self.console.width, 72), style="dim"))
        self.console.print("[dim]⌃T think harder · ⌃G it worked · ⌃Y copy · ⌃R run · ⌃S save note · ⌃N new[/]")

    def show_command(self, cmd: str) -> None:
        self.console.print(Panel(Syntax(cmd, "bash", theme="monokai", word_wrap=True), title="Run this?", border_style="yellow"))

    def show_output(self, code: int | None, out: str) -> None:
        title = "timed out" if code is None else f"exit {code}"
        style = "green" if code == 0 else "red"
        self.console.print(Panel(Text(out.rstrip() or "(no output)"), title=title, border_style=style))

    def show_case(self, record) -> None:
        title = f"#{record.id} · {record.created_at:%Y-%m-%d} · {record.mode} · {record.key or record.question}"
        self.console.print(Panel(Markdown(record.answer), title=title, border_style="magenta"))

    def show_cases(self, records) -> None:
        for r in records:
            self.console.print(f"[bold]#{r.id}[/] {r.created_at:%Y-%m-%d} [dim]{r.mode}[/] {escape(r.key or r.question[:70])}")
        self.console.print("[dim]Open one with /open <number>[/]")
