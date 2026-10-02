"""What Fixel tells the model about you: hand-editable about-me notes and similar past cases."""

from __future__ import annotations

from pathlib import Path

from .casefile import CaseRecord

ABOUT_ME_HEADER = "# About me\n\nFixel sends these notes to the AI with every question. Edit freely; one fact per `- ` line.\n\n"
ANSWER_LIMIT = 800  # characters of each past answer to include


class AboutMe:
    """Facts stored as `- ` bullet lines in a Markdown file. Other lines are left alone."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _lines(self) -> list[str]:
        return self.path.read_text().splitlines(keepends=True) if self.path.exists() else []

    def notes(self) -> list[str]:
        return [line[2:].strip() for line in self._lines() if line.startswith("- ") and line[2:].strip()]

    def add(self, fact: str) -> None:
        fact = " ".join(fact.split())
        if not fact:
            return
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(ABOUT_ME_HEADER)
        text = self.path.read_text()
        if text and not text.endswith("\n"):
            text += "\n"
        self.path.write_text(f"{text}- {fact}\n")

    def forget(self, number: int) -> str | None:
        """Remove the `number`-th note (1-based). Returns its text, or None if there's no such note."""
        lines = self._lines()
        seen = 0
        for index, line in enumerate(lines):
            if line.startswith("- ") and line[2:].strip():
                seen += 1
                if seen == number:
                    del lines[index]
                    self.path.write_text("".join(lines))
                    return line[2:].strip()
        return None


def past_cases_context(records: list[CaseRecord]) -> str:
    """A block prepended to a new question so the model can reuse what worked before."""
    if not records:
        return ""
    parts = ["[Fixel memory: this user's past cases that look similar. Use them only if relevant.]"]
    for record in records:
        proven = " (the user confirmed this fix worked)" if record.worked else ""
        answer = record.answer.strip()[:ANSWER_LIMIT]
        parts.append(
            f"Past case from {record.created_at:%b %d}{proven}:\nProblem: {record.key or record.question}\nAnswer given:\n{answer}"
        )
    parts.append("[End of Fixel memory]")
    return "\n\n".join(parts)
