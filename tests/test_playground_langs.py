import pytest

from fixel.playground.langs import LANGS, RUNNABLE, resolve


def test_four_runnable_languages_plus_html():
    assert RUNNABLE == ("python", "java", "javascript", "cpp")
    assert "html" in LANGS and not LANGS["html"].run


@pytest.mark.parametrize("name", RUNNABLE)
def test_runnable_languages_are_complete(name):
    lang = LANGS[name]
    assert lang.run and lang.tool and lang.filename and lang.starter
    assert "Install" in lang.install_hint


def test_java_uses_single_file_launch_and_cpp_compiles_first():
    assert LANGS["java"].filename == "Main.java" and LANGS["java"].run == ("java", "Main.java")
    assert LANGS["cpp"].build[0] == "g++" and LANGS["cpp"].run == ("./main",)


@pytest.mark.parametrize(
    "alias, name",
    [("py", "python"), ("Python3", "python"), ("js", "javascript"), ("node", "javascript"),
     ("c++", "cpp"), ("CPP", "cpp"), ("htm", "html"), (" java ", "java")],
)
def test_aliases_resolve(alias, name):
    assert resolve(alias).name == name


@pytest.mark.parametrize("name", ["", "bash", "diff", "rust"])
def test_unknown_names_resolve_to_none(name):
    assert resolve(name) is None
