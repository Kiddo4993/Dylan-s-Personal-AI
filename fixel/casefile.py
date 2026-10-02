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
  shot_paths TEXT NOT NULL,
  screen_text TEXT NOT NULL DEFAULT '',
  worked INTEGER NOT NULL DEFAULT 0
);
"""
_FTS_COLUMNS = ("key", "question", "answer", "screen_text")
_COLUMNS = "id, created_at, mode, key, question, answer, shot_paths, screen_text, worked"
MAX_QUERY_TOKENS = 200  # a full-screen capture can hold thousands of words


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", text.lower()))


def _match_any(words: set[str]) -> str:
    return " OR ".join(f'"{w}"' for w in sorted(words)[:MAX_QUERY_TOKENS])


@dataclass(frozen=True)
class CaseRecord:
    id: int
    created_at: datetime
    mode: str
    key: str
    question: str
    answer: str
    shot_paths: list[str]
    screen_text: str = ""
    worked: bool = False


class CaseFile:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)
        self._upgrade()

    def _upgrade(self) -> None:
        """Bring a case file from an older Fixel up to date, keeping every case."""
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(cases)")}
        with self._db:
            if "screen_text" not in columns:
                self._db.execute("ALTER TABLE cases ADD COLUMN screen_text TEXT NOT NULL DEFAULT ''")
            if "worked" not in columns:
                self._db.execute("ALTER TABLE cases ADD COLUMN worked INTEGER NOT NULL DEFAULT 0")
            fts_columns = tuple(row[1] for row in self._db.execute("PRAGMA table_info(cases_fts)"))
            if fts_columns != _FTS_COLUMNS:  # missing or from an older version: rebuild the search index
                self._db.execute("DROP TABLE IF EXISTS cases_fts")
                self._db.execute(f"CREATE VIRTUAL TABLE cases_fts USING fts5({', '.join(_FTS_COLUMNS)})")
                self._db.execute(
                    "INSERT INTO cases_fts (rowid, key, question, answer, screen_text) "
                    "SELECT id, key, question, answer, screen_text FROM cases"
                )

    def save(
        self,
        *,
        case_id: int | None,
        mode: str,
        key: str,
        question: str,
        answer: str,
        shot_paths: list,
        screen_text: str = "",
        now: datetime | None = None,
    ) -> int:
        shots = json.dumps([str(p) for p in shot_paths])
        with self._db:
            if case_id is None:
                created = (now or datetime.now()).isoformat(timespec="seconds")
                cursor = self._db.execute(
                    "INSERT INTO cases (created_at, mode, key, question, answer, shot_paths, screen_text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (created, mode, key, question, answer, shots, screen_text),
                )
                case_id = cursor.lastrowid
            else:
                self._db.execute(
                    "UPDATE cases SET mode = ?, key = ?, question = ?, answer = ?, shot_paths = ?, screen_text = ? "
                    "WHERE id = ?",
                    (mode, key, question, answer, shots, screen_text, case_id),
                )
                self._db.execute("DELETE FROM cases_fts WHERE rowid = ?", (case_id,))
            self._db.execute(
                "INSERT INTO cases_fts (rowid, key, question, answer, screen_text) VALUES (?, ?, ?, ?, ?)",
                (case_id, key, question, answer, screen_text),
            )
        return case_id

    def mark_worked(self, case_id: int) -> None:
        with self._db:
            self._db.execute("UPDATE cases SET worked = 1 WHERE id = ?", (case_id,))

    def get(self, case_id: int) -> CaseRecord | None:
        row = self._db.execute(f"SELECT {_COLUMNS} FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        cid, created, mode, key, question, answer, shots, screen_text, worked = row
        return CaseRecord(
            cid, datetime.fromisoformat(created), mode, key, question, answer, json.loads(shots), screen_text, bool(worked)
        )

    def similar(
        self, text: str, *, exclude_id: int | None = None, limit: int = 2, threshold: float = 0.6
    ) -> list[CaseRecord]:
        """Past cases whose key (e.g. an error message) shows up in `text` (e.g. the new screen).

        A case counts when at least `threshold` of its key's words appear in `text`.
        Fixes the user marked as worked come first, then closer matches, then newer cases.
        """
        wanted = tokens(text)
        if not wanted:
            return []
        rows = self._db.execute(
            "SELECT rowid FROM cases_fts WHERE cases_fts MATCH ? ORDER BY rank LIMIT 20",
            (f"key : ({_match_any(wanted)})",),
        ).fetchall()
        scored = []
        for (rowid,) in rows:
            if rowid == exclude_id:
                continue
            record = self.get(rowid)
            key_words = tokens(record.key) if record else set()
            if not key_words:
                continue
            coverage = len(key_words & wanted) / len(key_words)
            if coverage >= threshold:
                scored.append((record.worked, coverage, record.created_at, record))
        scored.sort(key=lambda item: item[:3], reverse=True)
        return [record for *_, record in scored[:limit]]

    def search(self, query: str, limit: int = 10) -> list[CaseRecord]:
        words = tokens(query)
        if not words:
            return []
        rows = self._db.execute(
            "SELECT rowid FROM cases_fts WHERE cases_fts MATCH ? ORDER BY rank LIMIT ?", (_match_any(words), limit)
        ).fetchall()
        return [record for (rowid,) in rows if (record := self.get(rowid)) is not None]
