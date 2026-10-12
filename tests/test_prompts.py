from fixel.prompts import build_system


def test_base_prompt_defines_header_contract():
    system = build_system(learn=False)
    assert "MODE:" in system and "KEY:" in system
    assert "Learn mode is ON" not in system


def test_learn_mode_appends_addendum():
    system = build_system(learn=True)
    assert system.startswith(build_system(learn=False))
    assert "Learn mode is ON" in system and "/answer" in system


def test_about_me_notes_go_into_the_instructions():
    system = build_system(learn=False, notes=["I use zsh", "AP Calc BC"])
    assert "## About this user" in system
    assert "- I use zsh\n- AP Calc BC" in system
    assert "## About this user" not in build_system(learn=False)


def test_instructions_explain_the_memory_block():
    assert "[Fixel memory" in build_system(learn=False)


def test_instructions_forbid_inventing_problems():
    system = build_system(learn=False)
    assert "Never invent an error" in system
    assert "ask what they need" in system


def test_web_mode_is_offered_with_its_format():
    system = build_system(learn=False)
    assert "MODE: <error|math|doc|ui|web|general>" in system
    assert "- web:" in system and "**Libraries**" in system
    assert "exactly ONE ```html block" in system
    assert "View Source" in system
