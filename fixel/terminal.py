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


def ide_command(lang: str | None) -> str:
    """The shell line for the IDE's own window. `exit` afterwards, so Esc can close the window too."""
    args = " ".join(shlex.quote(a) for a in ("-m", "fixel", "ide", *([lang] if lang else [])))
    return f"clear; {shlex.quote(sys.executable)} {args}; exit"


def launch_script(command: str | None = None) -> str:
    """AppleScript that runs Fixel (or `command`) in Terminal.app. If Terminal isn't running yet, it
    opens with its own startup window, so run in that window instead of adding a second one."""
    command = applescript_string(command or launch_command())
    return (
        'tell application "Terminal"\n'
        "  if it is running then\n"
        f"    do script {command}\n"
        "  else\n"
        "    activate\n"
        f"    do script {command} in window 1\n"
        "  end if\n"
        "  activate\n"
        "end tell"
    )


def open_in_terminal_app(command: str | None = None) -> bool:
    return subprocess.run(["osascript", "-e", launch_script(command)], capture_output=True).returncode == 0


def open_ide_window(lang: str | None) -> bool:
    """/ide: the terminal IDE in a new Terminal window, so Fixel's own window stays free."""
    return open_in_terminal_app(ide_command(lang))


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
