"""Tray and case state. Pure logic apart from reading tray PNGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .brain.base import Turn
from .parse import Header

MAX_TRAY = 5
DEFAULT_QUESTION = "Figure this out."


@dataclass
class Case:
    turns: list[Turn] = field(default_factory=list)
    shots: list[Path] = field(default_factory=list)
    header: Header | None = None
    question: str = ""  # the first question, used for notes and the case file
    answer: str = ""  # the latest answer body (header removed)
    case_id: int | None = None


@dataclass
class _Undo:
    case: Case
    turns: int
    shots: int
    question: str
    tray: list[Path]
    follow_up: bool


@dataclass
class Session:
    case: Case = field(default_factory=Case)
    tray: list[Path] = field(default_factory=list)
    follow_up: bool = False  # attach the next tray to the current case instead of starting a new one
    learn: bool = False
    _undo: _Undo | None = field(default=None, repr=False)
    _retracted: tuple[Turn, str] | None = field(default=None, repr=False)

    def add_shot(self, path: Path) -> bool:
        if len(self.tray) >= MAX_TRAY:
            return False
        self.tray.append(path)
        return True

    def new_case(self) -> None:
        self.case = Case()
        self.tray = []
        self.follow_up = False

    def build_user_turn(self, text: str) -> Turn:
        """Move the tray + text into the conversation. A tray sent after an answer
        starts a new case unless follow-up is on; text alone always follows up."""
        case = self.case
        self._undo = _Undo(case, len(case.turns), len(case.shots), case.question, list(self.tray), self.follow_up)
        if self.tray and case.turns and not self.follow_up:
            self.case = Case()
        question = text.strip() or DEFAULT_QUESTION
        turn = Turn("user", question, [path.read_bytes() for path in self.tray])
        self.case.turns.append(turn)
        self.case.shots.extend(self.tray)
        if not self.case.question:
            self.case.question = question
        self.tray = []
        self.follow_up = False
        return turn

    def rollback(self) -> None:
        """Undo the last build_user_turn (the model call failed or was cancelled)."""
        undo = self._undo
        if undo is None:
            return
        self.case = undo.case
        del undo.case.turns[undo.turns :]
        del undo.case.shots[undo.shots :]
        undo.case.question = undo.question
        self.tray = undo.tray
        self.follow_up = undo.follow_up
        self._undo = None

    def retract_answer(self) -> bool:
        """Take back the latest answer so its question can be re-asked (⌃T). False if there's none."""
        turns = self.case.turns
        if not turns or turns[-1].role != "assistant":
            return False
        self._retracted = (turns.pop(), self.case.answer)
        return True

    def restore_answer(self) -> None:
        """Put a retracted answer back (the re-ask failed or was stopped)."""
        if self._retracted is None:
            return
        turn, answer = self._retracted
        self.case.turns.append(turn)
        self.case.answer = answer
        self._retracted = None

    def record_answer(self, header: Header, raw: str, body: str) -> None:
        previous = self.case.header
        self.case.header = header if previous is None else Header(header.mode, header.key or previous.key)
        self.case.turns.append(Turn("assistant", raw))
        self.case.answer = body
        self._undo = None
        self._retracted = None
