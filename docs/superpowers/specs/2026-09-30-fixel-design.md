# Fixel — Design Spec

**Date:** 2026-09-30
**Status:** Approved in brainstorming, pending written-spec review

## 1. Purpose

Fixel is a personal macOS AI assistant for work and problem solving. Double-tap **Right Option** anywhere, drag over part of the screen, and Fixel answers in its own dedicated Terminal window.

It is a general helper across four domains: code/errors, homework, work documents/apps, and anything else on screen. It differs from generic chat LLMs by:

- **Auto-mode detection** — answers are shaped by what the screenshot *is* (error → cause + pasteable fix; math → worked steps + boxed answer; doc → summary + draft; UI → numbered clicks).
- **Case file memory** — a local, searchable history of every problem and solution, surfaced when a similar problem reappears.
- **One-key actions** — copy the fix, run a command (with confirmation), or save a note without selecting text.
- **Stack shots** — multiple screenshots per question via a tray.
- **Learn mode** — hints and guiding questions instead of answers, until `/answer`.

Fixel does not train a model. Its quality comes from a frontier model (Claude by default) plus the specialization layer above.

### Success criteria

1. From any app, double-tapping Right Option brings the Fixel window forward and opens the region-selection crosshair within ~300 ms.
2. Pressing Enter on a captured tray streams an answer with a correct mode badge.
3. ⌃Y copies the primary fix/answer, ⌃R runs a suggested command only after explicit `y`, ⌃S writes a Markdown note.
4. A repeat of a previously-solved problem shows a "Seen before" pointer.
5. Missing permissions or keys produce an actionable message — never a silent failure.

## 2. Constraints

- macOS only (tested on Darwin 25). Python ≥ 3.11.
- Architecture A: a single process running inside a dedicated Terminal window; it inherits Terminal's Accessibility and Screen Recording permissions. Closing the window quits Fixel.
- Default model: `claude-sonnet-5-5`. `/model` switches between `sonnet`, `opus` (`claude-opus-5-5`), and `gemini` (model id configurable in `~/.fixel/config.toml`; verify the current id at implementation time).
- API keys are stored in the macOS Keychain (via `keyring`) and never written to plain files. The `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` env vars override Keychain values when set.
- Screenshots are sent only to the selected model provider. Everything else stays local.

## 3. Architecture

```
fixel/
  __main__.py      # `fixel` / `fixel setup` entry points
  app.py           # main asyncio loop; wires components together
  hotkey.py        # Right-Option double-tap detector (pynput listener thread)
  capture.py       # `screencapture -i` wrapper → PNG bytes | None
  permissions.py   # Accessibility + Screen Recording preflight checks
  brain/
    base.py        # Provider protocol: stream(messages, system) -> AsyncIterator[str]
    claude.py      # Anthropic SDK impl (streaming, prompt caching on system prompt)
    gemini.py      # google-genai impl
    fake.py        # deterministic provider for tests
  prompts.py       # system prompt: persona, mode rules, header format, learn mode
  parse.py         # header parsing (MODE/KEY), primary-fix + command extraction
  casefile.py      # SQLite + FTS5 store at ~/.fixel/casefile.db
  actions.py       # clipboard (pbcopy), confirmed command run, note export
  config.py        # ~/.fixel/config.toml + keyring access
  ui.py            # rich rendering + prompt_toolkit session & key bindings
tests/
```

Each unit has one job. `ui.py` is the only module that touches the terminal, so replacing it is all that architecture B (background service + viewer) would require later.

### Threading model

`pynput` runs its listener on its own thread. On a detected double-tap it calls `loop.call_soon_threadsafe(queue.put_nowait, HotkeyEvent)`. The asyncio main loop runs the `prompt_toolkit` prompt under `patch_stdout()` and concurrently consumes the hotkey queue. A hotkey event:

1. activates the Fixel Terminal window (`osascript` activating Terminal and selecting the window by its title, `Fixel`),
2. runs `screencapture -i -x <tmpfile>` in a worker thread,
3. appends the PNG to the tray and refreshes the status line.

### Double-tap detection

Right Option (`Key.alt_r`) press→release counts as a tap only if no other key was pressed in between, which prevents Option-chords such as ⌥→ from triggering. Two taps within **400 ms** trigger the event. A third tap within the window does not re-trigger. Detection is a pure function over `(key, event, timestamp)` so it can be unit-tested.

## 4. Model protocol

A single model call per turn. The system prompt instructs the model to begin every reply with:

```
MODE: <error|math|doc|ui|general>
KEY: <one line: the most searchable text in the screenshot, e.g. the exact error message>
---
```

`parse.py` strips this header. Missing or malformed header → mode `general`, key empty, and the full text is still shown.

Mode-specific answer formats (defined in `prompts.py`):

| Mode | Format |
|---|---|
| error | **Cause** (1–2 sentences) → **Fix** as a fenced `bash` or diff block → optional *Why* |
| math | Numbered steps → final answer on its own line prefixed `Answer:` |
| doc | 2–4 bullet summary → **Draft** (reply/formula/rewrite) in a fenced block |
| ui | Numbered click-path steps |
| general | Direct answer; short |

**Primary fix** (for ⌃Y): the first fenced code block. If there is none, the `Answer:` line. Otherwise, the whole answer body.
**Runnable command** (for ⌃R): the first fenced block tagged `bash`/`sh`/`zsh` only. If there is none, ⌃R shows "no command to run".

**Learn mode** swaps in a system-prompt addendum: give one hint or guiding question per turn and never the final answer until the user sends `/answer`.

The Claude provider marks the system prompt with `cache_control` so repeated turns reuse the cached prefix.

## 5. Session & tray semantics

- **Tray:** up to 5 screenshots waiting to be sent. Each double-tap adds one; Esc during selection adds nothing.
- **Enter:** sends the tray plus typed text (empty text → "Figure this out."). Clears the tray.
- **Case:** one conversation (message history + mode + key). A tray sent *after* an answer starts a **new case** unless ⌃F (follow-up) was toggled on for that tray. Typed text with an empty tray is always a follow-up in the current case.
- **⌃N:** new case, clears tray and history.

## 6. Case file

SQLite at `~/.fixel/casefile.db`:

```
cases(id, created_at, mode, key, question, answer, shot_paths JSON)
cases_fts  -- FTS5 over (key, question, answer), content='cases'
```

- Saved after each completed answer; follow-ups update the same row.
- Screenshots are persisted to `~/.fixel/shots/<case_id>-<n>.png`.
- **Recall:** after the header is parsed and the key is non-empty, run an FTS5 `MATCH` on the key, excluding the current case. The top hit is shown only if its `bm25()` score is ≤ `recall_threshold` (default `-1.0`; lower is a stronger match in FTS5; tunable in `config.toml`). It is shown as `📁 Seen before: <date> — <key>` (⌃O shows that case's answer).
- `/cases <query>` lists the top 10 matches.
- On a DB error, memory is disabled for the session with a yellow warning. Answers still work.

## 7. Actions & commands

| Key / command | Behavior |
|---|---|
| ⌃Y | Copy primary fix via `pbcopy`; confirm with a one-line toast |
| ⌃R | Show the extracted command and require the user to type `y`; then run with `subprocess` (shell, cwd = `$HOME`, 60 s timeout) and print stdout/stderr and the exit code. Never auto-runs. |
| ⌃S | Write `~/Fixel Notes/YYYY-MM-DD-<slug>.md` with question, answer, and linked screenshot copies |
| ⌃L | Toggle learn mode (shown in the header bar) |
| ⌃F | Toggle follow-up for the current tray |
| ⌃O | Show the "Seen before" case |
| ⌃N | New case |
| `/model sonnet\|opus\|gemini` | Switch provider/model |
| `/answer` | In learn mode, reveal the full solution |
| `/cases <q>` | Search the case file |
| `/help` | List keys and commands |

## 8. Error handling

| Condition | Behavior |
|---|---|
| Accessibility not granted (`AXIsProcessTrusted()` false via `ApplicationServices`) | Red banner at startup with the System Settings path; the hotkey is marked inactive |
| Screen Recording not granted (`CGPreflightScreenCaptureAccess()` false) | Red banner at startup; captures are refused rather than sending wallpaper-only images |
| Esc during selection | No-op |
| Missing or invalid API key | "Run `fixel setup`" message; the app stays alive |
| Rate limit / network / 5xx | 2 retries with backoff; on final failure the tray is restored so Enter retries |
| Missing header | Treated as `general` |
| Case file DB failure | Memory disabled for the session, with a warning |

`fixel setup`: prompts for the Anthropic and (optional) Gemini keys into Keychain, runs both permission checks, and prints exactly which toggles to enable.

## 9. Testing

- **Unit (pytest, offline):** double-tap detector (timing, chord rejection, triple tap), header parsing (valid, missing, malformed), primary-fix and command extraction, case file save/recall/search on a temp DB, tray/case state transitions, and the app loop driven by `brain/fake.py`.
- **Live verification:** launch with the `run` skill, trigger a real capture of an on-screen error, confirm the streamed answer and badge, then exercise ⌃Y and ⌃S.

## 10. Out of scope (v1)

Voice, menu-bar icon, auto-start at login, background-service architecture, Windows/Linux, OCR-only offline mode, and feeding past cases into the model prompt (recall is display-only in v1).
