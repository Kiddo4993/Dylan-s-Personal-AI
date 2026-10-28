"""An assignment as Canvas reports it, and the plan the AI adds to it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

PRIORITIES = ("High", "Medium", "Low")


@dataclass(frozen=True)
class Assignment:
    uid: str  # "assignment-123": the same whether it came from the API or the calendar feed
    title: str
    course: str
    due: datetime | None  # timezone-aware
    url: str = ""
    points: float | None = None
    submitted: bool = False


@dataclass(frozen=True)
class Plan:
    """What the AI adds. Written to Notion once, so your own edits to these fields stick."""

    priority: str  # one of PRIORITIES
    hours: float
    start_by: date | None
    tip: str

    def to_json(self) -> dict:
        return {
            "priority": self.priority,
            "hours": self.hours,
            "start_by": self.start_by.isoformat() if self.start_by else None,
            "tip": self.tip,
        }

    @classmethod
    def from_json(cls, data: dict) -> Plan:
        start = data.get("start_by")
        return cls(
            priority=data.get("priority", "Medium"),
            hours=float(data.get("hours", 1)),
            start_by=date.fromisoformat(start) if start else None,
            tip=data.get("tip", ""),
        )
