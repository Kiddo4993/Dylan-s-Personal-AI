"""The user's scratch code, one file per language in ~/.fixel/playground/."""

from __future__ import annotations

from pathlib import Path

from .langs import LANGS, RUNNABLE

LAST_FILE = ".last"  # holds the last language saved


class Scratch:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, lang: str) -> Path:
        return self.folder / LANGS[lang].filename

    def load(self, lang: str) -> str:
        path = self.path(lang)
        return path.read_text() if path.exists() else LANGS[lang].starter

    def save(self, lang: str, code: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(lang).write_text(code)
        (self.folder / LAST_FILE).write_text(lang)

    def last_lang(self, choices: tuple[str, ...] = RUNNABLE, default: str = "python") -> str:
        try:
            name = (self.folder / LAST_FILE).read_text().strip()
        except OSError:
            return default
        return name if name in choices else default
