"""Fixel's homepage: the panel drawn when Fixel starts."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import pix
from .casefile import CaseRecord

# The one bold element: a pixel wordmark inside screenshot-selection corners,
# shaded like a selection highlight. Everything else stays quiet.
WORDMARK_ROWS = ("█▀▀ █ ▀▄▀ █▀▀ █  ", "█▀  █ ▄▀▄ ██▄ █▄▄")
GRADIENT = ((0x5A, 0xA9, 0xFF), (0x8B, 0x7C, 0xFF))  # sky blue → violet
OK, PROBLEM, QUIET = "#5FD38D", "#F2B84B", "grey62"
PIX_COLOR = "#A99BFF"  # Pix, the mascot: soft violet, the far end of the wordmark's gradient
MODE_COLORS = {"error": "#FF6B6B", "math": "#4FD1C5", "doc": "#F2B84B", "ui": "#5AA9FF", "general": "grey70"}
LEFT_WIDTH = 26
NARROW = 80  # below this many columns, stack instead of side-by-side
MAX_WIDTH = 100  # a card, not a full-width banner, in wide windows

TIPS = (
    "Type /deeper to re-answer the last question with deep thinking.",
    "Type /worked when a fix works. Fixel reaches for it first next time.",
    "Teach Fixel about you: /remember I'm taking AP Calc BC",
    "Type /learn for learn mode: hints instead of answers.",
    "Double-tap ⌥ again before pressing Enter to add more screenshots to one question.",
    "Type /run to run a suggested command. Fixel always asks first.",
    "Type / to see every command.",
)


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    fix: str = ""  # shown under the panel when not ok


@dataclass(frozen=True)
class HomeInfo:
    name: str | None
    model: str
    checks: list[Check]
    solved: int
    worked: int
    notes: int
    recent: list[CaseRecord] = field(default_factory=list)
    tip: str = ""


def first_name(full_name: str) -> str | None:
    parts = full_name.split()
    return parts[0] if parts else None


def mac_first_name() -> str | None:
    """First name of the macOS account, e.g. "Dylan" from "Dylan Duan"."""
    try:
        result = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return first_name(result.stdout) if result.returncode == 0 else None


def wordmark() -> list[Text]:
    rows = []
    for row in WORDMARK_ROWS:
        text = Text()
        last = max(len(row) - 1, 1)
        for column, char in enumerate(row):
            mix = column / last
            r, g, b = (round(a + (z - a) * mix) for a, z in zip(*GRADIENT))
            text.append(char, style=f"bold #{r:02x}{g:02x}{b:02x}")
        rows.append(text)
    return rows


def _left(info: HomeInfo, face: list[str] | None = None) -> RenderableType:
    greeting = f"Welcome back, {info.name}" if info.name and info.solved else (
        f"Welcome to Fixel, {info.name}" if info.name else "Welcome to Fixel"
    )
    return Group(
        *(Text(row, style=f"bold {PIX_COLOR}") for row in face or pix.big_face()),
        Text(""),
        *wordmark(),
        Text(""),
        Text(greeting, style="bold"),
        Text(""),
        Text(info.model),
        Text("quick answers, /deeper for more", style=QUIET),
    )


def _checks(checks: list[Check]) -> Text:
    line = Text()
    for index, check in enumerate(checks):
        if index:
            line.append("   ")
        line.append("✓ " if check.ok else "✗ ", style=OK if check.ok else PROBLEM)
        line.append(check.label, style=None if check.ok else PROBLEM)
    return line


def _recent(records: list[CaseRecord]) -> RenderableType:
    if not records:
        return Text("Nothing yet. Double-tap ⌥ on something you're stuck on.", style=QUIET)
    table = Table.grid(padding=(0, 2))
    table.add_column(style=QUIET, no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
    for record in records:
        table.add_row(
            f"{record.created_at:%b %d}",
            Text(record.mode, style=MODE_COLORS.get(record.mode, MODE_COLORS["general"])),
            Text(record.key or record.question),  # Text, not markup: case text is shown literally
        )
    return table


def _right(info: HomeInfo) -> RenderableType:
    solved = (
        f"{info.solved} solved, {info.worked} confirmed working" if info.solved else "No cases yet"
    )
    notes = (
        f"{info.notes} note{'' if info.notes == 1 else 's'} about you"
        if info.notes
        else "No notes yet. Add one with /remember"
    )
    return Group(
        Text("Ready", style="bold"),
        _checks(info.checks),
        Text(""),
        Text("Memory", style="bold"),
        Text(solved),
        Text(notes, style=None if info.notes else QUIET),
        Text(""),
        Text("Recent", style="bold"),
        _recent(info.recent),
    )


def render_home(info: HomeInfo, width: int, face: list[str] | None = None) -> RenderableType:
    """`face` swaps in a frame of Pix's startup animation; omit it for the resting face."""
    if min(width, MAX_WIDTH) >= NARROW:
        body = Table(box=box.MINIMAL, show_header=False, show_edge=False, padding=(0, 1), expand=True)
        body.add_column(width=LEFT_WIDTH, no_wrap=True)
        body.add_column(ratio=1)
        body.add_row(_left(info, face), _right(info))
    else:
        body = Group(_left(info, face), Text(""), _right(info))
    panel = Panel(body, box=box.ROUNDED, border_style=QUIET, padding=(0, 1), width=min(width, MAX_WIDTH))
    problems = [check.fix for check in info.checks if not check.ok and check.fix]
    parts: list[RenderableType] = [panel]
    if problems:
        parts.append(_hanging(" ✗", problems, PROBLEM))
    if info.tip:
        parts.append(_hanging(" Tip:", [info.tip], QUIET))
    return Group(*parts)


def _hanging(marker: str, lines: list[str], style: str) -> Table:
    """Marker in its own column, so wrapped lines stay indented under their text."""
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column(ratio=1)
    for line in lines:
        table.add_row(Text(marker, style=style), Text(line, style=style))
    return table
