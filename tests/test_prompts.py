from fixel.prompts import build_system


def test_base_prompt_defines_header_contract():
    system = build_system(learn=False)
    assert "MODE:" in system and "KEY:" in system
    assert "Learn mode is ON" not in system


def test_learn_mode_appends_addendum():
    system = build_system(learn=True)
    assert system.startswith(build_system(learn=False))
    assert "Learn mode is ON" in system and "/answer" in system
