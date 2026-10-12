# Fixel Playground and Web Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a code playground to Fixel (terminal editor `/code`, browser playground `/web`, one shared runner for Python/Java/Node/C++) and a `web` screenshot mode that explains a page's design and libraries and recreates it as one HTML file, with ⌃P opening an answer's code in the playground.

**Architecture:** A new `fixel/playground/` package holds pure data (`langs`, `attachment`), the runner, scratch storage, and two front-ends (`editor`, `server` + `web/index.html`). Both front-ends end by handing a `CodeAttachment` to the session, which sends it through the existing ask path, so memory, learn mode, ⌃T and ⌃G need no changes. Web mode is a prompt change plus a new MODE value.

**Tech Stack:** Python 3.12, prompt_toolkit 3.0.53 (full-screen `Application`), Pygments 2.21, stdlib `http.server`/`asyncio`, CodeMirror 5.65.16 from cdnjs in the browser page, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-10-12-fixel-playground-design.md`

**Run tests with:** `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q` from the repo root (this worktree has no venv; the main checkout's venv imports `fixel` from the working directory). Baseline: 177 passed.

## Global Constraints

- No new Python dependencies (prompt_toolkit, Pygments, stdlib only).
- Runtimes come from `PATH`: `python3`, `java`, `node`, `g++`. Missing runtime → the language's install hint, nothing else breaks.
- Web server binds `127.0.0.1` only; stopped when Fixel exits.
- Every `/api/*` request needs header `X-Fixel-Token`; `Origin`, when present, must equal `http://127.0.0.1:<port>`; body limit 1 MB (1_000_000 bytes).
- Preview iframe: `sandbox="allow-scripts"` and never `allow-same-origin`.
- Run timeout default 10 s (`playground_timeout`); output cap 64 KB (64_000 chars) with `[output truncated]`; attachment output tail 4 KB (4_000 chars).
- Nothing Fixel writes is run automatically: ⌃P only opens code.
- Default questions: `Why doesn't this work?` after a failed run, otherwise `Review this code.`
- Web-mode code: one ```html block, inline `<style>`, Google Fonts `<link>` allowed, no other external files, no hotlinked images.

## Review Focus

1. **A program that prints forever** (`while True: print("x")`) must not fill memory or flood the editor: output is capped while reading, the run stops at the timeout. → Task 2 `test_endless_output_is_capped`.
2. **A program that calls `input()` with no stdin given** must get end-of-file at once, not hang for the full timeout. → Task 2 `test_input_without_stdin_gets_eof_quickly`.
3. **Code edited after its last run, then "Ask Fixel"** must not send the old run's output as if it belonged to the new code. → Task 6 `test_attach_after_edit_drops_stale_output`; the page does the same check in Task 7.
4. **Malformed requests to the local server** (bad or negative `Content-Length`, non-JSON, JSON that isn't an object, non-string fields) must get a 4xx, never crash the server thread or block it. → Task 7 `test_malformed_requests_get_400`.
5. **A Java file whose public class isn't `Main`** (students write `public class Hello`) must still run. JDK single-file launch runs the first top-level class whatever the file name. → Task 2 `test_java_class_not_named_main_runs`.

---

### Task 1: Language table and code attachment

**Files:**
- Create: `fixel/playground/__init__.py`, `fixel/playground/langs.py`, `fixel/playground/attachment.py`
- Test: `tests/test_playground_langs.py`, `tests/test_playground_attachment.py`

**Interfaces:**
- Produces: `Lang` (frozen dataclass: `name, label, filename, build: tuple[str,...], run: tuple[str,...], tool, install_hint, starter`), `LANGS: dict[str, Lang]`, `RUNNABLE: tuple[str, ...]`, `resolve(name: str) -> Lang | None`; `CodeAttachment(lang, code, output="", exit_code=None, ran=False)` with `.failed`, `.default_question()`, `.to_prompt_text()`; `OUTPUT_TAIL = 4_000`.

- [ ] **Step 1: Write the failing tests**

`tests/test_playground_langs.py`:

```python
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
```

`tests/test_playground_attachment.py`:

```python
from fixel.playground.attachment import OUTPUT_TAIL, CodeAttachment


def test_unrun_code_is_reviewed():
    att = CodeAttachment("python", "print(1)\n")
    assert not att.failed and att.default_question() == "Review this code."
    assert att.to_prompt_text() == "[Code from Fixel playground · python]\n```python\nprint(1)\n```"


def test_failed_run_includes_output_and_asks_why():
    att = CodeAttachment("java", "class A {}", output="error: boom\n", exit_code=1, ran=True)
    assert att.failed and att.default_question() == "Why doesn't this work?"
    assert att.to_prompt_text().endswith("[Run output · exit 1]\nerror: boom")


def test_timeout_counts_as_failed():
    att = CodeAttachment("python", "while True: pass", output="[stopped after 10s]", exit_code=None, ran=True)
    assert att.failed and "[Run output · timed out]" in att.to_prompt_text()


def test_empty_output_and_long_output_tail():
    assert "(no output)" in CodeAttachment("python", "", ran=True, exit_code=0).to_prompt_text()
    long = CodeAttachment("python", "", output="a" * 10 + "b" * OUTPUT_TAIL, ran=True, exit_code=0)
    text = long.to_prompt_text()
    assert text.endswith("…" + "b" * OUTPUT_TAIL) and "a" not in text.split("]")[-1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_langs.py tests/test_playground_attachment.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'fixel.playground'`

- [ ] **Step 3: Write the implementation**

`fixel/playground/__init__.py`:

```python
"""Fixel's code playground: a terminal editor, a browser playground, and the runner they share."""
```

`fixel/playground/langs.py`:

```python
"""The languages the playground knows: one row each. Pure data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    name: str  # canonical name, also the Markdown fence tag
    label: str  # shown to the user
    filename: str  # source file name in the temp dir and the scratch folder
    build: tuple[str, ...] = ()  # run first, in the temp dir; empty = no build step
    run: tuple[str, ...] = ()  # empty = browser-only (HTML)
    tool: str = ""  # must be on PATH
    install_hint: str = ""  # shown when `tool` is missing
    starter: str = ""  # code for an empty scratch file


LANGS: dict[str, Lang] = {
    "python": Lang(
        "python", "Python", "main.py", run=("python3", "main.py"), tool="python3",
        install_hint="Python isn't installed. Install it: brew install python",
        starter='name = input("Your name? ")\nprint(f"Hello, {name}!")\n',
    ),
    "java": Lang(
        "java", "Java", "Main.java", run=("java", "Main.java"), tool="java",
        install_hint="Java isn't installed. Install a JDK: brew install openjdk",
        starter='public class Main {\n    public static void main(String[] args) {\n'
        '        System.out.println("Hello from Fixel!");\n    }\n}\n',
    ),
    "javascript": Lang(
        "javascript", "JavaScript", "main.js", run=("node", "main.js"), tool="node",
        install_hint="Node isn't installed. Install it: brew install node",
        starter='console.log("Hello from Fixel!");\n',
    ),
    "cpp": Lang(
        "cpp", "C++", "main.cpp", build=("g++", "-std=c++17", "-O2", "main.cpp", "-o", "main"), run=("./main",),
        tool="g++", install_hint="g++ isn't installed. Install it: xcode-select --install",
        starter='#include <iostream>\n\nint main() {\n    std::cout << "Hello from Fixel!" << std::endl;\n}\n',
    ),
    "html": Lang(
        "html", "HTML", "index.html",
        starter='<!doctype html>\n<html>\n<head>\n<style>\n  body { font-family: system-ui; padding: 2rem; }\n'
        '</style>\n</head>\n<body>\n  <h1>Hello from Fixel!</h1>\n</body>\n</html>\n',
    ),
}

ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript",
           "c++": "cpp", "cc": "cpp", "htm": "html"}

RUNNABLE: tuple[str, ...] = tuple(name for name, lang in LANGS.items() if lang.run)


def resolve(name: str) -> Lang | None:
    """A language from its name, alias, or fence tag (any case). None if the playground doesn't know it."""
    key = name.strip().lower()
    return LANGS.get(ALIASES.get(key, key))
```

`fixel/playground/attachment.py`:

```python
"""The one shape both playground front-ends hand to Fixel: code plus its last run."""

from __future__ import annotations

from dataclasses import dataclass

OUTPUT_TAIL = 4_000  # characters of run output sent to the model


@dataclass(frozen=True)
class CodeAttachment:
    lang: str  # canonical language name (a key of LANGS)
    code: str
    output: str = ""
    exit_code: int | None = None  # None after a timeout
    ran: bool = False  # False: never run, or edited since the last run

    @property
    def failed(self) -> bool:
        return self.ran and self.exit_code != 0

    def default_question(self) -> str:
        return "Why doesn't this work?" if self.failed else "Review this code."

    def to_prompt_text(self) -> str:
        parts = [f"[Code from Fixel playground · {self.lang}]", f"```{self.lang}", self.code.rstrip("\n"), "```"]
        if self.ran:
            status = "timed out" if self.exit_code is None else f"exit {self.exit_code}"
            output = self.output.rstrip() or "(no output)"
            if len(output) > OUTPUT_TAIL:
                output = "…" + output[-OUTPUT_TAIL:]
            parts += [f"[Run output · {status}]", output]
        return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_langs.py tests/test_playground_attachment.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fixel/playground tests/test_playground_langs.py tests/test_playground_attachment.py
git commit -m "feat(playground): language table and code attachment"
```

---

### Task 2: Runner

**Files:**
- Create: `fixel/playground/runner.py`
- Test: `tests/test_playground_runner.py`

**Interfaces:**
- Consumes: `resolve`, `Lang` from Task 1.
- Produces: `RunResult(exit_code: int | None, output: str, seconds: float)`, `RunnerError(Exception)`, `OUTPUT_CAP = 64_000`, `async run(code: str, lang: str, *, stdin: str = "", timeout: float = 10.0) -> RunResult`. Raises `RunnerError` for HTML/unknown languages and missing tools (message = install hint).

- [ ] **Step 1: Write the failing tests**

`tests/test_playground_runner.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_runner.py`
Expected: FAIL with `ImportError: cannot import name 'runner'`

- [ ] **Step 3: Write the implementation**

`fixel/playground/runner.py`:

```python
"""Run playground code: write it to a temp folder, build if needed, run with a timeout."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .langs import resolve

OUTPUT_CAP = 64_000  # characters kept; reading continues so the program never blocks on a full pipe


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None  # None: stopped at the timeout
    output: str  # stdout and stderr together
    seconds: float


class RunnerError(Exception):
    """The code can't run at all: a browser-only or unknown language, or a missing tool."""


async def run(code: str, lang: str, *, stdin: str = "", timeout: float = 10.0) -> RunResult:
    spec = resolve(lang)
    if spec is None or not spec.run:
        raise RunnerError(f"{lang or 'This code'} can't run here." + (" Use /web for HTML." if spec else ""))
    if shutil.which(spec.tool) is None:
        raise RunnerError(spec.install_hint)
    started = time.monotonic()
    deadline = started + timeout
    output, exit_code = "", 0
    with tempfile.TemporaryDirectory(prefix="fixel-play-") as tmp:
        work = Path(tmp)
        (work / spec.filename).write_text(code)
        for argv, feed in ((spec.build, ""), (spec.run, stdin)):
            if not argv:
                continue
            exit_code, out = await _exec(argv, work, feed, max(deadline - time.monotonic(), 0.1))
            output += out
            if exit_code != 0:
                break
    output = _cap(output)
    if exit_code is None:
        output += f"\n[stopped after {timeout:g}s]"
    return RunResult(exit_code, output, time.monotonic() - started)


def _cap(text: str) -> str:
    return text if len(text) <= OUTPUT_CAP else text[:OUTPUT_CAP] + "\n[output truncated]"


async def _exec(argv: tuple[str, ...], cwd: Path, stdin: str, timeout: float) -> tuple[int | None, str]:
    """Run one step in its own process group. Returns (exit code or None on timeout, output)."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # so a timeout kills the program's children too
    )
    buf = bytearray()

    async def pump() -> int:
        try:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
            proc.stdin.close()  # end-of-file, so input() never waits forever
        except (BrokenPipeError, ConnectionResetError):
            pass
        while chunk := await proc.stdout.read(65536):
            if len(buf) <= OUTPUT_CAP:
                buf.extend(chunk)
        return await proc.wait()

    try:
        code = await asyncio.wait_for(pump(), timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        return None, buf.decode(errors="replace")
    except asyncio.CancelledError:  # ⌃C in the editor, or Fixel quitting
        _kill(proc)
        raise
    return code, buf.decode(errors="replace")


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_runner.py`
Expected: PASS (Java/C++/Node tests skip only if those tools are missing)

- [ ] **Step 5: Commit**

```bash
git add fixel/playground/runner.py tests/test_playground_runner.py
git commit -m "feat(playground): runner for Python, Java, Node and C++ with timeout and output cap"
```

---

### Task 3: Scratch files and config

**Files:**
- Create: `fixel/playground/scratch.py`
- Modify: `fixel/config.py` (dataclass field, `playground_dir` property, load list, default TOML)
- Test: `tests/test_playground_scratch.py`, `tests/test_config.py` (add one test)

**Interfaces:**
- Consumes: `LANGS`, `RUNNABLE` from Task 1.
- Produces: `Scratch(folder: Path)` with `.path(lang) -> Path`, `.load(lang) -> str`, `.save(lang, code) -> None`, `.last_lang(choices=RUNNABLE, default="python") -> str`; `Config.playground_timeout: float = 10.0`; `Config.playground_dir -> Path` (`home / "playground"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_playground_scratch.py`:

```python
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
```

Add to `tests/test_config.py`:

```python
def test_playground_settings(tmp_path):
    from fixel.config import load_config

    (tmp_path / "config.toml").write_text("playground_timeout = 3\n")
    cfg = load_config(tmp_path)
    assert cfg.playground_timeout == 3 and cfg.playground_dir == tmp_path / "playground"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_scratch.py tests/test_config.py`
Expected: FAIL (`No module named 'fixel.playground.scratch'`, `AttributeError: playground_timeout`)

- [ ] **Step 3: Write the implementation**

`fixel/playground/scratch.py`:

```python
"""The user's scratch code, one file per language in ~/.fixel/playground/."""

from __future__ import annotations

from pathlib import Path

from .langs import LANGS, RUNNABLE

LAST_FILE = ".last"  # holds the last language saved


class Scratch:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, lang: str) -> Path:
        return self.folder / LANGS[lang].filename

    def load(self, lang: str) -> str:
        path = self.path(lang)
        return path.read_text() if path.exists() else LANGS[lang].starter

    def save(self, lang: str, code: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(lang).write_text(code)
        (self.folder / LAST_FILE).write_text(lang)

    def last_lang(self, choices: tuple[str, ...] = RUNNABLE, default: str = "python") -> str:
        try:
            name = (self.folder / LAST_FILE).read_text().strip()
        except OSError:
            return default
        return name if name in choices else default
```

In `fixel/config.py`:

1. Add to `DEFAULT_CONFIG_TOML` after the `slow_model_seconds` line:

```
playground_timeout = 10         # seconds a /code or /web run may take before Fixel stops it
```

2. Add to `Config` after `slow_model_seconds`:

```python
    playground_timeout: float = 10.0
```

3. Add a property after `about_me_path`:

```python
    @property
    def playground_dir(self) -> Path:
        return self.home / "playground"
```

4. Add `"playground_timeout"` to the tuple of names in `load_config`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_scratch.py tests/test_config.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fixel/playground/scratch.py fixel/config.py tests/test_playground_scratch.py tests/test_config.py
git commit -m "feat(playground): scratch files and playground_timeout setting"
```

---

### Task 4: Web mode (prompt, parsing, badge)

**Files:**
- Modify: `fixel/prompts.py` (header line, Choosing MODE, Answer format)
- Modify: `fixel/parse.py` (`MODES`, new `first_code_block`)
- Modify: `fixel/ui.py` (`BADGES["web"]`)
- Test: `tests/test_prompts.py`, `tests/test_parse.py`, `tests/test_ui.py` (add tests)

**Interfaces:**
- Produces: `"web"` in `parse.MODES`; `first_code_block(body: str) -> tuple[str, str] | None` returning `(lowercased fence tag, code without trailing newline)`, with an untagged block starting `<!doctype` or `<html` reported as `"html"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
def test_web_mode_is_offered_with_its_format():
    system = build_system(learn=False)
    assert "MODE: <error|math|doc|ui|web|general>" in system
    assert "- web:" in system and "**Libraries**" in system
    assert "exactly ONE ```html block" in system
    assert "View Source" in system
```

Add to `tests/test_parse.py`:

```python
from fixel.parse import first_code_block


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
```

Add to `tests/test_ui.py`:

```python
def test_web_answers_get_their_own_badge():
    from fixel.ui import BADGES

    assert BADGES["web"] not in (BADGES["ui"], BADGES["general"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_prompts.py tests/test_parse.py tests/test_ui.py`
Expected: FAIL (`ImportError: first_code_block`, missing web text, `KeyError: 'web'`)

- [ ] **Step 3: Write the implementation**

`fixel/parse.py`:

```python
MODES = ("error", "math", "doc", "ui", "web", "general")
```

and after `runnable_command`:

```python
def first_code_block(body: str) -> tuple[str, str] | None:
    """What ⌃P opens: the first code block as (language tag, code). Untagged HTML counts as html."""
    fence = _FENCE.search(body)
    if fence is None:
        return None
    lang, code = fence.group(1).lower(), fence.group(2).rstrip("\n")
    if not lang and code.lstrip().lower().startswith(("<!doctype", "<html")):
        lang = "html"
    return lang, code
```

`fixel/ui.py`, in `BADGES` after `"ui"`:

```python
    "web": "bold white on magenta",
```

`fixel/prompts.py`:

1. Header line becomes `MODE: <error|math|doc|ui|web|general>`.
2. In "## Choosing MODE", replace the `- ui:` line with these three lines:

```
- ui: an app or website screen where the user needs to know where to click or how to do something.
- web: a webpage, web app, landing page, or design mockup where the user wants to know how it's designed or built \
(fonts, colours, layout, libraries) or wants code that recreates it. With no question, a marketing page, portfolio, \
or landing page is web. When unsure between ui and web: a question about doing something is ui; a question about \
how it looks or how it's made is web.
```

3. In "## Answer format by MODE", after the `ui:` block and before `general:`, add:

```
web:
**Design**
- Type: font families (closest match; add a Google Fonts option if it isn't one) and the size/weight scale.
- Colours: 4-8 hex values, each with its role (background, text, accent, border...).
- Layout: page structure (grid/flex, columns, max width), spacing scale, corner radius, shadows.
- Components: the notable pieces (nav, hero, cards, buttons), one line each.
**Libraries** (best guess from pixels): 1-4 bullets as `Name (likely|possible): the visual tell`. \
If nothing stands out, say it looks like hand-written CSS. Finish with: Confirm with View Source or a \
tech-detection extension.
**Code:** exactly ONE ```html block: a complete document with inline <style>; a Google Fonts <link> is allowed; \
no other external files; no hotlinked images (use CSS gradients or inline SVG placeholders); text copied from the \
screenshot; responsive down to 375px wide.
```

- [ ] **Step 4: Run the whole suite** (the prompt is shared by every test that builds a system prompt)

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q`
Expected: PASS, 177 + new tests

- [ ] **Step 5: Commit**

```bash
git add fixel/prompts.py fixel/parse.py fixel/ui.py tests/test_prompts.py tests/test_parse.py tests/test_ui.py
git commit -m "feat: web mode explains a page's design and libraries and recreates it as one HTML file"
```

---

### Task 5: Code attachments in the session and toolbar

**Files:**
- Modify: `fixel/session.py` (`Session.code`, `attach_code`, `tray_text`, `starts_new_case`, `build_user_turn`, `rollback`, `new_case`, `_Undo`)
- Modify: `fixel/ui.py` (`Status.code`, `toolbar_text`)
- Test: `tests/test_session.py`, `tests/test_ui.py` (add tests)

**Interfaces:**
- Consumes: `CodeAttachment` from Task 1.
- Produces: `Session.code: CodeAttachment | None`; `Session.attach_code(att: CodeAttachment) -> None`; `Status.code: str` (language label, `""` when none). `build_user_turn` sends `context`, then `att.to_prompt_text()`, then the question, joined by blank lines; the attachment's code and output join `case.screen_text` so recall can find it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_session.py`:

```python
from fixel.playground.attachment import CodeAttachment

FAILED = CodeAttachment("python", "print(x)", output="NameError: x", exit_code=1, ran=True)


def test_code_attachment_is_sent_with_default_question():
    s = Session()
    s.attach_code(FAILED)
    assert s.starts_new_case()
    turn = s.build_user_turn("")
    assert turn.text.startswith("[Code from Fixel playground · python]")
    assert turn.text.endswith("NameError: x\n\nWhy doesn't this work?")
    assert s.code is None and s.case.question == "Why doesn't this work?"
    assert "NameError: x" in s.case.screen_text and "print(x)" in s.case.screen_text


def test_code_attachment_with_memory_and_typed_question():
    s = Session()
    s.attach_code(CodeAttachment("java", "class A {}"))
    turn = s.build_user_turn("is this ok?", context="[Fixel memory]")
    assert turn.text.startswith("[Fixel memory]\n\n[Code from Fixel playground · java]")
    assert turn.text.endswith("```\n\nis this ok?")


def test_code_after_an_answer_starts_a_new_case_and_rollback_restores_it():
    s = Session()
    s.build_user_turn("hi")
    answer(s)
    first = s.case
    s.attach_code(FAILED)
    assert s.starts_new_case()
    s.build_user_turn("")
    assert s.case is not first
    s.rollback()
    assert s.case is first and s.code == FAILED


def test_tray_text_includes_attached_code_and_new_case_clears_it(tmp_path):
    s = Session()
    s.attach_code(FAILED)
    assert "print(x)" in s.tray_text() and "NameError" in s.tray_text()
    s.new_case()
    assert s.code is None and s.tray_text() == ""
```

Add to `tests/test_ui.py`:

```python
def test_toolbar_shows_attached_code():
    text = toolbar_text(Status(code="Java"))
    assert text.startswith("📝 Java code in tray") and "⏎ ask" in text
    both = toolbar_text(Status(tray=1, code="Python"))
    assert both.startswith("📸 1 shot in tray · 📝 Python code in tray")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_session.py tests/test_ui.py`
Expected: FAIL (`AttributeError: 'Session' object has no attribute 'attach_code'`, `unexpected keyword argument 'code'`)

- [ ] **Step 3: Write the implementation**

`fixel/session.py`:

1. Import: `from .playground.attachment import CodeAttachment`.
2. `_Undo` gets a last field: `code: CodeAttachment | None`.
3. `Session` gets a field after `learn`: `code: CodeAttachment | None = None  # code from the playground, waiting to be asked about`.
4. New method after `set_shot_text`:

```python
    def attach_code(self, att: CodeAttachment) -> None:
        """Put playground code in the tray (one at a time; a new one replaces the old)."""
        self.code = att
```

5. `tray_text` becomes:

```python
    def tray_text(self) -> str:
        """Searchable text waiting to be sent: what's on the tray's screenshots, plus any attached code and its output."""
        texts = [text for path in self.tray if (text := self._shot_text.get(path))]
        if self.code is not None:
            texts += [part for part in (self.code.code.strip(), self.code.output.strip()) if part]
        return "\n".join(texts)
```

6. `starts_new_case`:

```python
        return not self.case.turns or ((bool(self.tray) or self.code is not None) and not self.follow_up)
```

7. `new_case` adds `self.code = None`.
8. In `build_user_turn`: the `_Undo(...)` call gets `self.code` as its last argument; then

```python
        if (self.tray or self.code is not None) and case.turns and not self.follow_up:
            self.case = Case()
        default = self.code.default_question() if self.code is not None else DEFAULT_QUESTION
        question = text.strip() or default
        attached = self.code.to_prompt_text() if self.code is not None else ""
        sent = "\n\n".join(part for part in (context, attached, question) if part)
```

replacing the old `if self.tray and case.turns...`, `question = ...` and `sent = ...` lines; and after `self.follow_up = False` at the end, add `self.code = None` (before `return turn`).
9. `rollback` adds `self.code = undo.code`.

`fixel/ui.py`:

1. `Status` gets `code: str = ""  # label of the attached playground code's language` after `follow_up`.
2. `toolbar_text`, replacing the `if status.tray:` block:

```python
    if status.tray or status.code:
        parts = []
        if status.tray:
            plural = "" if status.tray == 1 else "s"
            parts.append(f"📸 {status.tray} shot{plural} in tray")
        if status.code:
            parts.append(f"📝 {status.code} code in tray")
        follow = "on" if status.follow_up else "off"
        return " · ".join(parts) + f" · ⏎ ask · ⌥⌥ add more · ⌃F follow-up: {follow}"
```

- [ ] **Step 4: Run the whole suite**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fixel/session.py fixel/ui.py tests/test_session.py tests/test_ui.py
git commit -m "feat(playground): code attachments ride the tray into a normal case"
```

---

### Task 6: Terminal editor (`/code`)

**Files:**
- Create: `fixel/playground/editor.py`
- Test: `tests/test_playground_editor.py`

**Interfaces:**
- Consumes: `LANGS`, `RUNNABLE` (Task 1), `RunResult`, `RunnerError` (Task 2), `Scratch` (Task 3), `CodeAttachment` (Task 1).
- Produces: `RunFn = Callable[[str, str, str], Awaitable[RunResult]]` (code, lang, stdin); `EditorResult(lang: str, code: str, attachment: CodeAttachment | None)`; `format_result(result: RunResult) -> str`; `Editor(scratch, lang, code, run, *, input=None, output=None)` with `async edit() -> EditorResult`. Keys: F5 run, ⌃C stop a run, F3 input pane, F2 next language, ⌃A attach and close, Esc close, Tab inserts 4 spaces. Saves the scratch file on run and on close, but on close only if the code changed or was run.

- [ ] **Step 1: Write the failing tests**

`tests/test_playground_editor.py`:

```python
import asyncio

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from fixel.playground.editor import Editor, format_result
from fixel.playground.runner import RunnerError, RunResult
from fixel.playground.scratch import Scratch

F2, F3, F5, CTRL_A, ESC = "\x1bOQ", "\x1bOR", "\x1b[15~", "\x01", "\x1b"


class FakeRun:
    def __init__(self, result=RunResult(1, "NameError: x\n", 0.2), error=None):
        self.calls, self.result, self.error = [], result, error

    async def __call__(self, code, lang, stdin):
        self.calls.append((code, lang, stdin))
        if self.error:
            raise self.error
        return self.result


async def until(predicate, timeout=2.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


@pytest.fixture
def pipe():
    with create_pipe_input() as inp:
        yield inp


def start(tmp_path, pipe, run, lang="python", code="print(x)"):
    editor = Editor(Scratch(tmp_path), lang, code, run, input=pipe, output=DummyOutput())
    return editor, asyncio.create_task(editor.edit())


def test_format_result():
    assert format_result(RunResult(0, "hi\n", 0.42)) == "hi\n── exit 0 · 0.4s"
    assert format_result(RunResult(None, "", 10.0)) == "(no output)\n── stopped · 10.0s"


async def test_f5_runs_and_ctrl_a_attaches_code_and_output(tmp_path, pipe):
    run = FakeRun()
    editor, task = start(tmp_path, pipe, run)
    pipe.send_text(F5)
    await until(lambda: editor.last is not None)
    assert "NameError" in editor.output.text and "exit 1" in editor.output.text
    pipe.send_text(CTRL_A)
    result = await asyncio.wait_for(task, 2)
    assert run.calls == [("print(x)", "python", "")]
    assert result.attachment.failed and result.attachment.output == "NameError: x\n"
    assert Scratch(tmp_path).load("python") == "print(x)"


async def test_attach_after_edit_drops_stale_output(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun())
    pipe.send_text(F5)
    await until(lambda: editor.last is not None)
    pipe.send_text("# changed")
    await until(lambda: "# changed" in editor.code.text)
    pipe.send_text(CTRL_A)
    att = (await asyncio.wait_for(task, 2)).attachment
    assert att.ran is False and att.output == "" and att.code.endswith("# changed")


async def test_input_pane_feeds_stdin(tmp_path, pipe):
    run = FakeRun(RunResult(0, "", 0.1))
    editor, task = start(tmp_path, pipe, run)
    pipe.send_text(F3)
    await until(lambda: editor.show_input)
    pipe.send_text("5 7")
    await until(lambda: editor.stdin.text == "5 7")
    pipe.send_text(F5)
    await until(lambda: run.calls)
    assert run.calls[0][2] == "5 7"
    pipe.send_text(CTRL_A)
    await asyncio.wait_for(task, 2)


async def test_runner_error_is_shown(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun(error=RunnerError("Java isn't installed.")), lang="java")
    pipe.send_text(F5)
    await until(lambda: "isn't installed" in editor.output.text)
    pipe.send_text(CTRL_A)
    assert (await asyncio.wait_for(task, 2)).attachment.ran is False


async def test_f2_switches_language_and_saves(tmp_path, pipe):
    editor, task = start(tmp_path, pipe, FakeRun())
    pipe.send_text(F2)
    await until(lambda: editor.lang == "java")
    assert "public class Main" in editor.code.text
    assert Scratch(tmp_path).load("python") == "print(x)"
    pipe.send_text(CTRL_A)
    assert (await asyncio.wait_for(task, 2)).lang == "java"


async def test_esc_closes_without_attaching_and_leaves_untouched_scratch(tmp_path, pipe):
    Scratch(tmp_path).save("python", "old")
    editor, task = start(tmp_path, pipe, FakeRun(), code="handed off by ctrl+p")
    pipe.send_text(ESC)
    result = await asyncio.wait_for(task, 2)
    assert result.attachment is None
    assert Scratch(tmp_path).load("python") == "old"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_editor.py`
Expected: FAIL with `No module named 'fixel.playground.editor'`

- [ ] **Step 3: Write the implementation**

`fixel/playground/editor.py`:

```python
"""/code: a full-screen code editor in the terminal, with an output pane and a Run key."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import merge_styles, style_from_pygments_cls
from prompt_toolkit.widgets import TextArea
from pygments.styles import get_style_by_name

from .attachment import CodeAttachment
from .langs import LANGS, RUNNABLE
from .runner import RunnerError, RunResult
from .scratch import Scratch

RunFn = Callable[[str, str, str], Awaitable[RunResult]]  # (code, lang, stdin)


@dataclass(frozen=True)
class EditorResult:
    lang: str
    code: str
    attachment: CodeAttachment | None  # set when the user pressed ⌃A


def format_result(result: RunResult) -> str:
    status = "stopped" if result.exit_code is None else f"exit {result.exit_code}"
    return f"{result.output.rstrip() or '(no output)'}\n── {status} · {result.seconds:.1f}s"


class Editor:
    def __init__(self, scratch: Scratch, lang: str, code: str, run: RunFn, *, input=None, output=None) -> None:
        self.scratch = scratch
        self.lang = lang
        self.last: RunResult | None = None
        self.show_input = False
        self._run = run
        self._opened_with = code
        self._ran_code: str | None = None  # the code `last` came from
        self._task: asyncio.Task | None = None
        self.code = TextArea(text=code, lexer=self._lexer(), line_numbers=True, scrollbar=True)
        self.stdin = TextArea(height=Dimension(preferred=3, max=6), prompt="stdin› ")
        self.output = TextArea(
            text="F5 runs your code.", read_only=True, scrollbar=True, height=Dimension(preferred=8, max=12)
        )
        rule = lambda: Window(height=1, char="─", style="class:rule")  # noqa: E731
        body = HSplit([
            self.code,
            rule(),
            ConditionalContainer(HSplit([self.stdin, rule()]), filter=Condition(lambda: self.show_input)),
            self.output,
            Window(FormattedTextControl(self._status_text), height=1, style="reverse"),
        ])
        self.app = Application(
            layout=Layout(body, focused_element=self.code),
            key_bindings=self._bindings(),
            style=merge_styles([style_from_pygments_cls(get_style_by_name("monokai"))]),
            full_screen=True,
            mouse_support=True,
            input=input,
            output=output,
        )
        self.app.ttimeoutlen = 0.05  # Esc closes without a half-second wait

    async def edit(self) -> EditorResult:
        return await self.app.run_async()

    # ---- pieces

    def _lexer(self) -> PygmentsLexer:
        return PygmentsLexer.from_filename(LANGS[self.lang].filename)

    def _status_text(self) -> str:
        running = " · running… ⌃C stops" if self._running else ""
        return f" {LANGS[self.lang].label} · F5 run · F3 input · F2 language · ⌃A ask Fixel · Esc back{running} "

    @property
    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _attachment(self) -> CodeAttachment:
        code = self.code.text
        if self.last is None or self._ran_code != code:  # never run, or edited since: old output would mislead
            return CodeAttachment(self.lang, code)
        return CodeAttachment(self.lang, code, self.last.output, self.last.exit_code, ran=True)

    def _close(self, attach: bool) -> None:
        if self._running:
            self._task.cancel()
        if self.code.text != self._opened_with or self.last is not None:
            self.scratch.save(self.lang, self.code.text)
        self.app.exit(result=EditorResult(self.lang, self.code.text, self._attachment() if attach else None))

    async def _run_now(self) -> None:
        code = self.code.text
        self.scratch.save(self.lang, code)
        self.output.text = "Running…"
        self.app.invalidate()
        try:
            result = await self._run(code, self.lang, self.stdin.text)
        except RunnerError as e:
            self.output.text = str(e)
        except asyncio.CancelledError:
            self.output.text = "Stopped."
            raise
        else:
            self.last, self._ran_code = result, code
            self.output.text = format_result(result)
        finally:
            self.app.invalidate()

    def _switch_language(self) -> None:
        self.scratch.save(self.lang, self.code.text)
        self.lang = RUNNABLE[(RUNNABLE.index(self.lang) + 1) % len(RUNNABLE)]
        text = self.scratch.load(self.lang)
        self.code.text, self._opened_with = text, text
        self.code.lexer = self._lexer()  # TextArea reads it through a DynamicLexer
        self.last, self._ran_code = None, None
        self.output.text = "F5 runs your code."

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("f5")
        def _(event) -> None:
            if not self._running:
                self._task = asyncio.ensure_future(self._run_now())

        @kb.add("c-c")
        def _(event) -> None:
            if self._running:
                self._task.cancel()

        @kb.add("f3")
        def _(event) -> None:
            self.show_input = not self.show_input
            event.app.layout.focus(self.stdin if self.show_input else self.code)

        @kb.add("f2")
        def _(event) -> None:
            if not self._running:
                self._switch_language()

        @kb.add("c-a")
        def _(event) -> None:
            self._close(attach=True)

        @kb.add("escape", eager=True)
        def _(event) -> None:
            self._close(attach=False)

        @kb.add("tab", filter=has_focus(self.code))
        def _(event) -> None:
            event.current_buffer.insert_text("    ")

        return kb
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_editor.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fixel/playground/editor.py tests/test_playground_editor.py
git commit -m "feat(playground): full-screen terminal editor with run, input, language switch and ask"
```

---

### Task 7: Browser playground server and page (`/web`)

**Files:**
- Create: `fixel/playground/server.py`, `fixel/playground/web/index.html`
- Modify: `pyproject.toml` (package data)
- Test: `tests/test_playground_server.py`

**Interfaces:**
- Consumes: `LANGS`, `RUNNABLE` (Task 1), `RunnerError` (Task 2), `Scratch` (Task 3), `CodeAttachment` (Task 1), `RunFn` (Task 6).
- Produces: `PlaygroundServer(loop, scratch, run: RunFn, on_ask: Callable[[CodeAttachment], None], *, token: str | None = None)` with `start(port=0)`, `stop()`, `hand_off(lang, code)`, properties `running`, `port`, `origin`, `url` (`http://127.0.0.1:<port>/#<token>`); `MAX_BODY = 1_000_000`. Endpoints: `GET /`, `GET /api/state`, `GET /api/scratch?lang=`, `POST /api/run`, `POST /api/ask`, `POST /api/save`.

- [ ] **Step 1: Write the failing tests**

`tests/test_playground_server.py`:

```python
import asyncio
import http.client
import json

import pytest

from fixel.playground.runner import RunnerError, RunResult
from fixel.playground.scratch import Scratch
from fixel.playground.server import MAX_BODY, PlaygroundServer


@pytest.fixture
async def web(tmp_path):
    asked, runs = [], []

    async def fake_run(code, lang, stdin):
        runs.append((code, lang, stdin))
        if lang == "java":
            raise RunnerError("Java isn't installed.")
        return RunResult(0, "ok\n", 0.1)

    server = PlaygroundServer(asyncio.get_running_loop(), Scratch(tmp_path), fake_run, asked.append, token="T0KEN")
    server.start()
    server.asked, server.runs = asked, runs
    yield server
    server.stop()


async def call(server, method, path, body=None, *, token="T0KEN", origin=None, raw=None, headers=None):
    def go():
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        if token is not None:
            hdrs["X-Fixel-Token"] = token
        if origin is not None:
            hdrs["Origin"] = origin
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp.status, payload

    status, payload = await asyncio.to_thread(go)
    try:
        return status, json.loads(payload)
    except ValueError:
        return status, payload


async def test_page_is_served_and_url_carries_token(web):
    status, page = await call(web, "GET", "/", token=None)
    assert status == 200 and b"Fixel Playground" in page and b'sandbox="allow-scripts"' in page
    assert web.url == f"http://127.0.0.1:{web.port}/#T0KEN"


async def test_api_needs_the_token_and_our_origin(web):
    assert (await call(web, "GET", "/api/state", token=None))[0] == 403
    assert (await call(web, "GET", "/api/state", token="wrong"))[0] == 403
    assert (await call(web, "POST", "/api/run", {"lang": "python", "code": "1"}, origin="https://evil.example"))[0] == 403
    assert (await call(web, "POST", "/api/run", {"lang": "python", "code": "1"}, origin=web.origin))[0] == 200
    assert web.runs == [("1", "python", "")]


async def test_run_saves_scratch_and_reports_runner_errors(web, tmp_path):
    status, data = await call(web, "POST", "/api/run", {"lang": "python", "code": "print(1)", "stdin": "x"})
    assert status == 200 and data == {"exit_code": 0, "output": "ok\n", "seconds": 0.1}
    assert Scratch(tmp_path).load("python") == "print(1)"
    status, data = await call(web, "POST", "/api/run", {"lang": "java", "code": "x"})
    assert status == 200 and data["error"] is True and "isn't installed" in data["output"]
    assert (await call(web, "POST", "/api/run", {"lang": "html", "code": "<p>"}))[0] == 400


async def test_state_prefers_a_handoff_once_then_scratch(web, tmp_path):
    Scratch(tmp_path).save("javascript", "console.log(1)")
    web.hand_off("html", "<h1>clone</h1>")
    _, first = await call(web, "GET", "/api/state")
    _, second = await call(web, "GET", "/api/state")
    assert (first["lang"], first["code"]) == ("html", "<h1>clone</h1>")
    assert (second["lang"], second["code"]) == ("javascript", "console.log(1)")
    assert {"name": "cpp", "label": "C++", "runnable": True, "filename": "main.cpp"} in first["langs"]


async def test_scratch_endpoint_and_save(web):
    assert (await call(web, "POST", "/api/save", {"lang": "html", "code": "<p>saved</p>"}))[0] == 200
    _, data = await call(web, "GET", "/api/scratch?lang=html")
    assert data == {"lang": "html", "code": "<p>saved</p>"}
    assert (await call(web, "GET", "/api/scratch?lang=cobol"))[0] == 400


async def test_ask_hands_an_attachment_to_fixel(web):
    body = {"lang": "python", "code": "print(x)", "output": "NameError", "exit_code": 1, "ran": True}
    assert (await call(web, "POST", "/api/ask", body))[0] == 200
    await asyncio.sleep(0.05)  # on_ask runs on Fixel's loop
    (att,) = web.asked
    assert att.failed and att.code == "print(x)" and att.output == "NameError"


async def test_malformed_requests_get_400(web):
    assert (await call(web, "POST", "/api/run", raw=b"not json"))[0] == 400
    assert (await call(web, "POST", "/api/run", raw=b"[1, 2]"))[0] == 400
    assert (await call(web, "POST", "/api/run", {"lang": 5, "code": None}))[0] == 400
    assert (await call(web, "POST", "/api/run", raw=b"{}", headers={"Content-Length": "-1"}))[0] == 400
    assert (await call(web, "POST", "/api/nope", {}))[0] == 404


async def test_large_bodies_are_refused(web):
    status, _ = await call(web, "POST", "/api/save", raw=b"x" * (MAX_BODY + 1))
    assert status == 413


async def test_stop_frees_the_server(web):
    web.stop()
    assert not web.running
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_server.py`
Expected: FAIL with `No module named 'fixel.playground.server'`

- [ ] **Step 3: Write the server**

`fixel/playground/server.py`:

```python
"""/web: the browser playground. Serves one page and a small JSON API on 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .attachment import CodeAttachment
from .editor import RunFn
from .langs import LANGS, RUNNABLE
from .runner import RunnerError
from .scratch import Scratch

MAX_BODY = 1_000_000
PAGE = files(__package__) / "web" / "index.html"


class PlaygroundServer:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        scratch: Scratch,
        run: RunFn,
        on_ask: Callable[[CodeAttachment], None],
        *,
        token: str | None = None,
    ) -> None:
        self.loop = loop
        self.scratch = scratch
        self.token = token or secrets.token_urlsafe(32)
        self._run = run
        self._on_ask = on_ask
        self._handoff: tuple[str, str] | None = None
        self._httpd: ThreadingHTTPServer | None = None

    # ---- lifecycle (Fixel's loop)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.origin}/#{self.token}"  # a fragment: the browser never sends it by itself

    def start(self, port: int = 0) -> None:
        if self._httpd is not None:
            return
        handler = type("Handler", (_Handler,), {"playground": self})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="fixel-web", daemon=True).start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def hand_off(self, lang: str, code: str) -> None:
        """⌃P: the next page load opens this code instead of the scratch file."""
        self._handoff = (lang, code)

    # ---- API (server thread). Each returns (status, payload).

    def api_state(self, query: dict) -> tuple[int, dict]:
        if self._handoff is not None:
            (lang, code), self._handoff = self._handoff, None
        else:
            lang = self.scratch.last_lang(choices=tuple(LANGS))
            code = self.scratch.load(lang)
        langs = [
            {"name": name, "label": spec.label, "runnable": bool(spec.run), "filename": spec.filename}
            for name, spec in LANGS.items()
        ]
        return 200, {"lang": lang, "code": code, "langs": langs}

    def api_scratch(self, query: dict) -> tuple[int, dict]:
        lang = query.get("lang", [""])[0]
        if lang not in LANGS:
            return 400, {"error": f"Unknown language {lang!r}."}
        return 200, {"lang": lang, "code": self.scratch.load(lang)}

    def api_run(self, body: dict) -> tuple[int, dict]:
        lang, code, stdin = body["lang"], body["code"], body["stdin"]
        if lang not in RUNNABLE:
            return 400, {"error": f"{lang} runs in the preview, not the runner."}
        future = asyncio.run_coroutine_threadsafe(self._run(code, lang, stdin), self.loop)
        try:
            result = future.result()
        except RunnerError as e:
            return 200, {"exit_code": None, "output": str(e), "seconds": 0.0, "error": True}
        self.scratch.save(lang, code)
        return 200, {"exit_code": result.exit_code, "output": result.output, "seconds": round(result.seconds, 2)}

    def api_ask(self, body: dict) -> tuple[int, dict]:
        lang = body["lang"]
        if lang not in LANGS:
            return 400, {"error": f"Unknown language {lang!r}."}
        exit_code = body.get("exit_code")
        att = CodeAttachment(
            lang, body["code"], body["output"],
            exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
            ran=body.get("ran") is True,
        )
        self.loop.call_soon_threadsafe(self._on_ask, att)
        return 200, {"ok": True}

    def api_save(self, body: dict) -> tuple[int, dict]:
        if body["lang"] not in LANGS:
            return 400, {"error": f"Unknown language {body['lang']!r}."}
        self.scratch.save(body["lang"], body["code"])
        return 200, {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    playground: PlaygroundServer
    server_version = "Fixel"

    def log_message(self, format, *args) -> None:  # keep Fixel's terminal clean
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        routes = {"/api/state": self.playground.api_state, "/api/scratch": self.playground.api_scratch}
        route = routes.get(url.path)
        if route is None:
            self._json(404, {"error": "Not found."})
        elif self._allowed():
            self._json(*route(parse_qs(url.query)))

    def do_POST(self) -> None:
        routes = {"/api/run": self.playground.api_run, "/api/ask": self.playground.api_ask,
                  "/api/save": self.playground.api_save}
        route = routes.get(urlsplit(self.path).path)
        if route is None:
            self._json(404, {"error": "Not found."})
            return
        if not self._allowed():
            return
        body = self._read_body()
        if body is not None:
            self._json(*route(body))

    def _allowed(self) -> bool:
        token = self.headers.get("X-Fixel-Token", "")
        origin = self.headers.get("Origin")
        if not hmac.compare_digest(token.encode(), self.playground.token.encode()) or (
            origin is not None and origin != self.playground.origin
        ):
            self._json(403, {"error": "Open the playground from Fixel with /web."})
            return False
        return True

    def _read_body(self) -> dict | None:
        """The JSON body with string fields guaranteed, or None after sending an error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self._json(400, {"error": "Bad Content-Length."})
            return None
        if length > MAX_BODY:
            self._json(413, {"error": "That's too much code for the playground (1 MB max)."})
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "Expected a JSON object."})
            return None
        for field in ("lang", "code", "stdin", "output"):
            value = body.get(field, "")
            if not isinstance(value, str):
                self._json(400, {"error": f"{field} must be text."})
                return None
            body[field] = value
        return body

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
```

Note on the 413 test: the client sends 1 MB + 1 bytes and the server answers without reading them. `http.client` may raise `ConnectionResetError` or `BrokenPipeError` while sending. If that happens on macOS, have `_read_body` drain up to `MAX_BODY * 2` bytes before replying (`self.rfile.read(min(length, MAX_BODY * 2))`) rather than weakening the test.

- [ ] **Step 4: Write the page**

`fixel/playground/web/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fixel Playground</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/clike/clike.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/xml/xml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/css/css.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/htmlmixed/htmlmixed.min.js"></script>
<style>
  :root {
    --bg: #f6f5f2; --panel: #ffffff; --text: #1d1d1f; --muted: #6e6e73; --line: #e2e0da;
    --accent: #2f9e6b; --accent-text: #ffffff; --bad: #c4352b; --code-bg: #fbfbfa;
    --mono: ui-monospace, "SF Mono", Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141416; --panel: #1c1c1f; --text: #ececee; --muted: #9a9aa0; --line: #2c2c31;
      --accent: #3fbf86; --accent-text: #0d1f17; --bad: #ff6b5e; --code-bg: #18181b;
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--bg); color: var(--text); font: 14px/1.4 system-ui, -apple-system, sans-serif;
         display: flex; flex-direction: column; }
  header { display: flex; gap: 8px; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--line);
           flex-wrap: wrap; }
  header h1 { font-size: 15px; margin: 0 auto 0 0; letter-spacing: .02em; }
  header h1 span { color: var(--accent); }
  select, button { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
                   border-radius: 8px; padding: 6px 12px; cursor: pointer; }
  button.primary { background: var(--accent); color: var(--accent-text); border-color: var(--accent); font-weight: 600; }
  button:disabled { opacity: .5; cursor: default; }
  main { flex: 1; display: grid; grid-template-columns: 1fr 1fr; min-height: 0; }
  .pane { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
  .pane + .pane { border-left: 1px solid var(--line); }
  .label { font-size: 12px; color: var(--muted); padding: 6px 16px; border-bottom: 1px solid var(--line); }
  #source, .CodeMirror { flex: 1; height: 100%; width: 100%; font: 13px/1.5 var(--mono); background: var(--code-bg);
                         color: var(--text); border: 0; padding: 8px; resize: none; }
  .CodeMirror-gutters { background: var(--code-bg); border-right: 1px solid var(--line); }
  .CodeMirror-cursor { border-left-color: var(--text); }
  .editor-wrap { flex: 1; min-height: 0; display: flex; }
  iframe { flex: 1; border: 0; background: #fff; width: 100%; }
  #runner { flex: 1; display: none; flex-direction: column; min-height: 0; }
  #output { flex: 1; margin: 0; padding: 12px 16px; overflow: auto; font: 13px/1.5 var(--mono); white-space: pre-wrap; }
  #output.bad { color: var(--bad); }
  #stdin { height: 80px; font: 13px/1.5 var(--mono); background: var(--code-bg); color: var(--text); border: 0;
           border-top: 1px solid var(--line); padding: 8px 16px; resize: vertical; }
  #toast { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); background: var(--text);
           color: var(--bg); padding: 8px 14px; border-radius: 8px; opacity: 0; transition: opacity .2s; pointer-events: none; }
  #toast.show { opacity: 1; }
  @media (max-width: 760px) {
    main { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
    .pane + .pane { border-left: 0; border-top: 1px solid var(--line); }
  }
</style>
</head>
<body>
<header>
  <h1><span>●</span> Fixel Playground</h1>
  <select id="lang" aria-label="Language"></select>
  <button id="run" class="primary" title="⌘↵">Run</button>
  <button id="ask">Ask Fixel</button>
  <button id="download">Download</button>
</header>
<main>
  <section class="pane">
    <div class="label" id="file">main.py</div>
    <div class="editor-wrap"><textarea id="source" spellcheck="false"></textarea></div>
  </section>
  <section class="pane">
    <div class="label" id="right-label">Preview</div>
    <iframe id="preview" sandbox="allow-scripts" title="Preview"></iframe>
    <div id="runner">
      <pre id="output">Run your code to see its output.</pre>
      <textarea id="stdin" placeholder="Input (stdin) for your program" spellcheck="false"></textarea>
    </div>
  </section>
</main>
<div id="toast" role="status"></div>
<script>
const token = location.hash.slice(1);
const $ = (id) => document.getElementById(id);
const MODES = { python: "python", java: "text/x-java", javascript: "javascript", cpp: "text/x-c++src", html: "htmlmixed" };
let langs = {}, lang = "python", lastRun = null, saveTimer = null, previewTimer = null;

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "X-Fixel-Token": token, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Fixel said ${res.status}`);
  return data;
}

const cm = window.CodeMirror
  ? CodeMirror.fromTextArea($("source"), {
      lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false,
      extraKeys: { "Cmd-Enter": run, "Ctrl-Enter": run, Tab: (ed) => ed.replaceSelection("    ") },
    })
  : null;  // offline: the plain textarea still works
const getCode = () => (cm ? cm.getValue() : $("source").value);
const setCode = (text) => (cm ? cm.setValue(text) : ($("source").value = text));
if (!cm) $("source").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); });

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 3000);
}

function showLang(name, code) {
  lang = name;
  lastRun = null;
  $("lang").value = name;
  $("file").textContent = langs[name].filename;
  setCode(code);
  if (cm) cm.setOption("mode", MODES[name]);
  const runnable = langs[name].runnable;
  $("run").disabled = !runnable;
  $("preview").style.display = runnable ? "none" : "block";
  $("runner").style.display = runnable ? "flex" : "none";
  $("right-label").textContent = runnable ? "Output" : "Preview";
  $("output").textContent = "Run your code to see its output.";
  $("output").classList.remove("bad");
  if (!runnable) updatePreview();
}

function updatePreview() { $("preview").srcdoc = getCode(); }

function onEdit() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api("/api/save", { lang, code: getCode() }).catch(() => {}), 1000);
  if (!langs[lang].runnable) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 300);
  }
}
if (cm) cm.on("change", onEdit); else $("source").addEventListener("input", onEdit);

async function run() {
  if (!langs[lang] || !langs[lang].runnable || $("run").disabled) return;
  const code = getCode();
  $("run").disabled = true;
  $("output").classList.remove("bad");
  $("output").textContent = "Running…";
  try {
    const r = await api("/api/run", { lang, code, stdin: $("stdin").value });
    const status = r.exit_code === null ? "stopped" : `exit ${r.exit_code}`;
    $("output").textContent = `${r.output.trimEnd() || "(no output)"}\n── ${status} · ${r.seconds.toFixed(1)}s`;
    $("output").classList.toggle("bad", r.exit_code !== 0);
    lastRun = r.error ? null : { code, output: r.output, exit_code: r.exit_code };
  } catch (e) {
    $("output").textContent = e.message;
    $("output").classList.add("bad");
  } finally {
    $("run").disabled = false;
  }
}

async function ask() {
  const code = getCode();
  const fresh = lastRun && lastRun.code === code;  // edited since the run? then the old output would mislead
  try {
    await api("/api/ask", {
      lang, code, output: fresh ? lastRun.output : "", exit_code: fresh ? lastRun.exit_code : null, ran: !!fresh,
    });
    toast("Sent to Fixel. Switch to the terminal and press Enter.");
  } catch (e) { toast(e.message); }
}

function download() {
  const url = URL.createObjectURL(new Blob([getCode()], { type: "text/plain" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: langs[lang].filename });
  a.click();
  URL.revokeObjectURL(url);
}

$("run").addEventListener("click", run);
$("ask").addEventListener("click", ask);
$("download").addEventListener("click", download);
$("lang").addEventListener("change", async (e) => {
  const next = e.target.value;
  await api("/api/save", { lang, code: getCode() }).catch(() => {});
  const data = await api(`/api/scratch?lang=${encodeURIComponent(next)}`);
  showLang(next, data.code);
});

(async () => {
  try {
    const state = await api("/api/state");
    for (const l of state.langs) {
      langs[l.name] = l;
      $("lang").append(new Option(l.label, l.name));
    }
    showLang(state.lang, state.code);
  } catch (e) {
    $("output").textContent = `${e.message} Open the playground from Fixel with /web.`;
    $("runner").style.display = "flex";
    $("preview").style.display = "none";
  }
})();
</script>
</body>
</html>
```

Subresource Integrity: give every cdnjs `<script>` and the stylesheet `integrity="sha384-…" crossorigin="anonymous"`, with each hash computed from the real file:
`curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A`. If CodeMirror fails to load (offline or hash mismatch) the page falls back to the textarea.

In `pyproject.toml`, after `[tool.setuptools.packages.find]`:

```toml
[tool.setuptools.package-data]
"fixel.playground" = ["web/*.html"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_playground_server.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add fixel/playground/server.py fixel/playground/web/index.html pyproject.toml tests/test_playground_server.py
git commit -m "feat(playground): local browser playground with live HTML preview and token-protected API"
```

---

### Task 8: Wire it into Fixel (`/code`, `/web`, ⌃P, help, README)

**Files:**
- Modify: `fixel/actions.py` (`open_url`)
- Modify: `fixel/app.py` (constructor, `attach_code`, `open_editor`, `open_web`, `play`, `/code`, `/web`, `play` action, run loop, `_looks_stray`, `_sync_status`, `_finish`, server stop)
- Modify: `fixel/ui.py` (`ACTION_KEYS`, `HELP`, `playground_hint`)
- Modify: `README.md`
- Test: `tests/test_app_playground.py`, `tests/test_ui.py` (add one test)

**Interfaces:**
- Consumes: everything above. `Editor(scratch, lang, code, run).edit() -> EditorResult`; `PlaygroundServer(loop, scratch, run, on_ask)`; `first_code_block`; `resolve`; `Session.attach_code`; `Status.code`.
- Produces: `FixelApp(..., editor_factory=Editor, server_factory=PlaygroundServer, open_url=actions.open_url)`; `FixelApp.attach_code(att)`, `async open_editor(lang, code=None)`, `open_web(handoff=None)`, `async play()`; `UI.playground_hint(where: str)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_app_playground.py`:

```python
from fixel.app import FixelApp
from fixel.brain.fake import FakeProvider
from fixel.casefile import CaseFile
from fixel.config import Config
from fixel.parse import Header
from fixel.playground.attachment import CodeAttachment
from fixel.playground.editor import EditorResult
from fixel.ui import UI

WEB = "MODE: web\nKEY: Acme landing page\n---\n**Design**\n- Type: Inter\n**Code:**\n```html\n<!doctype html><h1>Acme</h1>\n```\n"
PY = "MODE: error\nKEY: NameError\n---\n**Cause:** typo.\n**Fix:**\n```python\nprint(x)\n```\n"
BASH = "MODE: error\nKEY: numpy\n---\n**Fix:**\n```bash\npip install numpy\n```\n"


class FakeEditor:
    opened = []
    attach = None

    def __init__(self, scratch, lang, code, run):
        FakeEditor.opened.append((lang, code))
        self.lang, self.code = lang, code

    async def edit(self):
        return EditorResult(self.lang, self.code, FakeEditor.attach)


class FakeServer:
    instances = []

    def __init__(self, loop, scratch, run, on_ask):
        self.on_ask, self.handoffs, self.started, self.stopped = on_ask, [], 0, False
        self.url, self.origin = "http://127.0.0.1:9/#tok", "http://127.0.0.1:9"
        FakeServer.instances.append(self)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped = True

    def hand_off(self, lang, code):
        self.handoffs.append((lang, code))


def make_app(tmp_path, console, replies=()):
    FakeEditor.opened, FakeEditor.attach, FakeServer.instances = [], None, []
    opened_urls = []
    app = FixelApp(
        Config(home=tmp_path, notes_dir=tmp_path / "notes"), UI(console),
        provider_factory=lambda alias, cfg: FakeProvider(list(replies)),
        casefile=CaseFile(tmp_path / "c.db"),
        editor_factory=FakeEditor, server_factory=FakeServer, open_url=opened_urls.append,
    )
    app.select_model("sonnet")
    app.opened_urls = opened_urls
    return app


async def test_code_command_opens_editor_in_last_or_named_language(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/code")
    await app.handle_command("/code c++")
    assert [lang for lang, _ in FakeEditor.opened] == ["python", "cpp"]
    assert "public" not in FakeEditor.opened[0][1]  # python starter, not java


async def test_code_command_rejects_html_and_unknown(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/code html")
    await app.handle_command("/code rust")
    out = console.file.getvalue()
    assert "/web" in out and "Unknown language 'rust'" in out and FakeEditor.opened == []


async def test_ctrl_a_in_editor_puts_code_in_tray_and_enter_asks(tmp_path, console):
    app = make_app(tmp_path, console, [PY])
    FakeEditor.attach = CodeAttachment("python", "print(x)", "NameError", 1, ran=True)
    await app.handle_command("/code")
    assert app.ui.status.code == "Python" and app.session.code is not None
    assert await app.ask("") == ""
    sent = app.provider.calls[0][0][-1].text
    assert "[Code from Fixel playground · python]" in sent and sent.endswith("Why doesn't this work?")
    assert app.ui.status.code == ""


async def test_web_command_starts_one_server_and_opens_browser(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/web")
    await app.handle_command("/web")
    (server,) = FakeServer.instances
    assert server.started == 1 and app.opened_urls == [server.url, server.url]


async def test_browser_ask_attaches_code(tmp_path, console):
    app = make_app(tmp_path, console)
    await app.handle_command("/web")
    FakeServer.instances[0].on_ask(CodeAttachment("javascript", "console.log(1)"))
    assert app.ui.status.code == "JavaScript" and "Enter" in app.ui.status.flash


async def test_ctrl_p_routes_html_to_web_and_code_to_editor(tmp_path, console):
    app = make_app(tmp_path, console, [WEB, PY])
    await app.ask("clone this")
    assert "⌃P opens this code" in console.file.getvalue()
    await app.handle_action("play")
    assert FakeServer.instances[0].handoffs == [("html", "<!doctype html><h1>Acme</h1>")]
    await app.ask("and this?")
    await app.handle_action("play")
    assert FakeEditor.opened == [("python", "print(x)")]


async def test_ctrl_p_without_playground_code(tmp_path, console):
    app = make_app(tmp_path, console, [BASH])
    await app.handle_action("play")
    assert "Ask something first" in console.file.getvalue()
    await app.ask("numpy?")
    await app.handle_action("play")
    assert "no code the playground can open" in console.file.getvalue()
    assert FakeEditor.opened == [] and FakeServer.instances == []


async def test_server_bind_failure_is_reported(tmp_path, console):
    app = make_app(tmp_path, console)

    class Broken(FakeServer):
        def start(self):
            raise OSError("Address in use")

    app._server_factory = Broken
    await app.handle_command("/web")
    assert "Couldn't start the web playground (Address in use)" in console.file.getvalue()
    assert app.web is None and app.opened_urls == []


async def test_new_case_clears_attached_code(tmp_path, console):
    app = make_app(tmp_path, console)
    app.attach_code(CodeAttachment("python", "x"))
    await app.handle_action("new")
    assert app.session.code is None and app.ui.status.code == ""
```

Add to `tests/test_ui.py`:

```python
def test_help_lists_playground(console):
    UI(console).help()
    out = console.file.getvalue()
    assert "⌃P" in out and "/code" in out and "/web" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q tests/test_app_playground.py tests/test_ui.py`
Expected: FAIL with `TypeError: FixelApp.__init__() got an unexpected keyword argument 'editor_factory'`

- [ ] **Step 3: Write the implementation**

`fixel/actions.py`, after `copy_to_clipboard`:

```python
def open_url(url: str) -> None:
    subprocess.run(["open", url], check=False)
```

`fixel/ui.py`:

1. `ACTION_KEYS` gets `("c-p", "play"),` after `("c-s", "save"),`.
2. `HELP` table gets a row after ⌃S: `| ⌃P | open the answer's code in the playground (HTML in the browser, the rest in /code) |`, and the Commands line starts with `` `/code [python|java|js|cpp]` · `/web` · ``.
3. New method after `action_bar`:

```python
    def playground_hint(self, where: str) -> None:
        self.console.print(f"[dim]⌃P opens this code in the {where}[/]")
```

`fixel/app.py`:

1. Imports:

```python
from .parse import first_code_block, primary_fix, runnable_command
from .playground.attachment import CodeAttachment
from .playground.editor import Editor
from .playground.langs import LANGS, resolve
from .playground.runner import RunResult
from .playground.runner import run as run_code
from .playground.scratch import Scratch
from .playground.server import PlaygroundServer
```

2. Constructor keyword parameters after `ocr=...`:

```python
        editor_factory: Callable[..., Editor] = Editor,
        server_factory: Callable[..., PlaygroundServer] = PlaygroundServer,
        open_url: Callable[[str], None] = actions.open_url,
```

and in the body:

```python
        self.scratch = Scratch(cfg.playground_dir)
        self.web: PlaygroundServer | None = None
        self._editor_factory = editor_factory
        self._server_factory = server_factory
        self._open_url = open_url
```

3. `run()`: change `elif text or self.session.tray:` to `elif text or self.session.tray or self.session.code:`, and in `finally:` add after `capture_task.cancel()`:

```python
            if self.web is not None:
                self.web.stop()
```

4. `_sync_status` adds:

```python
        code = self.session.code
        self.ui.status.code = LANGS[code.lang].label if code is not None else ""
```

5. `_looks_stray`: add `and self.session.code is None` after `and not self.session.tray`.
6. `_finish`, after `self.ui.action_bar()`:

```python
        where = self._playground_target(self.session.case.answer)
        if where:
            self.ui.playground_hint("code editor" if where[0].run else "web playground")
```

7. New section before `# ---- keys and commands`:

```python
    # ---- playground

    def _run_code(self, code: str, lang: str, stdin: str) -> Awaitable[RunResult]:
        return run_code(code, lang, stdin=stdin, timeout=self.cfg.playground_timeout)

    def attach_code(self, att: CodeAttachment) -> None:
        """Playground code goes in the tray; Enter asks about it like a screenshot."""
        self.session.attach_code(att)
        self._sync_status()
        self.ui.status.flash_msg(f"📝 {LANGS[att.lang].label} code is in the tray. Press Enter to ask, or type a question.")
        if self._raise_window is not None:
            asyncio.ensure_future(self._raise_window())

    async def open_editor(self, lang: str, code: str | None = None) -> None:
        editor = self._editor_factory(
            self.scratch, lang, self.scratch.load(lang) if code is None else code, self._run_code
        )
        result = await editor.edit()
        if result.attachment is not None:
            self.attach_code(result.attachment)
        else:
            self.ui.info("Back from the editor. /code reopens it.")

    def open_web(self, handoff: tuple[str, str] | None = None) -> None:
        if self.web is None:
            server = self._server_factory(asyncio.get_running_loop(), self.scratch, self._run_code, self.attach_code)
            try:
                server.start()
            except OSError as e:
                self.ui.error(f"Couldn't start the web playground ({e}). /code still works.")
                return
            self.web = server
        if handoff is not None:
            self.web.hand_off(*handoff)
        self._open_url(self.web.url)
        self.ui.info(f"Web playground open in your browser ({self.web.origin}).")

    @staticmethod
    def _playground_target(answer: str):
        """(Lang, code) for the answer's first code block if the playground can open it, else None."""
        block = first_code_block(answer) if answer else None
        lang = resolve(block[0]) if block else None
        return (lang, block[1]) if lang is not None else None

    async def play(self) -> None:
        """⌃P: open the answer's code. HTML goes to the browser, everything else to the terminal editor."""
        if not self.session.case.answer:
            self.ui.warn("Ask something first, then ⌃P opens its code.")
            return
        target = self._playground_target(self.session.case.answer)
        if target is None:
            self.ui.warn("This answer has no code the playground can open.")
            return
        lang, code = target
        if lang.run:
            await self.open_editor(lang.name, code)
        else:
            self.open_web((lang.name, code))
```

   Also add `Awaitable` is already imported from `typing`; keep it.
8. `handle_action`: add a branch:

```python
        elif name == "play":
            await self.play()
```

9. `handle_command`: add before the final `else:`:

```python
        elif command == "/code":
            lang = resolve(arg) if arg else None
            if arg and lang is None:
                self.ui.warn(f"Unknown language '{arg}'. Try: python, java, js, cpp.")
            elif lang is not None and not lang.run:
                self.ui.info("HTML runs in the web playground: /web")
            else:
                await self.open_editor(lang.name if lang else self.scratch.last_lang())
        elif command == "/web":
            self.open_web()
```

`README.md`:

1. Add to the "You screenshot…" table: `| a webpage or design | its fonts, colours, layout and likely libraries, plus one HTML file that recreates it (⌃P opens it live) |`.
2. Add a section after "Use":

```markdown
## Playground

- `/code [python|java|js|cpp]` opens a full-screen editor: **F5** run · **F3** input (stdin) · **F2** language · **⌃A** ask Fixel about the code and its output · **Esc** back.
- `/web` opens the browser playground: live HTML preview, a Run button for the same four languages, and **Ask Fixel**.
- **⌃P** opens an answer's code: HTML in the browser, everything else in `/code`. Nothing runs until you press Run.
- Code runs on your Mac with your permissions (it's a scratchpad, not a sandbox). Runs stop after `playground_timeout` seconds (default 10). Your scratch code lives in `~/.fixel/playground/`.
```

3. Add `| ⌃P | open the answer's code in the playground |` to the key table and `/code`, `/web` to the Commands line.

- [ ] **Step 4: Run the whole suite**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m pytest -q`
Expected: PASS (all existing tests plus the new ones)

- [ ] **Step 5: Try it for real**

Run: `../Dylan-s-Personal-AI/.venv/bin/python -m fixel --here`, then: `/code` → F5 → ⌃A → Enter; `/web` → switch to Java → Run → Ask Fixel → Enter in the terminal; screenshot a webpage → Enter → ⌃P.
Expected: each step behaves as in spec success criteria 1-5.

- [ ] **Step 6: Commit**

```bash
git add fixel/actions.py fixel/app.py fixel/ui.py README.md tests/test_app_playground.py tests/test_ui.py
git commit -m "feat: /code, /web and ⌃P bring the playground into Fixel"
```
