from fixel.playground.langs import LANGS
from fixel.playground.scratch import Scratch


def test_empty_scratch_gives_starter_code(tmp_path):
    scratch = Scratch(tmp_path / "pg")
    assert scratch.load("java") == LANGS["java"].starter
    assert scratch.last_lang() == "python"


def test_save_round_trip_and_last_language(tmp_path):
    scratch = Scratch(tmp_path / "pg")
    scratch.save("cpp", "int main(){}")
    assert scratch.load("cpp") == "int main(){}"
    assert scratch.path("cpp").name == "main.cpp"
    assert scratch.last_lang() == "cpp"


def test_last_language_respects_choices(tmp_path):
    scratch = Scratch(tmp_path)
    scratch.save("html", "<p>hi</p>")
    assert scratch.last_lang() == "python"  # the terminal editor can't open HTML
    assert scratch.last_lang(choices=tuple(LANGS)) == "html"


def test_garbage_last_language_falls_back(tmp_path):
    (tmp_path / ".last").write_text("cobol")
    assert Scratch(tmp_path).last_lang() == "python"
