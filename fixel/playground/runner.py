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

    async def feed() -> None:
        # Its own task: a program that prints a lot before reading must not deadlock against our write.
        try:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()  # end-of-file, so input() never waits forever

    async def read() -> None:
        while chunk := await proc.stdout.read(65536):
            if len(buf) <= OUTPUT_CAP:
                buf.extend(chunk)

    feeder = asyncio.ensure_future(feed())
    reader = asyncio.ensure_future(read())
    try:
        done, _ = await asyncio.wait({reader}, timeout=timeout)
        if not done:
            _kill(proc)
            feeder.cancel()
            await asyncio.wait({reader}, timeout=2)  # the killed program's output closes; don't wait forever if not
            reader.cancel()
            await proc.wait()
            return None, buf.decode(errors="replace")
        code = await proc.wait()
    except asyncio.CancelledError:  # ⌃C in the editor, or Fixel quitting
        _kill(proc)
        feeder.cancel()
        reader.cancel()
        raise
    feeder.cancel()
    return code, buf.decode(errors="replace")


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
