"""`fixel ide`: the terminal IDE in its own window. ⌃A sends the code to the Fixel window that opened it."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .attachment import CodeAttachment
from .editor import Editor
from .langs import LANGS, resolve
from .runner import run as run_code
from .scratch import Scratch

LINK = "ide-link.json"
NOT_OPEN = "Fixel isn't open (or was restarted), so nothing was sent. Open Fixel and type /ide again."


def write_link(home: Path, origin: str, token: str) -> Path:
    """Tell IDE windows where Fixel listens. A private file, so the token stays out of shell history and screenshots."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / LINK
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"ask": f"{origin}/api/ask", "token": token}, f)
    return path


def read_link(home: Path) -> dict | None:
    try:
        link = json.loads((home / LINK).read_text())
    except (OSError, ValueError):
        return None
    return link if isinstance(link, dict) and {"ask", "token"} <= link.keys() else None


def remove_link(home: Path) -> None:
    (home / LINK).unlink(missing_ok=True)


def send_to_fixel(link: dict | None, att: CodeAttachment) -> str | None:
    """POST the code to Fixel's playground server, like the browser IDE's Ask button. Returns a problem, or None."""
    if link is None:
        return NOT_OPEN
    body = {"lang": att.lang, "code": att.code, "output": att.output, "exit_code": att.exit_code, "ran": att.ran}
    request = urllib.request.Request(
        link["ask"], data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Fixel-Token": link["token"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return None if response.status == 200 else NOT_OPEN
    except urllib.error.HTTPError as e:
        return "That code is over the 1 MB limit." if e.code == 413 else NOT_OPEN
    except (urllib.error.URLError, TimeoutError, OSError):
        return NOT_OPEN


async def run_window(
    cfg,
    lang: str | None,
    *,
    editor_factory: Callable[..., Editor] = Editor,
    send: Callable[[dict | None, CodeAttachment], str | None] = send_to_fixel,
) -> int:
    """Edit until Esc. Each ⌃A sends the code to Fixel, then the editor reopens right where you were."""
    scratch = Scratch(cfg.playground_dir)
    spec = resolve(lang) if lang else None
    name = spec.name if spec is not None and spec.run else scratch.last_lang()
    code, note = scratch.load(name), f"{LANGS[name].label} · ⌃A sends your code to Fixel · Esc closes this window."

    def run(source: str, language: str, stdin: str):
        return run_code(source, language, stdin=stdin, timeout=cfg.playground_timeout)

    while True:
        result = await editor_factory(scratch, name, code, run, note=note).edit()
        if result.attachment is None:
            return 0
        problem = send(read_link(cfg.home), result.attachment)
        name, code = result.lang, result.code
        note = problem or "Sent to Fixel. Ask about it in the Fixel window. Keep editing here, or Esc to close."
