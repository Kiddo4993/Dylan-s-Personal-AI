from prompt_toolkit.document import Document

from fixel.commands import BY_NAME, COMMANDS, SlashCompleter, shortcut_label


def complete(text):
    return [c.text for c in SlashCompleter().get_completions(Document(text), None)]


def test_every_shortcut_has_a_slash_command():
    actions = {"deeper", "worked", "copy", "run", "save", "play", "learn", "follow", "open", "new"}
    assert actions <= {c.action for c in COMMANDS if c.action}
    keys = [c.key for c in COMMANDS if c.key]
    assert len(keys) == len(set(keys)) == len(actions)


def test_names_are_unique_slash_words():
    names = [c.name for c in COMMANDS]
    assert len(names) == len(set(names)) and all(n.startswith("/") and " " not in n for n in names)
    assert BY_NAME["/deeper"].action == "deeper"


def test_typing_slash_lists_every_command():
    assert complete("/") == [c.name for c in COMMANDS]


def test_menu_narrows_as_you_type():
    assert complete("/de") == ["/deeper"]
    assert complete("/fo") == ["/follow", "/forget"]


def test_menu_stays_out_of_the_way_otherwise():
    assert complete("why does this break") == []
    assert complete("/learn ") == []  # already typing the argument
    assert complete("") == []


def test_menu_rows_explain_each_command():
    completions = list(SlashCompleter().get_completions(Document("/rem"), None))
    assert completions[0].display_meta_text == BY_NAME["/remember"].summary
    assert "<fact>" in completions[0].display_text


def test_shortcut_label_reads_as_ctrl():
    assert shortcut_label("c-t") == "Ctrl+T"
