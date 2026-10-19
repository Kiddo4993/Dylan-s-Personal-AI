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

from .java import java_entry
from .langs import Lang, resolve

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
        filename, build, run_argv = _steps(spec, code)
        (work / filename).write_text(code)
        for argv, feed in ((build, ""), (run_argv, stdin)):
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


def _steps(spec: Lang, code: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """(source file name, build argv, run argv). Java compiles and runs the class that declares main,
    so a helper class may come first; without javac, or without a main, the JDK's single-file launcher reports it."""
    if spec.name == "java" and shutil.which("javac"):
        entry = java_entry(code)
        if entry:
            filename, main_class = entry
            return filename, ("javac", "-d", ".", filename), ("java", "-cp", ".", main_class)
    return spec.filename, spec.build, spec.run


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
    async def exited() -> int:
        # Not proc.wait(): asyncio only finishes that once every pipe closes, and a background child may hold one.
        while proc.returncode is None:
            await asyncio.sleep(0.05)
        return proc.returncode

    waiter = asyncio.ensure_future(exited())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        await asyncio.wait({reader, waiter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not waiter.done():  # output closed, or nothing yet: the program itself still has until the deadline
            await asyncio.wait({waiter}, timeout=max(deadline - loop.time(), 0))
        if not waiter.done():
            _kill(proc)
            feeder.cancel()
            await asyncio.wait({reader}, timeout=2)  # the killed program's output closes; don't wait forever if not
            reader.cancel()
            await waiter
            return None, buf.decode(errors="replace")
        if not reader.done():  # finished, but something it started still holds the output open
            await asyncio.wait({reader}, timeout=0.5)
        _kill(proc)  # stop anything the finished program left running in the background
    except asyncio.CancelledError:  # ⌃C in the editor, or Fixel quitting
        _kill(proc)
        for task in (feeder, reader, waiter):
            task.cancel()
        raise
    feeder.cancel()
    reader.cancel()
    return waiter.result(), buf.decode(errors="replace")


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # already gone, or only zombies left (macOS says EPERM)
        pass
