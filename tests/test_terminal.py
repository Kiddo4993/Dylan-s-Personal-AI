from fixel import terminal


def test_applescript_string_escapes_quotes_and_backslashes():
    assert terminal.applescript_string('say "hi" \\ there') == '"say \\"hi\\" \\\\ there"'


def test_launch_command_quotes_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(terminal.sys, "executable", "/Users/d/Personal Projects/x/.venv/bin/python")
    command = terminal.launch_command()
    assert "FIXEL_INSIDE=1" in command
    assert "'/Users/d/Personal Projects/x/.venv/bin/python' -m fixel" in command


def test_launch_script_reuses_startup_window_when_terminal_is_closed():
    script = terminal.launch_script()
    assert "if it is running then" in script
    assert "in window 1" in script
