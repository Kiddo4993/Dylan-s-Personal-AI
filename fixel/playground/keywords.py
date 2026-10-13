"""Words the terminal editor offers on ⌃Space, besides the ones already in your code."""

from __future__ import annotations

import re
from typing import Callable, Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

KEYWORDS: dict[str, tuple[str, ...]] = {
    "python": (
        "False", "None", "True", "and", "break", "class", "continue", "def", "elif", "else", "except", "finally",
        "for", "from", "import", "input", "isinstance", "lambda", "len", "list", "print", "range", "return",
        "sorted", "split", "strip", "while", "with", "yield", "enumerate", "append", "dict", "int", "str",
    ),
    "java": (
        "ArrayList", "Integer", "Math", "Scanner", "String", "System", "boolean", "break", "class", "continue",
        "double", "else", "extends", "final", "for", "implements", "import", "interface", "length", "nextInt",
        "nextLine", "new", "null", "println", "private", "public", "return", "static", "this", "void", "while",
    ),
    "javascript": (
        "Array", "Math", "Object", "async", "await", "break", "class", "console", "const", "continue", "else",
        "export", "false", "function", "import", "length", "let", "log", "null", "return", "true", "undefined",
        "while",
    ),
    "cpp": (
        "auto", "bool", "break", "char", "cin", "class", "const", "continue", "cout", "double", "else", "endl",
        "false", "include", "int", "iostream", "long", "main", "namespace", "push_back", "return", "size",
        "std", "string", "struct", "true", "vector", "void", "while",
    ),
}

_WORD = re.compile(r"[A-Za-z_]\w{2,}")


class CodeCompleter(Completer):
    """Words in the buffer plus the current language's keywords that start with the word being typed."""

    def __init__(self, lang: Callable[[], str]) -> None:
        self._lang = lang  # read on every request, so switching files switches keywords

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        prefix = document.get_word_before_cursor()
        if not prefix or not (prefix[0].isalpha() or prefix[0] == "_"):
            return
        words = set(_WORD.findall(document.text)) | set(KEYWORDS.get(self._lang(), ()))
        for word in sorted(words, key=str.lower):
            if word.startswith(prefix) and word != prefix:
                yield Completion(word, start_position=-len(prefix))
