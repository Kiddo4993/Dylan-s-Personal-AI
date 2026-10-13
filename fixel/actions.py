"""One-key actions: copy the fix, run a confirmed command, save a note."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import subprocess
from datetime import datetime
from pathlib import Path


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode(), check=True)


def open_url(url: str) -> None:
    subprocess.run(["open", url], check=False)


async def run_command(cmd: str, *, timeout: float = 60.0, cwd: Path | None = None) -> tuple[int | None, str]:
    """Run an already-confirmed command in zsh. Returns (exit code, or None on timeout; combined output)."""
    proc = await asyncio.create_subprocess_exec(
        "/bin/zsh", "-c", cmd,
        cwd=str(cwd or Path.home()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # so a timeout can kill the whole process group
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = await proc.communicate()
        return None, out.decode(errors="replace") + f"\n[stopped after {timeout:g}s]"
    except asyncio.CancelledError:  # Ctrl+C: don't leave the command running in the background
        os.killpg(proc.pid, signal.SIGKILL)
        raise
    return proc.returncode, out.decode(errors="replace")


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].strip("-")
    return slug or "note"


def save_note(
    notes_dir: Path,
    *,
    question: str,
    answer: str,
    mode: str,
    shots: list[Path],
    when: datetime | None = None,
) -> Path:
    when = when or datetime.now()
    notes_dir.mkdir(parents=True, exist_ok=True)
    base = f"{when:%Y-%m-%d}-{slugify(question)}"
    path, n = notes_dir / f"{base}.md", 2
    while path.exists():
        path, n = notes_dir / f"{base}-{n}.md", n + 1
    lines = [f"# {question}", "", f"*{mode} · {when:%Y-%m-%d %H:%M}*", ""]
    existing = [shot for shot in shots if Path(shot).exists()]
    if existing:
        attachments = notes_dir / "attachments"
        attachments.mkdir(exist_ok=True)
        for i, shot in enumerate(existing, 1):
            target = attachments / f"{path.stem}-{i}.png"
            shutil.copyfile(shot, target)
            lines.append(f"![screenshot {i}](attachments/{target.name})")
        lines.append("")
    lines += [answer.strip(), ""]
    path.write_text("\n".join(lines))
    return path
