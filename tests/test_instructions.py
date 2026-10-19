import re
from pathlib import Path

from fixel.app import FixelApp
from fixel.brain.fake import FakeProvider
from fixel.casefile import CaseFile
from fixel.config import Config
from fixel.commands import COMMANDS
from fixel.ui import UI

APP_SOURCE = (Path(__file__).parents[1] / "fixel" / "app.py").read_text()
ALIASES = {"/quit", "/web"}  # handled, but folded into /exit and /ide in the list


def handled_commands() -> set[str]:
    """Every slash command app.py's handle_command answers to."""
    found = set(re.findall(r'command == "(/\w+)"', APP_SOURCE))
    for group in re.findall(r"command in \(([^)]*)\)", APP_SOURCE):
        found |= set(re.findall(r'"(/\w+)"', group))
    return found


def listed_commands() -> set[str]:
    return {c.name for c in COMMANDS}


def action_commands() -> set[str]:
    """Commands handle_command runs through handle_action, like their Ctrl shortcuts."""
    return {c.name for c in COMMANDS if c.action}


def test_every_command_fixel_handles_is_listed():
    assert handled_commands() - ALIASES - listed_commands() == set()


def test_nothing_listed_that_fixel_does_not_handle():
    assert listed_commands() - action_commands() - handled_commands() == set()


def make_app(tmp_path, console):
    return FixelApp(
        Config(home=tmp_path, notes_dir=tmp_path / "notes"), UI(console),
        provider_factory=lambda alias, cfg: FakeProvider(), casefile=CaseFile(tmp_path / "c.db"),
    )


async def test_instruction_command_shows_every_command_and_shortcut(tmp_path, console):
    await make_app(tmp_path, console).handle_command("/instruction")
    out = console.file.getvalue()
    for command in COMMANDS:
        assert command.name in out
    assert "/ide terminal" in out and "Shortcuts" in out and "⌃P" in out and "⌥⌥" in out


async def test_unknown_command_points_to_instruction(tmp_path, console):
    await make_app(tmp_path, console).handle_command("/nope")
    assert "/instruction" in console.file.getvalue()


async def test_arguments_in_brackets_are_shown_not_eaten_as_markup(tmp_path, console):
    await make_app(tmp_path, console).handle_command("/instruction")
    out = console.file.getvalue()
    for command in COMMANDS:
        assert f"{command.name} {command.usage}".strip() in out


async def test_instruction_shows_each_commands_ctrl_key(tmp_path, console):
    await make_app(tmp_path, console).handle_command("/instruction")
    out = console.file.getvalue()
    for command in COMMANDS:
        if command.key:
            assert f"⌃{command.key.removeprefix('c-').upper()}" in out
