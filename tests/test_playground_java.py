import shutil

import pytest

from fixel.playground.java import java_entry
from fixel.playground.runner import run

HELPER_FIRST = """
class Helper {
    static int twice(int x) { return x * 2; }
}

public class Main {
    public static void main(String[] args) {
        System.out.println(Helper.twice(21));
    }
}
"""


def test_entry_is_the_class_that_declares_main():
    assert java_entry(HELPER_FIRST) == ("Main.java", "Main")


def test_public_class_names_the_file():
    code = "public class Hello { public static void main(String[] a) {} }"
    assert java_entry(code) == ("Hello.java", "Hello")


def test_nested_class_before_main_is_not_the_entry():
    code = "public class Main {\n  static class Node { int v; }\n  public static void main(String[] a) {}\n}"
    assert java_entry(code) == ("Main.java", "Main")


def test_main_inside_a_nested_class_uses_its_binary_name():
    code = "class Outer {\n  static class App {\n    public static void main(String[] a) {}\n  }\n}"
    assert java_entry(code) == ("Main.java", "Outer$App")


def test_braces_and_class_words_in_strings_and_comments_are_ignored():
    code = ('// class Fake { static void main(\n'
            'public class Real {\n  String s = "class Nope { }";\n  /* } */\n'
            '  public static void main(String[] a) {}\n}')
    assert java_entry(code) == ("Real.java", "Real")


def test_no_main_means_no_entry():
    assert java_entry("class A { void f() {} }") is None


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
async def test_helper_class_first_runs():
    result = await run(HELPER_FIRST, "java", timeout=30)
    assert result.exit_code == 0 and result.output == "42\n"
