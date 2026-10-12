from fixel.parse import Header, first_code_block, primary_fix, runnable_command, split_header

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


def test_web_mode_header_is_kept():
    header, _ = split_header("MODE: web\nKEY: Stripe pricing page\n---\nbody")
    assert header == Header("web", "Stripe pricing page")


def test_first_code_block_language_and_code():
    body = "**Code:**\n```HTML\n<!doctype html>\n<p>hi</p>\n```\n```python\nx\n```"
    assert first_code_block(body) == ("html", "<!doctype html>\n<p>hi</p>")


def test_untagged_html_block_is_html():
    assert first_code_block("```\n<html><body></body></html>\n```") == ("html", "<html><body></body></html>")


def test_no_block_and_untagged_other_block():
    assert first_code_block("Answer: 42") is None
    assert first_code_block("```\nx = 1\n```") == ("", "x = 1")
