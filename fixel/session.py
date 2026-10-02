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
    screen_text: str = ""  # text recognized in this case's screenshots


@dataclass
class _Undo:
    case: Case
    turns: int
    shots: int
    question: str
    screen_text: str
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
    _shot_text: dict[Path, str] = field(default_factory=dict, repr=False)

    def add_shot(self, path: Path, text: str = "") -> bool:
        if len(self.tray) >= MAX_TRAY:
            return False
        self.tray.append(path)
        self._shot_text[path] = text
        return True

    def set_shot_text(self, path: Path, text: str) -> None:
        """Attach recognized text to a shot (recognition finishes after the shot lands in the tray)."""
        self._shot_text[path] = text

    def tray_text(self) -> str:
        return "\n".join(text for path in self.tray if (text := self._shot_text.get(path)))

    def starts_new_case(self) -> bool:
        """Would sending now start a new case (as opposed to following up on the current one)?"""
        return not self.case.turns or (bool(self.tray) and not self.follow_up)

    def new_case(self) -> None:
        self.case = Case()
        self.tray = []
        self.follow_up = False

    def build_user_turn(self, text: str, context: str = "") -> Turn:
        """Move the tray + text into the conversation. A tray sent after an answer
        starts a new case unless follow-up is on; text alone always follows up.
        `context` (Fixel memory) goes to the model ahead of the question but isn't part of it."""
        case = self.case
        self._undo = _Undo(
            case, len(case.turns), len(case.shots), case.question, case.screen_text, list(self.tray), self.follow_up
        )
        if self.tray and case.turns and not self.follow_up:
            self.case = Case()
        question = text.strip() or DEFAULT_QUESTION
        sent = f"{context}\n\n{question}" if context else question
        turn = Turn("user", sent, [path.read_bytes() for path in self.tray])
        self.case.turns.append(turn)
        self.case.shots.extend(self.tray)
        new_text = self.tray_text()
        if new_text:
            self.case.screen_text = f"{self.case.screen_text}\n{new_text}".strip()
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
        undo.case.screen_text = undo.screen_text
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
