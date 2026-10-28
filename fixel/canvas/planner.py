"""Ask your AI model for a priority, hours, start-by date and one tip per assignment."""

from __future__ import annotations

import json
import re
from datetime import date

from ..brain.base import Provider, Turn
from .items import PRIORITIES, Assignment, Plan

BATCH = 20  # assignments per request: small enough that one bad answer costs little

SYSTEM = """\
You plan a high-school or college student's schoolwork. For every assignment you are given, decide:
- priority: "High", "Medium" or "Low", from how soon it is due and how much it is worth
- hours: a realistic estimate of the work, in hours (0.25 to 40)
- start_by: the date (YYYY-MM-DD) to start so it is done comfortably before it is due; never after the due date
- tip: one short, specific, practical sentence for doing this assignment well

Reply with only a JSON array, one object per assignment, in this shape and nothing else:
[{"id": "<the id you were given>", "priority": "High", "hours": 2, "start_by": "2026-01-31", "tip": "..."}]
"""


class PlannerError(Exception):
    """The model's answer couldn't be used."""


def build_prompt(assignments: list[Assignment], today: date) -> str:
    rows = [
        {
            "id": a.uid,
            "title": a.title,
            "course": a.course,
            "due": a.due.astimezone().strftime("%Y-%m-%d %H:%M") if a.due else None,
            "points": a.points,
        }
        for a in assignments
    ]
    return f"Today is {today.isoformat()} ({today:%A}).\n\nAssignments:\n{json.dumps(rows, indent=1)}"


def parse_plans(text: str, assignments: list[Assignment], today: date) -> dict[str, Plan]:
    """The model's JSON, checked: unknown ids dropped, every field forced into range."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        raise PlannerError("The model didn't send a plan (no JSON list in its answer).")
    try:
        rows = json.loads(cleaned[start : end + 1])
    except ValueError:
        raise PlannerError("The model's plan wasn't valid JSON.") from None
    by_id = {a.uid: a for a in assignments}
    plans: dict[str, Plan] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("id") not in by_id:
            continue
        plans[row["id"]] = _checked(row, by_id[row["id"]], today)
    return plans


def _checked(row: dict, assignment: Assignment, today: date) -> Plan:
    priority = str(row.get("priority", "")).strip().title()
    if priority not in PRIORITIES:
        priority = "Medium"
    try:
        hours = float(row.get("hours", 1))
    except (TypeError, ValueError):
        hours = 1.0
    hours = round(min(max(hours, 0.25), 40.0) * 4) / 4  # nearest quarter hour
    try:
        start_by = date.fromisoformat(str(row.get("start_by"))[:10])
    except ValueError:
        start_by = None
    due_day = assignment.due.astimezone().date() if assignment.due else None
    if start_by is not None:
        if due_day is not None and start_by > due_day:
            start_by = due_day
        start_by = max(start_by, min(today, due_day or today))  # not in the past, unless it's already overdue
    tip = " ".join(str(row.get("tip") or "").split())[:200]
    return Plan(priority=priority, hours=hours, start_by=start_by, tip=tip)


async def make_plans(provider: Provider, assignments: list[Assignment], today: date) -> dict[str, Plan]:
    plans: dict[str, Plan] = {}
    for first in range(0, len(assignments), BATCH):
        batch = assignments[first : first + BATCH]
        reply = ""
        async for chunk in provider.stream([Turn("user", build_prompt(batch, today))], SYSTEM):
            reply += chunk
        plans.update(parse_plans(reply, batch, today))
    return plans
