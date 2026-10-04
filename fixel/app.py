"""Fixel's main loop: wires hotkey, capture, model, memory, and UI together."""

from __future__ import annotations

import asyncio
import random
import signal
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from . import actions, permissions
from .brain import Provider, ProviderError, make_provider
from .capture import capture_region
from .casefile import CaseFile, CaseRecord
from .config import Config
from .home import TIPS, Check, HomeInfo, mac_first_name
from .hotkey import HotkeyListener
from .memory import AboutMe, past_cases_context
from .ocr import recognize_text_async
from .parse import primary_fix, runnable_command
from .prompts import build_system
from .session import MAX_TRAY, Session
from .ui import UI, KeyAction


class FixelApp:
    def __init__(
        self,
        cfg: Config,
        ui: UI,
        *,
        provider_factory: Callable[[str, Config], Provider] = make_provider,
        capture: Callable[[Path], Awaitable[bytes | None]] = capture_region,
        raise_window: Callable[[], Awaitable[None]] | None = None,
        casefile: CaseFile | None = None,
        ocr: Callable[[Path], Awaitable[str]] = recognize_text_async,
    ) -> None:
        self.cfg = cfg
        self.ui = ui
        self.ui.animations = cfg.animations
        self.session = Session()
        self.provider: Provider | None = None
        self.model_alias = cfg.default_model
        self.casefile = casefile
        self.about_me = AboutMe(cfg.about_me_path)
        self.last_recall: CaseRecord | None = None  # the past case used for the current one (⌃O)
        self.screen_ok = True
        self._provider_factory = provider_factory
        self._capture = capture
        self._ocr = ocr
        self._raise_window = raise_window
        self._hotkeys: asyncio.Queue[None] = asyncio.Queue()

    # ---- startup

    def select_model(self, alias: str) -> bool:
        problem = self._load_model(alias)
        if problem:
            self.ui.error(problem)
        return problem is None

    def _load_model(self, alias: str) -> str | None:
        """Switch to `alias`. Returns what went wrong, or None on success."""
        try:
            self.provider = self._provider_factory(alias, self.cfg)
        except ProviderError as e:
            return str(e)
        self.model_alias = alias
        return None

    def _open_casefile(self) -> None:
        if self.casefile is not None:
            return
        try:
            self.casefile = CaseFile(self.cfg.casefile_path)
        except sqlite3.Error as e:
            self.ui.warn(f"Case file unavailable ({e}); memory is off this session.")

    def _start_hotkey(self) -> list[Check]:
        """Start listening for ⌥⌥ and check screen access. Returns the homepage's readiness checks."""
        loop = asyncio.get_running_loop()
        app_name = permissions.host_app()
        listener = HotkeyListener(
            lambda: loop.call_soon_threadsafe(self._hotkeys.put_nowait, None), window=self.cfg.double_tap_window
        )
        hotkey_ok = permissions.input_monitoring_granted() and listener.start()
        self.ui.status.hotkey_ok = hotkey_ok
        self.screen_ok = permissions.screen_recording_granted()
        return [
            Check(
                "⌥⌥ hotkey", hotkey_ok,
                f"Hotkey is off: allow {app_name} in System Settings → Privacy & Security → Input Monitoring, "
                "then reopen it. `fixel setup` walks you through it.",
            ),
            Check(
                "screenshots", self.screen_ok,
                f"Screenshots are off: allow {app_name} in System Settings → Privacy & Security → "
                "Screen & System Audio Recording, then reopen it.",
            ),
        ]

    async def startup(self) -> None:
        alias = self.cfg.default_model
        self._open_casefile()
        key_problem = self._load_model(alias)
        checks = [*self._start_hotkey(), Check("API key", key_problem is None, key_problem or "")]
        solved, worked, recent = 0, 0, []
        if self.casefile is not None:
            try:
                solved, worked = self.casefile.stats()
                recent = _distinct(self.casefile.recent(limit=20))[:3]
            except sqlite3.Error:
                pass
        self.ui.home(
            HomeInfo(
                name=self.cfg.name or mac_first_name(),
                model=self.provider.name if self.provider else self.cfg.models.get(alias, alias),
                checks=checks,
                solved=solved,
                worked=worked,
                notes=len(self.about_me.notes()),
                recent=recent,
                tip=random.choice(TIPS),
            )
        )

    async def run(self) -> None:
        await self.startup()
        capture_task = asyncio.create_task(self._capture_worker())
        pending = ""
        try:
            while True:
                result = await self.ui.prompt(default=pending)
                pending = ""
                if result is None:
                    break
                if isinstance(result, KeyAction):
                    pending = result.buffer
                    await self.handle_action(result.name)
                    continue
                text = result.strip()
                if text.startswith("/"):
                    if not await self.handle_command(text):
                        break
                elif text or self.session.tray:
                    pending = await self.ask(text)
        finally:
            capture_task.cancel()

    # ---- capture

    async def _capture_worker(self) -> None:
        while True:
            await self._hotkeys.get()
            await self.capture_once()
            while not self._hotkeys.empty():  # drop taps made during the selection
                self._hotkeys.get_nowait()

    async def capture_once(self) -> None:
        status = self.ui.status
        if not self.screen_ok:
            status.flash_msg("⚠ Screen Recording permission is missing. Run `fixel setup`.")
            return
        if len(self.session.tray) >= MAX_TRAY:
            status.flash_msg(f"Tray is full ({MAX_TRAY} shots). Press Enter to ask.")
            return
        path = self.cfg.shots_dir / f"{uuid.uuid4().hex}.png"
        captured = bool(await self._capture(path)) and self.session.add_shot(path)
        self._sync_status()
        if self._raise_window is not None:
            await self._raise_window()
        if captured:  # read the screen after Fixel is in front; it's ready by the time you press Enter
            self.session.set_shot_text(path, await self._ocr(path))

    def _sync_status(self) -> None:
        self.ui.status.tray = len(self.session.tray)
        self.ui.status.follow_up = self.session.follow_up

    # ---- asking

    async def ask(self, text: str) -> str:
        """Send the tray + text. Returns text to put back at the prompt (empty on success)."""
        if self.provider is None:
            self.ui.error("No model is ready. Run `fixel setup`, then `/model sonnet`.")
            return text
        context = self._recall_context(text) if self.session.starts_new_case() else ""
        self.session.build_user_turn(text, context=context)
        self._sync_status()
        answer = await self._stream_answer(deep=False)
        if answer is None:
            self.session.rollback()
            self._sync_status()
            if self.session.tray:
                self.ui.info("Your screenshots are still in the tray. Press Enter to retry.")
            return text
        self._finish(answer)
        return ""

    async def think_harder(self) -> None:
        """⌃T: re-answer the latest question with deep thinking, replacing the quick answer."""
        if self.provider is None or not self.session.retract_answer():
            self.ui.warn("Ask something first, then press ⌃T to re-answer it with deep thinking.")
            return
        self.ui.info("Thinking harder…")
        answer = await self._stream_answer(deep=True)
        if answer is None:
            self.session.restore_answer()
            return
        self._finish(answer)

    async def _stream_answer(self, *, deep: bool):
        """Stream an answer to the current case. Returns (header, raw, body), or None after reporting why not."""
        system = build_system(self.session.learn, self.about_me.notes())
        turns = list(self.session.case.turns)
        images = any(turn.images for turn in turns)
        started = time.monotonic()
        try:
            finished, answer = await self._interruptible(
                self.ui.stream_answer(self.provider.stream(turns, system, deep=deep), images=images, deep=deep)
            )
        except Exception as e:  # ProviderError is expected; anything else is an SDK surprise
            message = str(e) if isinstance(e, ProviderError) else f"Unexpected error from {self.provider.name}: {e!r}"
            self.ui.error(message)
            return None
        if not finished:
            self.ui.warn("Stopped.")
            return None
        self.ui.answer_footer(self.provider.last_model, self.provider.name, time.monotonic() - started, deep)
        return answer

    def _finish(self, answer) -> None:
        self.session.record_answer(*answer)
        self._remember()
        self.ui.action_bar()

    async def _interruptible(self, awaitable) -> tuple[bool, object]:
        """Await `awaitable` so that ⌃C cancels just it, not Fixel. Returns (finished, result)."""
        task = asyncio.ensure_future(awaitable)
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, task.cancel)
            installed = True
        except (NotImplementedError, RuntimeError, ValueError):
            installed = False
        try:
            return True, await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():  # Fixel itself is shutting down
                raise
            return False, None
        finally:
            if installed:
                loop.remove_signal_handler(signal.SIGINT)

    def _recall_context(self, text: str) -> str:
        """For a new case: find similar past cases, show them, and return the memory block for the model."""
        records: list[CaseRecord] = []
        query = f"{text}\n{self.session.tray_text()}".strip()
        if self.casefile is not None and query:
            try:
                records = self.casefile.similar(query, threshold=self.cfg.recall_threshold)
            except sqlite3.Error as e:
                self.ui.warn(f"Case file error ({e}); memory is off this session.")
                self.casefile = None
        self.last_recall = records[0] if records else None
        if records:
            self.ui.memory_line(records, len(self.about_me.notes()))
        return past_cases_context(records)

    def _remember(self) -> None:
        case = self.session.case
        if self.casefile is None or case.header is None:
            return
        try:
            case.case_id = self.casefile.save(
                case_id=case.case_id, mode=case.header.mode, key=case.header.key, question=case.question,
                answer=case.answer, shot_paths=case.shots, screen_text=case.screen_text,
            )
        except sqlite3.Error as e:
            self.ui.warn(f"Case file error ({e}); memory is off this session.")
            self.casefile = None

    # ---- keys and commands

    async def handle_action(self, name: str) -> None:
        case = self.session.case
        if name == "deeper":
            await self.think_harder()
        elif name == "worked":
            if case.case_id is None or self.casefile is None:
                self.ui.warn("Nothing to mark yet. Press ⌃G after a fix works.")
                return
            self.casefile.mark_worked(case.case_id)
            self.ui.react("Nice. Marked as worked. Fixel will reach for this fix first next time.")
        elif name == "copy":
            fix = primary_fix(case.answer) if case.answer else None
            if not fix:
                self.ui.warn("Nothing to copy yet.")
                return
            actions.copy_to_clipboard(fix)
            self.ui.info(f"Copied {len(fix)} characters to the clipboard.")
        elif name == "run":
            command = runnable_command(case.answer) if case.answer else None
            if not command:
                self.ui.warn("This answer has no shell command to run.")
                return
            self.ui.show_command(command)
            if not await self.ui.confirm("Type y to run it (anything else cancels): "):
                self.ui.info("Cancelled. Nothing ran.")
                return
            finished, result = await self._interruptible(actions.run_command(command))
            if not finished:
                self.ui.warn("Stopped the command.")
                return
            self.ui.show_output(*result)
        elif name == "save":
            if not case.answer:
                self.ui.warn("Nothing to save yet.")
                return
            mode = case.header.mode if case.header else "general"
            path = actions.save_note(
                self.cfg.notes_dir, question=case.question, answer=case.answer, mode=mode, shots=case.shots
            )
            self.ui.info(f"Saved {path}")
        elif name == "learn":
            self._set_learn(not self.session.learn)
        elif name == "follow":
            if not self.session.tray:
                self.ui.warn("Take a screenshot first (⌥⌥), then press ⌃F to attach it to this case.")
                return
            self.session.follow_up = not self.session.follow_up
            self._sync_status()
            where = "added to the current case" if self.session.follow_up else "a new case"
            self.ui.info(f"The tray will go to {where}.")
        elif name == "open":
            if self.last_recall is None:
                self.ui.warn("No past case to open.")
            else:
                self.ui.show_case(self.last_recall)
        elif name == "new":
            self.session.new_case()
            self.last_recall = None
            self._sync_status()
            self.ui.info("New case. Double-tap ⌥ to screenshot.")

    def _set_learn(self, on: bool) -> None:
        self.session.learn = on
        if on:
            self.ui.info("Learn mode on: you'll get hints and guiding questions. Send /answer for the full solution.")
        else:
            self.ui.info("Learn mode off: full answers.")

    async def handle_command(self, text: str) -> bool:
        """Run a slash command. Returns False when Fixel should quit."""
        command, _, arg = text.partition(" ")
        arg = arg.strip()
        if command in ("/quit", "/exit"):
            return False
        if command == "/help":
            self.ui.help()
        elif command == "/model":
            if not arg:
                current = self.provider.name if self.provider else "none"
                self.ui.info(f"Model: {self.model_alias} ({current}). Options: {', '.join(self.cfg.models)}")
            elif self.select_model(arg):
                self.ui.banner(self.provider.name, self.session.learn)
        elif command == "/learn":
            choice = arg.lower()
            if choice not in ("", "on", "off"):
                self.ui.warn("Usage: /learn (switch), /learn on, or /learn off")
            else:
                self._set_learn(not self.session.learn if not choice else choice == "on")
        elif command == "/answer":
            if not self.session.learn:
                self.ui.info("Learn mode is off, so answers are already complete.")
            elif not self.session.case.turns:
                self.ui.warn("Nothing to answer yet.")
            else:
                await self.ask("/answer")
        elif command == "/remember":
            if not arg:
                self.ui.warn("Usage: /remember <a fact about you, e.g. I use Python 3.12 and zsh>")
            else:
                self.about_me.add(arg)
                self.ui.info(f"Remembered. Fixel will tell the AI this with every question. ({self.cfg.about_me_path})")
        elif command == "/memory":
            notes = self.about_me.notes()
            if not notes:
                self.ui.info("No notes yet. Add one with /remember <fact>.")
            for number, note in enumerate(notes, 1):
                self.ui.info(f"{number}. {note}")
        elif command == "/forget":
            removed = self.about_me.forget(int(arg)) if arg.isdigit() else None
            if removed is None:
                self.ui.warn("Usage: /forget <number from /memory>")
            else:
                self.ui.info(f"Forgot: {removed}")
        elif command == "/cases":
            if self.casefile is None:
                self.ui.warn("Memory is off this session.")
            elif not arg:
                self.ui.warn("Usage: /cases <words to search for>")
            else:
                records = self.casefile.search(arg)
                if records:
                    self.ui.show_cases(records)
                else:
                    self.ui.info("No matching cases.")
        elif command == "/open":
            record = self.casefile.get(int(arg)) if self.casefile and arg.isdigit() else None
            if record is None:
                self.ui.warn("Usage: /open <number from /cases>")
            else:
                self.ui.show_case(record)
        else:
            self.ui.warn(f"Unknown command {command}. Try /help.")
        return True


def _distinct(records: list[CaseRecord]) -> list[CaseRecord]:
    """Newest case for each different problem, so repeats don't crowd the homepage."""
    seen: set[str] = set()
    unique = []
    for record in records:
        problem = (record.key or record.question).strip().lower()
        if problem not in seen:
            seen.add(problem)
            unique.append(record)
    return unique
