from fixel import terminal


def test_applescript_string_escapes_quotes_and_backslashes():
    assert terminal.applescript_string('say "hi" \\ there') == '"say \\"hi\\" \\\\ there"'


def test_launch_command_quotes_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(terminal.sys, "executable", "/Users/d/Personal Projects/x/.venv/bin/python")
    command = terminal.launch_command()
    assert "FIXEL_INSIDE=1" in command
    assert "'/Users/d/Personal Projects/x/.venv/bin/python' -m fixel" in command
