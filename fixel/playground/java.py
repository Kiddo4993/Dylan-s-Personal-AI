"""Find where a Java file starts, so classes can be written in any order.

The JDK's single-file launcher (`java Main.java`) runs the *first* class, which fails when a student
puts a helper class above Main. Compiling with javac and running the class that declares main doesn't care.
"""

from __future__ import annotations

import re

_NOISE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_TOKEN = re.compile(r"\b(?P<public>public\s+(?:(?:final|abstract|static)\s+)*)?class\s+(?P<name>\w+)|(?P<brace>[{}])"
                    r"|(?P<main>\bstatic\s+void\s+main\s*\()")
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)


def java_entry(code: str) -> tuple[str, str] | None:
    """(file name javac needs, class to run), or None when no class declares main."""
    text = _NOISE.sub(lambda m: " " * len(m.group()), code)  # keep positions, drop strings and comments
    stack: list[str | None] = []  # one entry per open brace: the class it opens, or None
    pending: str | None = None  # a class name waiting for its opening brace
    public_file = None
    entry = None  # the class that declares main, once found; keep going, a public class may come later
    for token in _TOKEN.finditer(text):
        if token["name"]:
            pending = token["name"]
            if token["public"] and not any(stack):  # a public top-level class must name the file
                public_file = token["name"]
        elif token["brace"] == "{":
            stack.append(pending)
            pending = None
        elif token["brace"] == "}":
            if stack:
                stack.pop()
        elif token["main"] and entry is None:
            classes = [name for name in stack if name]
            if classes:
                entry = "$".join(classes)
    if entry is None:
        return None
    package = _PACKAGE.search(text)  # javac -d puts packaged classes in folders; java wants the full name
    return f"{public_file or 'Main'}.java", f"{package[1]}.{entry}" if package else entry
