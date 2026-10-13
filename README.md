# Fixel: Dylan's Personal AI

Double-tap **Right Option ⌥**, drag over anything on screen, and Fixel answers in its own Terminal window.

Fixel recognizes what you captured and answers in the format that fits:

| You screenshot… | You get… |
|---|---|
| an error, stack trace, or broken code | the cause, plus the fix as a paste-ready command or diff |
| a math or homework problem | numbered steps and a final `Answer:` |
| an email, doc, or spreadsheet | a short summary plus a ready-to-use draft or formula |
| a confusing app screen | exact click-by-click steps |
| a webpage or design | its fonts, colours, layout and likely libraries, plus one HTML file that recreates it (⌃P opens it live) |

**What sets it apart**

- **Gets smarter with use:** Fixel reads each screenshot on your Mac, finds similar problems you've solved before, and hands those fixes to the AI. Press ⌃G when a fix works so Fixel prefers it next time, and use `/remember <fact>` to teach it about you (your classes, tools, setup).
- **One-key actions:** ⌃Y copies the fix, ⌃R runs the suggested command (only after you type `y`), ⌃S saves a Markdown note.
- **Stack shots:** double-tap again before asking to add more screenshots (error + code + config) to one question.
- **Learn mode:** ⌃L switches to hints and guiding questions instead of answers; `/answer` reveals the full solution.

**Meet Pix.** Fixel's mascot is a little face made from screenshot-selection corners. It focuses in when Fixel starts, blinks and glances around while it's thinking (*Squinting at your screenshot…*), cheers when you press ⌃G, and frowns at errors. Set `animations = false` in `~/.fixel/config.toml` to keep it still.

## Install

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
ln -sf "$PWD/.venv/bin/fixel" /opt/homebrew/bin/fixel   # makes `fixel` work everywhere
```

## Set up (once)

Run this **in Terminal.app**, because macOS grants permissions to the app Fixel runs inside:

```bash
fixel setup
```

It will:
1. Ask for your **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com/settings/keys)) and, optionally, a **Gemini key** ([aistudio.google.com](https://aistudio.google.com/apikey)) or **OpenAI key** ([platform.openai.com](https://platform.openai.com/api-keys)). Keys go into the macOS Keychain, never into a file.
2. Check that the key works and the model exists.
3. Open System Settings for **Input Monitoring** (the hotkey) and **Screen Recording** (screenshots). Switch Terminal on in both, then quit and reopen Terminal.

## Use

```bash
fixel           # opens Fixel in its own Terminal window
fixel --here    # runs in the current terminal instead
```

| Key | Does |
|---|---|
| ⌥⌥ (Right Option twice) | screenshot a region into the tray |
| Enter | ask (type a question first, or just press Enter) |
| ⌃T | think harder: re-answer the last question with deep thinking |
| ⌃Y / ⌃R / ⌃S | copy fix / run command / save note |
| ⌃L | learn mode |
| ⌃F | attach the tray to the current case instead of starting a new one |
| ⌃G | that worked: mark this fix as proven |
| ⌃O | open the past case Fixel used |
| ⌃P | open the answer's code in the playground |
| ⌃N | new case |
| ⌃C | stop an answer that's streaming |

Commands: `/code [python|java|js|cpp]`, `/web`, `/model sonnet|opus|gemini|gpt`, `/api [provider] [key]`, `/learn [on|off]`, `/answer`, `/remember <fact>`, `/memory`, `/forget <n>`, `/cases <words>`, `/open <n>`, `/help`, `/exit` (or `/quit`).

## Playground

- `/code [python|java|js|cpp]` opens a full-screen editor: **F5** run · **F3** input (stdin) · **F2** language · **⌃A** ask Fixel about the code and its output · **Esc** back.
- `/web` opens the browser playground: live HTML preview, a Run button for the same four languages, and **Ask Fixel**.
- **⌃P** opens an answer's code: HTML in the browser, everything else in `/code`. Nothing runs until you press Run.
- Code runs on your Mac with your permissions (it's a scratchpad, not a sandbox). Runs stop after `playground_timeout` seconds (default 10). Your scratch code lives in `~/.fixel/playground/`.

## Customize

- `~/.fixel/config.toml` sets the default model, model IDs, the backup Gemini models used when Google is busy or slow (`gemini_fallbacks`, `slow_model_seconds`), the double-tap speed, the notes folder, and how closely a past problem must match before Fixel reuses it (`recall_threshold`).
- `fixel/prompts.py` holds Fixel's personality and answer formats. Edit it to change how Fixel talks.

## Privacy & cost

Screenshots go only to the model provider you've selected (Anthropic, Google, or OpenAI). The case file, notes, and screenshots stay in `~/.fixel` and `~/Fixel Notes`. Claude bills per use, typically a fraction of a cent to a few cents per question; Opus costs more than Sonnet. Gemini has a free tier with rate limits.

## Develop

```bash
.venv/bin/pytest -q
```
