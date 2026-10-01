"""Right-Option double-tap detection.

DoubleTapDetector is pure timing logic. HotkeyListener feeds it from a macOS
Quartz listen-only event tap running on its own thread. We read raw keycodes
and never translate them to characters, which is what makes pynput crash on
recent macOS.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

RIGHT_OPTION_KEYCODE = 61
RIGHT_OPTION_DEVICE_FLAG = 0x40  # NX_DEVICERALTKEYMASK


@dataclass
class DoubleTapDetector:
    window: float = 0.4
    _down: bool = False
    _chorded: bool = False  # another key was pressed while Right Option was held
    _last_tap: float | None = None

    def option_down(self, t: float) -> None:
        self._down = True
        self._chorded = False

    def other_key(self, t: float) -> None:
        if self._down:
            self._chorded = True
        self._last_tap = None  # any other key breaks a pending double-tap

    def option_up(self, t: float) -> bool:
        """Register a release; True when it completes a double-tap."""
        if not self._down:
            return False
        self._down = False
        if self._chorded:
            self._last_tap = None
            return False
        if self._last_tap is not None and t - self._last_tap <= self.window:
            self._last_tap = None  # consumed: a third tap starts a fresh pair
            return True
        self._last_tap = t
        return False


class HotkeyListener:
    def __init__(self, on_trigger: Callable[[], None], window: float = 0.4) -> None:
        self._detector = DoubleTapDetector(window=window)
        self._on_trigger = on_trigger
        self._tap = None

    def start(self) -> bool:
        """Start listening on a daemon thread. False if macOS refused (no Input Monitoring)."""
        import Quartz

        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if self._tap is None:
            return False

        def run() -> None:
            source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            Quartz.CFRunLoopRun()

        threading.Thread(target=run, name="fixel-hotkey", daemon=True).start()
        return True

    def _callback(self, proxy, event_type, event, refcon):
        import Quartz

        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        now = time.monotonic()
        if event_type == Quartz.kCGEventKeyDown:
            self._detector.other_key(now)
        elif event_type == Quartz.kCGEventFlagsChanged:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode != RIGHT_OPTION_KEYCODE:
                self._detector.other_key(now)
            elif Quartz.CGEventGetFlags(event) & RIGHT_OPTION_DEVICE_FLAG:
                self._detector.option_down(now)
            elif self._detector.option_up(now):
                self._on_trigger()
        return event
