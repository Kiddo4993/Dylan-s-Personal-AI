"""macOS privacy checks. Fixel inherits these permissions from the terminal app it runs in."""

from __future__ import annotations

import os
import subprocess

INPUT_MONITORING_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
SCREEN_RECORDING_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"


def host_app() -> str:
    names = {"Apple_Terminal": "Terminal", "vscode": "Visual Studio Code", "iTerm.app": "iTerm"}
    return names.get(os.environ.get("TERM_PROGRAM", ""), "your terminal app")


def input_monitoring_granted() -> bool:
    import Quartz

    return bool(Quartz.CGPreflightListenEventAccess())


def screen_recording_granted() -> bool:
    import Quartz

    return bool(Quartz.CGPreflightScreenCaptureAccess())


def request_input_monitoring() -> None:
    import Quartz

    Quartz.CGRequestListenEventAccess()


def request_screen_recording() -> None:
    import Quartz

    Quartz.CGRequestScreenCaptureAccess()


def open_settings(url: str) -> None:
    subprocess.run(["open", url], check=False)
