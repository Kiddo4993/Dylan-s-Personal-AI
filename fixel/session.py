"""Tray and case state. Pure logic apart from reading tray PNGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .brain.base import Turn
from .parse import Header
from .playground.attachment import CodeAttachment

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
    code: CodeAttachment | None


@dataclass
class Session:
    case: Case = field(default_factory=Case)
    tray: list[Path] = field(default_factory=list)
    follow_up: bool = False  # attach the next tray to the current case instead of starting a new one
    learn: bool = False
    code: CodeAttachment | None = None  # code from the playground, waiting to be asked about
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

    def attach_code(self, att: CodeAttachment) -> None:
        """Put playground code in the tray (one at a time; a new one replaces the old)."""
        self.code = att

    def tray_text(self) -> str:
        """Searchable text waiting to be sent: what's on the tray's screenshots, plus any attached code and its output."""
        texts = [text for path in self.tray if (text := self._shot_text.get(path))]
        if self.code is not None:
            texts += [part for part in (self.code.code.strip(), self.code.output.strip()) if part]
        return "\n".join(texts)

    def starts_new_case(self) -> bool:
        """Would sending now start a new case (as opposed to following up on the current one)?"""
        return not self.case.turns or ((bool(self.tray) or self.code is not None) and not self.follow_up)

    def new_case(self) -> None:
        self.case = Case()
        self.tray = []
        self.follow_up = False
        self.code = None

    def build_user_turn(self, text: str, context: str = "") -> Turn:
        """Move the tray + text into the conversation. A tray sent after an answer
        starts a new case unless follow-up is on; text alone always follows up.
        `context` (Fixel memory) goes to the model ahead of the question but isn't part of it."""
        case = self.case
        self._undo = _Undo(
            case, len(case.turns), len(case.shots), case.question, case.screen_text, list(self.tray), self.follow_up,
            self.code,
        )
        if (self.tray or self.code is not None) and case.turns and not self.follow_up:
            self.case = Case()
        default = self.code.default_question() if self.code is not None else DEFAULT_QUESTION
        question = text.strip() or default
        attached = self.code.to_prompt_text() if self.code is not None else ""
        sent = "\n\n".join(part for part in (context, attached, question) if part)
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
        self.code = None
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
        meanwhile = [path for path in self.tray if path not in undo.tray]  # shots taken while it streamed
        self.tray = (undo.tray + meanwhile)[:MAX_TRAY]
        self.follow_up = undo.follow_up
        if self.code is None:  # keep code that arrived while the answer streamed; it's newer
            self.code = undo.code
        self._undo = None

    def retract_answer(self) -> bool:
        """Take back the latest answer so its question can be re-asked (/deeper). False if there's none."""
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
