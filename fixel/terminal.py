"""Terminal.app glue: open Fixel in its own window, and bring that window forward."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys

WINDOW_TITLE = "Fixel"


def applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def launch_command() -> str:
    return f"clear; FIXEL_INSIDE=1 exec {shlex.quote(sys.executable)} -m fixel"


def open_in_terminal_app() -> bool:
    script = f'tell application "Terminal"\n  activate\n  do script {applescript_string(launch_command())}\nend tell'
    return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0


def set_title(title: str = WINDOW_TITLE) -> None:
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def front_window_id() -> int | None:
    """Terminal.app's id for the window we're running in (it's frontmost at startup)."""
    if os.environ.get("TERM_PROGRAM") != "Apple_Terminal":
        return None
    result = subprocess.run(
        ["osascript", "-e", 'tell application "Terminal" to id of front window'], capture_output=True, text=True
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


async def raise_window(window_id: int | None) -> None:
    if window_id is None:
        return
    script = f'tell application "Terminal"\n  set index of window id {window_id} to 1\n  activate\nend tell'
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()
