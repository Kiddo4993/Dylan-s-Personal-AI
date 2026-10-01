"""Local memory of solved problems: SQLite + FTS5 at ~/.fixel/casefile.db."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  key TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  shot_paths TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(key, question, answer);
"""


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", text.lower()))


def _match_any(words: set[str]) -> str:
    return " OR ".join(f'"{w}"' for w in sorted(words))


@dataclass(frozen=True)
class CaseRecord:
    id: int
    created_at: datetime
    mode: str
    key: str
    question: str
    answer: str
    shot_paths: list[str]


class CaseFile:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)

    def save(
        self,
        *,
        case_id: int | None,
        mode: str,
        key: str,
        question: str,
        answer: str,
        shot_paths: list,
        now: datetime | None = None,
    ) -> int:
        shots = json.dumps([str(p) for p in shot_paths])
        with self._db:
            if case_id is None:
                created = (now or datetime.now()).isoformat(timespec="seconds")
                cursor = self._db.execute(
                    "INSERT INTO cases (created_at, mode, key, question, answer, shot_paths) VALUES (?, ?, ?, ?, ?, ?)",
                    (created, mode, key, question, answer, shots),
                )
                case_id = cursor.lastrowid
            else:
                self._db.execute(
                    "UPDATE cases SET mode = ?, key = ?, question = ?, answer = ?, shot_paths = ? WHERE id = ?",
                    (mode, key, question, answer, shots, case_id),
                )
                self._db.execute("DELETE FROM cases_fts WHERE rowid = ?", (case_id,))
            self._db.execute(
                "INSERT INTO cases_fts (rowid, key, question, answer) VALUES (?, ?, ?, ?)",
                (case_id, key, question, answer),
            )
        return case_id

    def get(self, case_id: int) -> CaseRecord | None:
        row = self._db.execute(
            "SELECT id, created_at, mode, key, question, answer, shot_paths FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None
        cid, created, mode, key, question, answer, shots = row
        return CaseRecord(cid, datetime.fromisoformat(created), mode, key, question, answer, json.loads(shots))

    def recall(self, key: str, *, exclude_id: int | None, threshold: float = 0.6) -> CaseRecord | None:
        """The most similar past case by key-token overlap (Jaccard), if it clears `threshold`."""
        wanted = tokens(key)
        if not wanted:
            return None
        rows = self._db.execute(
            "SELECT rowid FROM cases_fts WHERE cases_fts MATCH ? ORDER BY rank LIMIT 10",
            (f"key : ({_match_any(wanted)})",),
        ).fetchall()
        best, best_score = None, 0.0
        for (rowid,) in rows:
            if rowid == exclude_id:
                continue
            record = self.get(rowid)
            if record is None:
                continue
            theirs = tokens(record.key)
            score = len(wanted & theirs) / len(wanted | theirs)
            if score > best_score:
                best, best_score = record, score
        return best if best_score >= threshold else None

    def search(self, query: str, limit: int = 10) -> list[CaseRecord]:
        words = tokens(query)
        if not words:
            return []
        rows = self._db.execute(
            "SELECT rowid FROM cases_fts WHERE cases_fts MATCH ? ORDER BY rank LIMIT ?", (_match_any(words), limit)
        ).fetchall()
        return [record for (rowid,) in rows if (record := self.get(rowid)) is not None]
