from datetime import datetime

from fixel.casefile import CaseRecord
from fixel.memory import AboutMe, past_cases_context


def test_notes_roundtrip(tmp_path):
    about = AboutMe(tmp_path / "about-me.md")
    assert about.notes() == []
    about.add("I use Python 3.12 and zsh")
    about.add("  I'm in AP Calc BC  ")
    assert about.notes() == ["I use Python 3.12 and zsh", "I'm in AP Calc BC"]
    assert about.forget(1) == "I use Python 3.12 and zsh"
    assert about.notes() == ["I'm in AP Calc BC"]
    assert about.forget(5) is None


def test_hand_edits_are_kept(tmp_path):
    path = tmp_path / "about-me.md"
    path.write_text("# About me\nSome prose I wrote.\n- first fact\n- second fact\n")
    about = AboutMe(path)
    assert about.notes() == ["first fact", "second fact"]
    about.forget(1)
    assert path.read_text() == "# About me\nSome prose I wrote.\n- second fact\n"


def test_blank_fact_is_ignored(tmp_path):
    about = AboutMe(tmp_path / "about-me.md")
    about.add("   ")
    assert about.notes() == []


def record(answer="pip install numpy", worked=False):
    return CaseRecord(7, datetime(2026, 9, 12), "error", "ModuleNotFoundError: numpy", "q", answer, [], "", worked)


def test_past_cases_context_marks_proven_fixes_and_trims():
    context = past_cases_context([record(worked=True), record(answer="x" * 2000)])
    assert context.startswith("[Fixel memory")
    assert "Sep 12" in context and "ModuleNotFoundError: numpy" in context
    assert "confirmed this fix worked" in context
    assert "x" * 800 in context and "x" * 801 not in context
    assert context.rstrip().endswith("[End of Fixel memory]")


def test_no_cases_no_context():
    assert past_cases_context([]) == ""
