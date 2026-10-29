"""Regenerate the README's screenshots from Fixel's real rendering code: `.venv/bin/python scripts/screenshots.py`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI

from fixel.canvas.items import Assignment, Plan
from fixel.casefile import CaseRecord
from fixel.home import Check, HomeInfo, render_home
from fixel.parse import split_header
from fixel.ui import UI

OUT = Path(__file__).parents[1] / "docs" / "images"
WIDTH = 100

ANSWER = """MODE: error
KEY: ModuleNotFoundError: pandas
---
**Cause:** `pandas` isn't installed in the Python that ran `app.py`.

**Fix:**
```bash
python3 -m pip install pandas
```

Run it with the same `python3` you used for `app.py`, so it installs into the right environment.
"""


def save(name: str, draw) -> None:
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor")
    draw(UI(console, animations=False), console)
    console.save_svg(str(OUT / f"{name}.svg"), title="Fixel", theme=MONOKAI)
    print(f"wrote docs/images/{name}.svg")


def home(ui: UI, console: Console) -> None:
    checks = [Check("⌥⌥ hotkey", True), Check("screenshots", True), Check("API key", True)]
    when = datetime(2026, 10, 27, 21, 30)
    recent = [
        CaseRecord(3, when, "error", "ModuleNotFoundError: pandas", "", "", [], worked=True),
        CaseRecord(2, when - timedelta(hours=5), "math", "Related rates: ladder sliding down a wall", "", "", []),
        CaseRecord(1, when - timedelta(days=1), "web", "Recreate this landing page", "", "", []),
    ]
    info = HomeInfo(name="Sam", model="claude-sonnet-5-5", checks=checks, solved=128, worked=41, notes=3,
                    recent=recent, tip="Type /learn for learn mode: hints instead of answers.")
    console.print(render_home(info, WIDTH))


def answer(ui: UI, console: Console) -> None:
    console.print("[cyan]›[/] why won't this run?")
    header, body = split_header(ANSWER, final=True)
    console.print(ui.answer_view(header, body))
    ui.answer_footer("claude-sonnet-5-5", "claude-sonnet-5-5", 3.2, False)
    ui.action_bar()


def canvas(ui: UI, console: Console) -> None:
    now = datetime(2026, 10, 27, 15, 0).astimezone()
    day = lambda n, h=23, m=59: (now + timedelta(days=n)).replace(hour=h, minute=m)  # noqa: E731
    work = [
        Assignment("assignment-1", "Unit 4 FRQ practice set", "AP Computer Science A", day(0, 22)),
        Assignment("assignment-2", "Lab report: titration", "Chemistry", day(2)),
        Assignment("quiz-3", "Derivatives quiz", "AP Calculus BC", day(3, 8, 0), submitted=True),
        Assignment("assignment-4", "Essay 2: final draft", "English 11", day(6)),
    ]
    plans = {
        "assignment-1": Plan("High", 1.5, now.date(), "Time each FRQ at 22 minutes, like the real exam."),
        "assignment-2": Plan("Medium", 2, now.date() + timedelta(days=1), "Do the calculations section first while the data is fresh."),
        "assignment-4": Plan("Medium", 3, now.date() + timedelta(days=3), "Read it aloud once; it catches run-ons fast."),
    }
    console.print("[cyan]›[/] /canvas")
    ui.info("Checking Canvas (myschool.instructure.com)…")
    ui.canvas_table(work, plans, now, 14)
    ui.info("Notion: 3 added, 1 updated.")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in (("home", home), ("answer", answer), ("canvas", canvas)):
        save(name, draw)
