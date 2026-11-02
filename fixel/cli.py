"""One-shot commands for scripts and for Claude Code's Fixel skill: `fixel shot`, `fixel canvas`, `fixel cases`.

Data goes to stdout (JSON with --json); progress and problems go to stderr, so `--json` output always parses.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from rich.console import Console

from .capture import capture_region
from .casefile import CaseFile, CaseRecord
from .config import Config


def _out(data) -> None:
    print(json.dumps(data, indent=1, ensure_ascii=False))


async def shot(
    cfg: Config, out: str | None, capture: Callable[[Path], Awaitable[bytes | None]] = capture_region
) -> int:
    """Drag over part of the screen; print the PNG's path. Exit 1 if you press Esc instead."""
    dest = Path(out).expanduser() if out else cfg.shots_dir / f"{uuid.uuid4().hex}.png"
    print("Drag over what you want to show. Esc cancels.", file=sys.stderr)
    if not await capture(dest):
        print("Cancelled: no screenshot taken.", file=sys.stderr)
        return 1
    print(dest.resolve())
    return 0


def _case(record: CaseRecord) -> dict:
    return {
        "id": record.id,
        "date": record.created_at.date().isoformat(),
        "mode": record.mode,
        "problem": record.key or record.question,
        "question": record.question,
        "answer": record.answer,
        "worked": record.worked,
    }


def cases(cfg: Config, words: list[str], as_json: bool, casefile: CaseFile | None = None) -> int:
    """Search past cases (newest best match first). With no words, the most recent ones."""
    try:
        casefile = casefile or CaseFile(cfg.casefile_path)
        records = casefile.search(" ".join(words)) if words else casefile.recent(limit=10)
    except sqlite3.Error as e:
        print(f"Couldn't read the case file ({e}).", file=sys.stderr)
        return 1
    if as_json:
        _out([_case(r) for r in records])
    elif not records:
        print("No matching cases.", file=sys.stderr)
    else:
        for r in records:
            proven = "  (worked)" if r.worked else ""
            print(f"#{r.id}  {r.created_at:%Y-%m-%d}  {r.mode}: {r.key or r.question[:70]}{proven}")
    return 0


def _assignment(a, plan) -> dict:
    return {
        "id": a.uid,
        "title": a.title,
        "course": a.course,
        "due": a.due.isoformat() if a.due else None,
        "url": a.url,
        "points": a.points,
        "submitted": a.submitted,
        "priority": plan.priority if plan else None,
        "hours": plan.hours if plan else None,
        "start_by": plan.start_by.isoformat() if plan and plan.start_by else None,
        "tip": plan.tip if plan else None,
    }


async def canvas(cfg: Config, as_json: bool, *, command_factory=None, provider_factory=None) -> int:
    """Sync Canvas like /canvas (plans and Notion included); print the table, or JSON with --json."""
    from .brain import ProviderError, make_provider
    from .canvas.command import CanvasCommand
    from .ui import UI

    provider = None
    try:
        provider = (provider_factory or make_provider)(cfg.default_model, cfg)
    except ProviderError as e:
        print(f"{e} Assignments will come without plans.", file=sys.stderr)
    ui = UI(Console(stderr=True) if as_json else Console(), animations=False)
    command = (command_factory or CanvasCommand)(cfg, ui, lambda: provider)
    result = await command.sync(table=not as_json)
    if result is None:
        return 1
    assignments, plans = result
    if as_json:
        _out([_assignment(a, plans.get(a.uid)) for a in assignments])
    return 0
