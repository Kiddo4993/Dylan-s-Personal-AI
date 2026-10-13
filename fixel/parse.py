"""Parse Fixel's hidden reply header and pull actionable pieces out of answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

MODES = ("error", "math", "doc", "writing", "ui", "web", "general")
HEADER_MAX = 400  # give up waiting for `---` after this many characters

_SEPARATOR = re.compile(r"^---[ \t]*$\n?", re.M)
_FENCE = re.compile(r"```([\w+-]*)[^\n]*\n(.*?)```", re.S)
_ANSWER_LINE = re.compile(r"^[ \t]*\**Answer:\**[ \t]*(.+?)[ \t]*$", re.M)
_SHELL_LANGS = {"bash", "sh", "zsh", "shell", "console"}


@dataclass(frozen=True)
class Header:
    mode: str = "general"
    key: str = ""


def split_header(text: str, final: bool = False) -> tuple[Header, str] | None:
    """Split a (possibly still-streaming) reply into (header, body).

    Returns None while more text is needed to decide. A reply that doesn't
    open with the header is treated as `general`, with the whole text as body.
    """
    stripped = text.lstrip()
    if not stripped.startswith("MODE:"):
        if "MODE:".startswith(stripped) and not final:
            return None
        return Header(), text
    separator = _SEPARATOR.search(stripped)
    if separator is None:
        if final or len(stripped) > HEADER_MAX:
            return Header(), text
        return None
    head, body = stripped[: separator.start()], stripped[separator.end() :]
    mode_match = re.search(r"^MODE:[ \t]*(\w+)", head, re.M)
    key_match = re.search(r"^KEY:[ \t]*(.*)$", head, re.M)
    mode = mode_match.group(1).lower() if mode_match else "general"
    key = key_match.group(1).strip() if key_match else ""
    return Header(mode if mode in MODES else "general", key), body.lstrip("\n")


def primary_fix(body: str) -> str | None:
    """What /copy copies: the first code block, else the `Answer:` line, else the whole body."""
    fence = _FENCE.search(body)
    if fence:
        return fence.group(2).rstrip("\n")
    answer = _ANSWER_LINE.search(body)
    if answer:
        return answer.group(1)
    return body.strip() or None


def runnable_command(body: str) -> str | None:
    """What /run may run: the first bash/sh/zsh block, with any `$ ` prompts removed."""
    for fence in _FENCE.finditer(body):
        if fence.group(1).lower() in _SHELL_LANGS:
            lines = [re.sub(r"^\$ ", "", line) for line in fence.group(2).strip("\n").splitlines()]
            command = "\n".join(lines).strip()
            if command:
                return command
    return None


def first_code_block(body: str) -> tuple[str, str] | None:
    """What ⌃P opens: the first code block as (language tag, code). Untagged HTML counts as html."""
    fence = _FENCE.search(body)
    if fence is None:
        return None
    lang, code = fence.group(1).lower(), fence.group(2).rstrip("\n")
    if not lang and code.lstrip().lower().startswith(("<!doctype", "<html")):
        lang = "html"
    return lang, code
