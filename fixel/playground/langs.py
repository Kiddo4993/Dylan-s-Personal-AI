"""The languages the playground knows: one row each. Pure data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    name: str  # canonical name, also the Markdown fence tag
    label: str  # shown to the user
    filename: str  # source file name in the temp dir and the scratch folder
    build: tuple[str, ...] = ()  # run first, in the temp dir; empty = no build step
    run: tuple[str, ...] = ()  # empty = browser-only (HTML)
    tool: str = ""  # must be on PATH
    install_hint: str = ""  # shown when `tool` is missing
    starter: str = ""  # code for an empty scratch file


LANGS: dict[str, Lang] = {
    "python": Lang(
        "python", "Python", "main.py", run=("python3", "main.py"), tool="python3",
        install_hint="Python isn't installed. Install it: brew install python",
        starter='print("Hello from Fixel!")\n\n# Reading input? Type it in the Input box (F3 in /code), then:\n# name = input()\n',
    ),
    "java": Lang(
        "java", "Java", "Main.java", run=("java", "Main.java"), tool="java",
        install_hint="Java isn't installed. Install a JDK: brew install openjdk",
        starter='public class Main {\n    public static void main(String[] args) {\n'
        '        System.out.println("Hello from Fixel!");\n    }\n}\n',
    ),
    "javascript": Lang(
        "javascript", "JavaScript", "main.js", run=("node", "main.js"), tool="node",
        install_hint="Node isn't installed. Install it: brew install node",
        starter='console.log("Hello from Fixel!");\n',
    ),
    "cpp": Lang(
        "cpp", "C++", "main.cpp", build=("g++", "-std=c++17", "-O2", "main.cpp", "-o", "main"), run=("./main",),
        tool="g++", install_hint="g++ isn't installed. Install it: xcode-select --install",
        starter='#include <iostream>\n\nint main() {\n    std::cout << "Hello from Fixel!" << std::endl;\n}\n',
    ),
    "html": Lang(
        "html", "HTML", "index.html",
        starter='<!doctype html>\n<html>\n<head>\n<style>\n  body { font-family: system-ui; padding: 2rem; }\n'
        '</style>\n</head>\n<body>\n  <h1>Hello from Fixel!</h1>\n</body>\n</html>\n',
    ),
}

ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript",
           "c++": "cpp", "cc": "cpp", "htm": "html"}

RUNNABLE: tuple[str, ...] = tuple(name for name, lang in LANGS.items() if lang.run)


def resolve(name: str) -> Lang | None:
    """A language from its name, alias, or fence tag (any case). None if the playground doesn't know it."""
    key = name.strip().lower()
    return LANGS.get(ALIASES.get(key, key))
