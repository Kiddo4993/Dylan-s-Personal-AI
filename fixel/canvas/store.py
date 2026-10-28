"""~/.fixel/canvas.json: your /canvas settings and what's been synced. Tokens never go here (Keychain only)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .items import Plan


@dataclass
class Synced:
    """One assignment's Notion row, as Fixel last wrote it."""

    facts: str = ""  # fingerprint of the Canvas facts last sent, so unchanged rows aren't rewritten
    planned: bool = False  # the AI fields were written (they never are again)


@dataclass
class CanvasStore:
    path: Path
    source: str = ""  # "api" or "feed"
    base: str = ""  # https://yourschool.instructure.com
    notion_database: str = ""
    plans: dict[str, Plan] = field(default_factory=dict)
    synced: dict[str, Synced] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> CanvasStore:
        store = cls(path)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return store
        store.source = data.get("source", "")
        store.base = data.get("base", "")
        store.notion_database = data.get("notion_database", "")
        for uid, plan in data.get("plans", {}).items():
            try:
                store.plans[uid] = Plan.from_json(plan)
            except (TypeError, ValueError):
                continue  # a hand-edited plan that no longer parses is simply planned again
        for uid, row in data.get("synced", {}).items():
            store.synced[uid] = Synced(facts=row.get("facts", ""), planned=bool(row.get("planned")))
        return store

    def save(self) -> None:
        data = {
            "source": self.source,
            "base": self.base,
            "notion_database": self.notion_database,
            "plans": {uid: plan.to_json() for uid, plan in self.plans.items()},
            "synced": {uid: {"facts": row.facts, "planned": row.planned} for uid, row in self.synced.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=1))
        os.chmod(temp, 0o600)  # your coursework is nobody else's business on a shared Mac
        temp.replace(self.path)
