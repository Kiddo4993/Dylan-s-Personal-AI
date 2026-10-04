"""Every slash command, in one list: it drives the `/` menu, /help, and the hidden Ctrl shortcuts."""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.completion import Completer, Completion


@dataclass(frozen=True)
class Command:
    name: str  # what you type, e.g. "/deeper"
    summary: str  # one line for the menu and /help
    usage: str = ""  # argument hint, e.g. "<fact>"
    action: str | None = None  # the one-key action it runs (shared with its shortcut)
    key: str | None = None  # hidden Ctrl shortcut, in prompt_toolkit notation ("c-t")


COMMANDS = (
    Command("/deeper", "re-answer the last question with deep thinking", action="deeper", key="c-t"),
    Command("/worked", "that fix worked: Fixel reaches for it first next time", action="worked", key="c-g"),
    Command("/copy", "copy the fix, answer, or draft", action="copy", key="c-y"),
    Command("/run", "run the suggested shell command (asks first)", action="run", key="c-r"),
    Command("/save", "save this case as a note in ~/Fixel Notes", action="save", key="c-s"),
    Command("/new", "start a new case", action="new", key="c-n"),
    Command("/follow", "add the tray to this case instead of starting a new one", action="follow", key="c-f"),
    Command("/learn", "learn mode: hints instead of answers", usage="[on|off]", action="learn", key="c-l"),
    Command("/answer", "in learn mode, show the full solution"),
    Command("/remember", "save a fact about you", usage="<fact>"),
    Command("/memory", "list what Fixel knows about you"),
    Command("/forget", "remove a fact", usage="<number>"),
    Command("/cases", "search your past cases", usage="<words>"),
    Command("/open", "show the past case Fixel used, or one from /cases", usage="[number]", action="open", key="c-o"),
    Command("/model", "switch AI model", usage="sonnet|opus|gemini"),
    Command("/help", "show every command"),
    Command("/exit", "close Fixel"),
)
BY_NAME = {command.name: command for command in COMMANDS}


def shortcut_label(key: str) -> str:
    """prompt_toolkit's "c-t" as people say it: "Ctrl+T"."""
    return f"Ctrl+{key.removeprefix('c-').upper()}"


class SlashCompleter(Completer):
    """The menu that pops up as soon as you type `/`, narrowing as you keep typing."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for command in COMMANDS:
            if command.name.startswith(text):
                shown = f"{command.name} {command.usage}".strip()
                yield Completion(command.name, start_position=-len(text), display=shown, display_meta=command.summary)
