# Fixel Playground and Web Mode: Design Spec

**Date:** 2026-10-12
**Status:** Approved 2026-10-12. Plan: `docs/superpowers/plans/2026-10-12-fixel-playground.md`
**Builds on:** `docs/superpowers/specs/2026-09-30-fixel-design.md`

## 1. Purpose

Two features that make Fixel useful for code you write, not just problems you screenshot:

1. **Playground.** Write, paste, or hand off code and run it without leaving Fixel. It has two front-ends sharing one engine: a terminal editor (`/code`) and a live web playground in the browser (`/web`).
2. **Web mode.** Screenshot a webpage and Fixel explains its front-end design (type, colours, layout, spacing), names the libraries it probably uses, and writes one self-contained HTML file that recreates it. ⌃P opens that file in the web playground.

It serves three uses equally: trying Fixel's fixes, practising coding (AP CSA, CCC), and cloning websites.

### Agreed choices

| Topic | Decision |
|---|---|
| Front-ends | Both: terminal editor and web playground |
| Languages | Python, Java, JavaScript (Node), C++; HTML/CSS/JS live preview on the web side |
| Web-mode code | One self-contained HTML file |
| AI in the playground | "Ask Fixel" sends code + run output as a normal case; Fixel does not edit the editor |
| Architecture | Approach A: one runner, two front-ends |

### Success criteria

1. `/code java` opens a full-screen editor; F5 compiles and runs `Main.java` and shows output within ~2 s for a hello-world.
2. `/web` opens a browser tab; typing HTML updates the preview within ~0.5 s; Python/Java/JS/C++ run from the page.
3. "Ask Fixel" (either front-end) puts the code in Fixel's tray; Enter asks, and memory, ⌃G, ⌃S and learn mode all work as for a screenshot.
4. Screenshotting a webpage with no question gives a `WEB` answer with Design, Libraries and one `html` block; ⌃P opens it in the web playground and it renders close to the screenshot.
5. Nothing Fixel writes is ever run automatically: ⌃P only opens code; the user presses Run.

## 2. Constraints

- **No new Python dependencies.** The editor uses prompt_toolkit (already required); the server uses the stdlib `http.server`; syntax colours come from Pygments (a prompt_toolkit dependency).
- Runtimes are whatever is on `PATH` (`python3`, `java`, `node`, `g++`). A missing runtime gives a clear message and doesn't break anything else.
- The web server binds **127.0.0.1 only** and lives only as long as Fixel.
- Code runs as the user with the user's permissions, the same trust level as ⌃R today. This is a scratchpad, not a sandbox, and the README says so.
- Changing `BASE_SYSTEM` breaks the prompt cache once; after that it is byte-stable again.

## 3. Components

```
fixel/playground/
  __init__.py
  langs.py       # Lang table: name, aliases, file name, build/run commands, Pygments lexer
  runner.py      # async run(code, lang, stdin="") -> RunResult(exit_code, output, seconds)
  scratch.py     # load/save scratch files in ~/.fixel/playground/
  attachment.py  # CodeAttachment(lang, code, output, exit_code) + to_prompt_text()
  editor.py      # /code: full-screen prompt_toolkit Application
  server.py      # /web: ThreadingHTTPServer + token + JSON API
  web/index.html # the browser playground, one file
```

| Unit | Does | Depends on |
|---|---|---|
| `langs` | Pure data. Java: `java Main.java` (JDK 11+ single-file launch). C++: `g++ -std=c++17 -O2 main.cpp -o main` then `./main`. Python: `python3 main.py`. JS: `node main.js`. | nothing |
| `runner` | Writes code to a fresh temp dir, runs build then run steps with `start_new_session=True`, kills the process group on timeout or cancel, caps output at 64 KB. | `langs` |
| `scratch` | Keeps the last code per language (`main.py`, `Main.java`, `main.js`, `main.cpp`, `index.html`) and the last-used language. Starter templates when empty. | `langs` |
| `attachment` | The one shape both front-ends hand to the app. | nothing |
| `editor` | Terminal UI. Returns an `EditorResult(attachment: CodeAttachment \| None)` when it closes. | `runner`, `scratch`, `langs` |
| `server` | Serves the page and API. Asks go to an `on_ask(CodeAttachment)` callback. | `runner`, `scratch`, `attachment` |

Changes to existing files:

- `parse.py`: add `"web"` to `MODES`; add `first_code_block(body) -> tuple[str, str] | None` (language, code).
- `prompts.py`: add web to "Choosing MODE" and "Answer format by MODE".
- `session.py`: `attach_code(att)`, `tray_code`; `build_user_turn` adds the attachment text and a default question.
- `ui.py`: ⌃P in `ACTION_KEYS` as `"play"`; `web` badge (`bold white on magenta`); toolbar shows a code attachment; help text.
- `app.py`: `/code`, `/web`, the `play` action, `attach_code()`, server lifecycle (stopped in `run()`'s `finally`).
- `config.py`: `playground_timeout = 10` (seconds) setting and a `playground_dir` property (`~/.fixel/playground`).

## 4. Behaviour

### 4.1 One way in: the code attachment

Both front-ends end the same way: a `CodeAttachment` lands in the session next to the screenshot tray, and the toolbar says `📝 python code in tray · ⏎ ask`. The user can add screenshots, type a question, or just press Enter. This keeps one ask path (`session.build_user_turn` → memory recall → stream), so nothing about memory, learn mode, ⌃T or ⌃G needs to change, and a browser click never interrupts the terminal mid-prompt.

`to_prompt_text()` produces:

````
[Code from Fixel playground · python]
```python
...code...
```
[Run output · exit 1]
...output, last 4 KB...
````

Default question when none is typed: `Why doesn't this work?` if the last run failed, otherwise `Review this code.` One attachment at a time; a new one replaces the old.

### 4.2 Terminal editor (`/code [lang]`)

- `/code` reopens the last-used language; `/code java` (aliases: `py`, `js`, `node`, `c++`, `cpp`) switches. HTML isn't offered here: `/code html` says "HTML runs in the web playground: /web".
- Layout: code pane with line numbers and Pygments colours (top), output pane (bottom, ~8 lines, scrollable), status bar: `java · F5 run · F3 input · F2 language · ⌃A ask Fixel · Esc back`.
- **F5** saves the scratch file and runs; the output pane shows `Running…` then the result and `exit 0 · 0.4s`. **⌃C** while running stops it.
- **F3** toggles an Input pane; its text is passed as stdin (for `Scanner`/`input()`/CCC problems).
- **⌃A** closes the editor and attaches the code, plus the last run's output if the code hasn't changed since. **Esc** closes without attaching. Closing saves the scratch file only if the code was edited or run.
- The editor runs in the same event loop as Fixel (`Application.run_async()`), so no threads.

### 4.3 Web playground (`/web`)

- The first `/web` starts the server on a random free port with a random 32-byte token and runs `open http://127.0.0.1:<port>/#<token>`. Later `/web` calls reopen the same server. The token sits in the URL fragment, so it is never sent in requests the browser makes by itself.
- Page: editor on the left (Monaco 0.52.2 from cdnjs; its loader, core script and stylesheet carry Subresource Integrity hashes; falls back to a `<textarea>` if offline). Type: Silkscreen (wordmark), Schibsted Grotesk (UI), Fragment Mono (code). The result pane is drawn as a screenshot selection: violet corner brackets and a live `width × height` readout, right pane switches between **Preview** (HTML) and **Output + Input** (other languages). Language picker, **Run** (⌘↵), **Ask Fixel**, **Download**. Light/dark follows the system.
- HTML preview: `<iframe sandbox="allow-scripts" srcdoc=…>`, updated 300 ms after typing stops. No `allow-same-origin`, so the preview runs as an opaque origin and can't read the token or call the API.
- API (JSON, all require `X-Fixel-Token`):

| Endpoint | Body | Returns |
|---|---|---|
| `GET /api/state` | | `{lang, code, langs}`: the pending ⌃P handoff (once), else last scratch |
| `GET /api/scratch?lang=` | | `{lang, code}` for the language picker |
| `POST /api/run` | `{lang, code, stdin}` | `{exit_code, output, seconds}` |
| `POST /api/ask` | `{lang, code, output, exit_code}` | `{ok: true}`; Fixel raises its window |
| `POST /api/save` | `{lang, code}` | `{ok: true}` |

- **Request checks:** wrong or missing token → 403; `Origin` present and not `http://127.0.0.1:<port>` → 403; body over 1 MB → 413; unknown language → 400.
- Threading: the server runs in a daemon thread. `/api/run` hands the run to Fixel's loop with `asyncio.run_coroutine_threadsafe(runner.run(...), loop)` and waits for it; `/api/ask` uses `loop.call_soon_threadsafe(app.attach_code, att)`.

### 4.4 ⌃P: open the answer's code

`first_code_block(case.answer)` picks the first fenced block:

- `html`/`htm` (or a block starting with `<!doctype`/`<html`): load into the web playground (starting the server if needed) and open the browser.
- `python`/`py`, `java`, `javascript`/`js`, `cpp`/`c++`: open the terminal editor with that code in the matching language. The scratch file is replaced only when the user edits or runs, so Esc right away leaves the old scratch alone.
- `diff`, `bash`, other or none: `This answer has no code the playground can open.` (Shell commands stay with ⌃R.)

## 5. Web mode (screenshot a webpage)

### 5.1 Choosing MODE (added to the prompt)

- `web`: a webpage, web app, landing page, or design mockup where the user wants to know how it's designed or built: fonts, colours, layout, libraries, or code to recreate it. With no question, a marketing page, portfolio, or landing page counts as `web`.
- `ui` stays for "where do I click / how do I do X in this app". When unsure between the two, a question about doing something means `ui`; a question about how it looks or is made means `web`.

### 5.2 Answer format (added to the prompt)

```
web:
**Design**
- Type: font families (closest match, plus a Google Fonts option if it isn't one), size/weight scale
- Colours: 4-8 hex values, each with its role (background, text, accent, border...)
- Layout: page structure (grid/flex, columns, max width), spacing scale, corner radius, shadows
- Components: the notable pieces (nav, hero, cards, buttons) in one line each
**Libraries** (best guess from pixels):
1-4 bullets: `Name (likely|possible): the visual tell`. If nothing stands out, say it looks hand-written CSS.
Finish with: Confirm with View Source or a tech-detection extension.
**Code:** exactly ONE ```html block: a complete document with inline <style>, Google Fonts <link> allowed,
no other external files, no hotlinked images (use CSS gradients or inline SVG as placeholders),
text copied from the screenshot, responsive down to 375 px.
```

- ⌃Y copies the HTML (first fence, already how `primary_fix` works). ⌃S saves a note. ⌃R reports there's no shell command.
- Learn mode: the existing addendum applies (one hint, e.g. "look at the spacing between cards: what scale is it on?").
- The badge is `WEB`. The case file stores `web` as the mode so recall finds past clones.

## 6. Errors and testing

### 6.1 Errors

| Situation | What the user sees |
|---|---|
| Runtime missing (`shutil.which` fails) | `Java isn't installed. Install a JDK: brew install openjdk` (per-language hint in `langs`) |
| Compile error | Shown as output with the non-zero exit code, like any failed run |
| Timeout | Output so far + `[stopped after 10s]`, process group killed |
| Output over 64 KB | Truncated with `[output truncated]` |
| Server can't bind | `Couldn't start the web playground (<reason>). /code still works.` |
| Browser offline | CodeMirror fails to load → plain textarea, everything else works |
| ⌃P with no answer | `Ask something first, then ⌃P opens its code.` |

### 6.2 Tests (pytest, no network)

- `test_langs.py`: all four languages have commands, file names, lexers and install hints; aliases resolve.
- `test_runner.py`: Python hello world; non-zero exit; stdin passed through; timeout kills a `while True` loop and its children; output cap; missing runtime (monkeypatched `which`). Java and C++ cases are skipped when `java`/`g++` aren't installed.
- `test_scratch.py`: save/load round trip, starter templates, last-used language.
- `test_attachment.py`: prompt text format, output tail limit.
- `test_session.py` (extend): attach/replace/clear code; default questions; turn text includes attachment.
- `test_parse.py` (extend): `web` mode accepted; `first_code_block` for html, python, diff, none.
- `test_prompts.py` (extend): web is listed in MODE choice and format.
- `test_editor.py`: drive the Application with `create_pipe_input()` + `DummyOutput()` and a fake runner: F5 shows output, ⌃A returns an attachment, Esc returns none.
- `test_server.py`: start on port 0 with a fake runner; 403 without token and with a foreign Origin; 413 on a large body; run returns output; ask calls `on_ask`; state returns a ⌃P handoff.
- `test_app.py` (extend): `/code`, `/web`, ⌃P routing (html → server, python → editor, diff → warning) with fakes; server stopped on exit.

## 7. Out of scope

Multi-file projects, installing packages (pip/npm), a debugger, Fixel editing code in place, sharing the playground online, and reading real page source to confirm libraries (a possible follow-up: capture the page URL and fetch its HTML).
