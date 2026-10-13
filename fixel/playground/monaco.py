"""The Monaco editor files the browser IDE uses: fetched once from cdnjs, checked against pinned hashes, served locally.

The IDE page holds the token that lets it run code on this Mac, so no script reaches it unchecked:
every file, including the ones Monaco loads lazily, must match its SHA-384 below before it's cached or served.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

VERSION = "0.52.2"
CDN = f"https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/{VERSION}/min/"

FILES = {  # path under min/ → base64 SHA-384
    "vs/loader.js": "pHG02SG8pId94Np3AbPmBEJ1yPqaH0IkJGLSNGXYmuGhkazT8Lr/57WYpbkGjJtu",
    "vs/editor/editor.main.js": "fj9z+NUc93I3woCCy5IRQfrQ8Amu1E27tllwgb5gz3d9Vr1ymS13xcF6two3e4KH",
    "vs/editor/editor.main.css": "06yHXpYRlHEPaR4AS0fB/W+lMN09Zh5e1XMtfkNQdHV38OlhfkOEW5M+pCj3QskC",
    "vs/base/browser/ui/codicons/codicon/codicon.ttf": "7JbEA4N9p7IShUCYjNeFsUfYuAi68DV+AhR1T8Ais0/e3NqJ3JVutl04EqC8lQ21",
    "vs/base/worker/workerMain.js": "E+dAR/J/5QJorSgHftYIrvbbqdcfQ6JdmC6+/Bk17oJDltobW75bUWcqWEA4M+AA",
    "vs/basic-languages/python/python.js": "/Wl5Hgl7Fc9gZLvdjcTzg+L7i8Y8PI2GvOnkyvPeDONgUhsPoBEYKlatO3XfMbFC",
    "vs/basic-languages/java/java.js": "FCcva6j5pfIFwQCAQZkspePiAizuaIC7xwGJZMBBkjKp0hxxRBo0FWdYAFP5sQpV",
    "vs/basic-languages/javascript/javascript.js": "YYSSe7yqFkfQUQTP2/R5dXw89AI+2wNdquBWmJnB55Qb/HagPtWL3S838P80FEpu",
    "vs/basic-languages/cpp/cpp.js": "xWERe8RAN9NjvLMTAl1DlIZ1hEpdgajh7V+hXUpJmoOQqmrTbX8ZJ5EE+KcywBt+",
    "vs/basic-languages/html/html.js": "jJFhCqILy9vx0ekxrQ9QKp5x7/xuHlHbojw0O1fXHm/itds9s/VpolToVnTrao9C",
    "vs/language/html/htmlMode.js": "Z9mTGgULWBO8nB9wxfnGZdn4P9qF71glrS7iDOU6xtIDyMAa5+AW3JJHjA03wDPQ",
    "vs/language/html/htmlWorker.js": "EqeN2jIwf6xy3w4wgD0AbbPnLw2+e4iuoyEqJtOrglJkAaxij0hUzG/Dh5R4iQ45",
    "vs/language/typescript/tsMode.js": "LJDXVt7WHdcjvmrQwGPaDPpsAmD0FfVF59daseEl2Ifa/jHppeHXJeJzBPLScQ/e",
    "vs/language/typescript/tsWorker.js": "zxA6if3z1xYplirytIKRk7JyAbAW634/ADgNtSvYwCdedcuLuz8EApt3TC4PsUGB",
}

CONTENT_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".ttf": "font/ttf"}


class MonacoError(Exception):
    """A Monaco file couldn't be fetched, or it didn't match its pinned hash."""


def digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha384(data).digest()).decode()


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


class MonacoFiles:
    def __init__(
        self, cache: Path, *, fetch: Callable[[str], bytes] = _download, files: dict[str, str] = FILES
    ) -> None:
        self.cache = cache
        self._fetch = fetch
        self._files = files

    def get(self, path: str) -> bytes | None:
        """The checked bytes of a Monaco file, or None if Fixel doesn't serve that path.

        Raises MonacoError when the file can't be fetched or doesn't match its hash.
        """
        expected = self._files.get(path)
        if expected is None:
            return None
        target = self.cache / path
        try:
            data = target.read_bytes()
        except OSError:
            data = None
        if data is not None and digest(data) == expected:
            return data
        try:
            data = self._fetch(CDN + path)
        except OSError as e:  # urllib's URLError is an OSError
            raise MonacoError(f"Couldn't download the editor ({e}).") from e
        if digest(data) != expected:
            raise MonacoError(f"{path} failed its integrity check, so Fixel won't use it.")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, target)  # never leave a half-written file that a later run would trust
        return data
