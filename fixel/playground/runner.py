"""Run playground code: write it to a temp folder, build if needed, run with a timeout."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .langs import resolve

OUTPUT_CAP = 64_000  # characters kept; reading continues so the program never blocks on a full pipe


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None  # None: stopped at the timeout
    output: str  # stdout and stderr together
    seconds: float


class RunnerError(Exception):
    """The code can't run at all: a browser-only or unknown language, or a missing tool."""


async def run(code: str, lang: str, *, stdin: str = "", timeout: float = 10.0) -> RunResult:
    spec = resolve(lang)
    if spec is None or not spec.run:
        raise RunnerError(f"{lang or 'This code'} can't run here." + (" Use /web for HTML." if spec else ""))
    if shutil.which(spec.tool) is None:
        raise RunnerError(spec.install_hint)
    started = time.monotonic()
    deadline = started + timeout
    output, exit_code = "", 0
    with tempfile.TemporaryDirectory(prefix="fixel-play-") as tmp:
        work = Path(tmp)
        (work / spec.filename).write_text(code)
        for argv, feed in ((spec.build, ""), (spec.run, stdin)):
            if not argv:
                continue
            exit_code, out = await _exec(argv, work, feed, max(deadline - time.monotonic(), 0.1))
            output += out
            if exit_code != 0:
                break
    output = _cap(output)
    if exit_code is None:
        output += f"\n[stopped after {timeout:g}s]"
    return RunResult(exit_code, output, time.monotonic() - started)


def _cap(text: str) -> str:
    return text if len(text) <= OUTPUT_CAP else text[:OUTPUT_CAP] + "\n[output truncated]"


async def _exec(argv: tuple[str, ...], cwd: Path, stdin: str, timeout: float) -> tuple[int | None, str]:
    """Run one step in its own process group. Returns (exit code or None on timeout, output)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # so a timeout kills the program's children too
    )
    buf = bytearray()

    async def pump() -> int:
        try:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
            proc.stdin.close()  # end-of-file, so input() never waits forever
        except (BrokenPipeError, ConnectionResetError):
            pass
        while chunk := await proc.stdout.read(65536):
            if len(buf) <= OUTPUT_CAP:
                buf.extend(chunk)
        return await proc.wait()

    try:
        code = await asyncio.wait_for(pump(), timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        return None, buf.decode(errors="replace")
    except asyncio.CancelledError:  # ⌃C in the editor, or Fixel quitting
        _kill(proc)
        raise
    return code, buf.decode(errors="replace")


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
