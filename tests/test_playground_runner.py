import os
import shutil
import time

import pytest

from fixel.playground import runner
from fixel.playground.runner import OUTPUT_CAP, RunnerError, run

needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="java not installed")
needs_gpp = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


async def test_python_hello():
    result = await run('print("hi")', "python")
    assert result.exit_code == 0 and result.output == "hi\n" and result.seconds >= 0


async def test_errors_keep_exit_code_and_stderr():
    result = await run("raise SystemExit('nope')", "py")
    assert result.exit_code == 1 and "nope" in result.output


async def test_stdin_is_passed_through():
    result = await run("print(input()[::-1])", "python", stdin="abc\n")
    assert result.output == "cba\n"


async def test_input_without_stdin_gets_eof_quickly():
    started = time.monotonic()
    result = await run("input()", "python", timeout=5)
    assert result.exit_code == 1 and "EOFError" in result.output
    assert time.monotonic() - started < 3


async def test_timeout_kills_the_program_and_its_children(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess, time\n"
        f"p = subprocess.Popen(['sleep', '30']); open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(30)\n"
    )
    result = await run(code, "python", timeout=1.5)
    assert result.exit_code is None
    assert result.output.startswith("started") and result.output.endswith("[stopped after 1.5s]")
    child = int(pid_file.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


async def test_endless_output_is_capped():
    result = await run("while True: print('x' * 100)", "python", timeout=1.5)
    assert len(result.output) < OUTPUT_CAP + 200
    assert "[output truncated]" in result.output and result.exit_code is None


async def test_html_and_unknown_languages_cannot_run():
    with pytest.raises(RunnerError):
        await run("<p>hi</p>", "html")
    with pytest.raises(RunnerError):
        await run("echo hi", "bash")


async def test_missing_tool_reports_install_hint(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda tool: None)
    with pytest.raises(RunnerError, match="brew install openjdk"):
        await run("class A {}", "java")


@needs_java
async def test_java_class_not_named_main_runs():
    code = 'public class Hello { public static void main(String[] a) { System.out.println("hey"); } }'
    result = await run(code, "java", timeout=30)
    assert result.exit_code == 0 and result.output == "hey\n"


@needs_java
async def test_java_compile_error_is_output():
    result = await run("public class Main { int x = ; }", "java", timeout=30)
    assert result.exit_code != 0 and "error" in result.output


@needs_gpp
async def test_cpp_builds_then_runs_with_stdin():
    code = "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<'\\n';}"
    result = await run(code, "cpp", stdin="2 3", timeout=30)
    assert result.exit_code == 0 and result.output == "5\n"


@needs_gpp
async def test_cpp_build_failure_skips_run():
    result = await run("int main( {", "cpp", timeout=30)
    assert result.exit_code != 0 and "error" in result.output


@needs_node
async def test_node_runs():
    result = await run("console.log(1 + 1)", "js")
    assert result.output == "2\n"
