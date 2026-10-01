"""Region screenshots via macOS's built-in `screencapture`."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

MAX_EDGE = 1568  # Claude downsamples beyond this anyway; also keeps PNGs well under the 5 MB limit


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


async def _run(*args: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return await proc.wait()


async def capture_region(dest: Path) -> bytes | None:
    """Let the user drag-select a region and save it to `dest`. None if they pressed Esc."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    await _run("screencapture", "-i", "-x", str(dest))
    if not dest.exists() or dest.stat().st_size == 0:
        return None
    data = dest.read_bytes()
    if max(png_size(data)) > MAX_EDGE:
        await _run("sips", "-Z", str(MAX_EDGE), str(dest))
        data = dest.read_bytes()
    return data
