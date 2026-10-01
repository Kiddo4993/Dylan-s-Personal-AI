"""Fixel's main loop: wires hotkey, capture, model, memory, and UI together."""

from __future__ import annotations

import asyncio
import signal
import sqlite3
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from . import actions, permissions
from .brain import Provider, ProviderError, make_provider
from .capture import capture_region
from .casefile import CaseFile, CaseRecord
from .config import Config
from .hotkey import HotkeyListener
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
    ) -> None:
        self.cfg = cfg
        self.ui = ui
        self.session = Session()
        self.provider: Provider | None = None
        self.model_alias = cfg.default_model
        self.casefile = casefile
        self.last_recall: CaseRecord | None = None
        self.screen_ok = True
        self._provider_factory = provider_factory
        self._capture = capture
        self._raise_window = raise_window
        self._hotkeys: asyncio.Queue[None] = asyncio.Queue()

    # ---- startup

    def select_model(self, alias: str) -> bool:
        try:
            self.provider = self._provider_factory(alias, self.cfg)
        except ProviderError as e:
            self.ui.error(str(e))
            return False
        self.model_alias = alias
        return True

    def _open_casefile(self) -> None:
        if self.casefile is not None:
            return
        try:
            self.casefile = CaseFile(self.cfg.casefile_path)
        except sqlite3.Error as e:
            self.ui.warn(f"Case file unavailable ({e}); memory is off this session.")

    def _start_hotkey(self) -> None:
        loop = asyncio.get_running_loop()
        app_name = permissions.host_app()
        listener = HotkeyListener(
            lambda: loop.call_soon_threadsafe(self._hotkeys.put_nowait, None), window=self.cfg.double_tap_window
        )
        hotkey_ok = permissions.input_monitoring_granted() and listener.start()
        self.ui.status.hotkey_ok = hotkey_ok
        if not hotkey_ok:
            self.ui.error(
                f"Hotkey is off: allow {app_name} in System Settings → Privacy & Security → Input Monitoring, "
                "then reopen it. `fixel setup` walks you through it."
            )
        self.screen_ok = permissions.screen_recording_granted()
        if not self.screen_ok:
            self.ui.error(
                f"Screenshots are off: allow {app_name} in System Settings → Privacy & Security → "
                "Screen & System Audio Recording, then reopen it."
            )

    async def startup(self) -> None:
        alias = self.cfg.default_model
        self.ui.banner(self.cfg.models.get(alias, alias), self.session.learn)
        self._open_casefile()
        self.select_model(alias)
        self._start_hotkey()
        self.ui.info("Double-tap Right Option ⌥ to screenshot. /help for keys.")

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
        if await self._capture(path):
            self.session.add_shot(path)
        self._sync_status()
        if self._raise_window is not None:
            await self._raise_window()

    def _sync_status(self) -> None:
        self.ui.status.tray = len(self.session.tray)
        self.ui.status.follow_up = self.session.follow_up

    # ---- asking

    async def ask(self, text: str) -> str:
        """Send the tray + text. Returns text to put back at the prompt (empty on success)."""
        if self.provider is None:
            self.ui.error("No model is ready. Run `fixel setup`, then `/model sonnet`.")
            return text
        self.session.build_user_turn(text)
        self._sync_status()
        system = build_system(self.session.learn)
        try:
            finished, answer = await self._interruptible(
                self.ui.stream_answer(self.provider.stream(list(self.session.case.turns), system))
            )
        except Exception as e:  # ProviderError is expected; anything else is an SDK surprise
            self.session.rollback()
            self._sync_status()
            message = str(e) if isinstance(e, ProviderError) else f"Unexpected error from {self.provider.name}: {e!r}"
            hint = " Your screenshots are still in the tray. Press Enter to retry." if self.session.tray else ""
            self.ui.error(f"{message}{hint}")
            return text
        if not finished:
            self.session.rollback()
            self._sync_status()
            self.ui.warn("Stopped.")
            return text
        header, raw, body = answer
        self.session.record_answer(header, raw, body)
        self._remember()
        self.ui.action_bar()
        return ""

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

    def _remember(self) -> None:
        case = self.session.case
        if self.casefile is None or case.header is None:
            return
        first_answer = len(case.turns) == 2
        try:
            case.case_id = self.casefile.save(
                case_id=case.case_id, mode=case.header.mode, key=case.header.key,
                question=case.question, answer=case.answer, shot_paths=case.shots,
            )
            record = None
            if first_answer and case.header.key:
                record = self.casefile.recall(
                    case.header.key, exclude_id=case.case_id, threshold=self.cfg.recall_threshold
                )
        except sqlite3.Error as e:
            self.ui.warn(f"Case file error ({e}); memory is off this session.")
            self.casefile = None
            return
        if first_answer:
            self.last_recall = record
        if record is not None:
            self.ui.recall_line(record)

    # ---- keys and commands

    async def handle_action(self, name: str) -> None:
        case = self.session.case
        if name == "copy":
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
            self.session.learn = not self.session.learn
            if self.session.learn:
                self.ui.info("Learn mode on: you'll get hints and guiding questions. Send /answer for the full solution.")
            else:
                self.ui.info("Learn mode off: full answers.")
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
        elif command == "/answer":
            if not self.session.learn:
                self.ui.info("Learn mode is off, so answers are already complete.")
            elif not self.session.case.turns:
                self.ui.warn("Nothing to answer yet.")
            else:
                await self.ask("/answer")
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
