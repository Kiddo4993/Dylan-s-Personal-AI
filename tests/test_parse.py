from fixel.parse import Header, primary_fix, runnable_command, split_header

KEY = "ModuleNotFoundError: No module named 'numpy'"
REPLY = f"MODE: error\nKEY: {KEY}\n---\n**Cause:** wrong venv.\n"


def test_split_complete():
    header, body = split_header(REPLY)
    assert header == Header("error", KEY)
    assert body == "**Cause:** wrong venv.\n"


def test_partial_header_waits():
    assert split_header("MO") is None
    assert split_header("MODE: error\nKEY: x\n") is None


def test_streamed_char_by_char_converges():
    first = None
    for i in range(1, len(REPLY) + 1):
        result = split_header(REPLY[:i])
        if result is not None and first is None:
            first = result[0]
    assert first == Header("error", KEY)


def test_missing_header_is_general():
    assert split_header("Sure! Here's how") == (Header("general", ""), "Sure! Here's how")


def test_unknown_mode_falls_back_to_general():
    header, body = split_header("MODE: poetry\nKEY: k\n---\nhi")
    assert header == Header("general", "k")
    assert body == "hi"


def test_header_without_separator_gives_up():
    assert split_header("MODE: error\nKEY: " + "x" * 500)[0] == Header()
    assert split_header("MODE: error", final=True)[0] == Header()


def test_empty_final():
    assert split_header("", final=True) == (Header(), "")


def test_primary_fix_prefers_code_block():
    assert primary_fix("**Fix:**\n```bash\npip install numpy\n```\n") == "pip install numpy"


def test_primary_fix_answer_line():
    assert primary_fix("1. x = 2\n**Answer:** x = 2 m/s\n") == "x = 2 m/s"
    assert primary_fix("Answer: 42") == "42"


def test_primary_fix_falls_back_to_body():
    assert primary_fix("  Click Settings.  ") == "Click Settings."
    assert primary_fix("   ") is None


def test_runnable_command_only_shell_blocks():
    body = "```python\nimport os\n```\n```zsh\n$ brew install jq\n$ jq --version\n```"
    assert runnable_command(body) == "brew install jq\njq --version"
    assert runnable_command("```diff\n-a\n+b\n```") is None


def test_writing_mode_is_recognized():
    header, body = split_header("MODE: writing\nKEY: The Great Gatsby thesis\n---\n**Thesis:** arguable.")
    assert header == Header("writing", "The Great Gatsby thesis")
    assert body == "**Thesis:** arguable."
