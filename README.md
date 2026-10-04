# Fixel: Dylan's Personal AI

Double-tap **Right Option ⌥**, drag over anything on screen, and Fixel answers in its own Terminal window.

Fixel recognizes what you captured and answers in the format that fits:

| You screenshot… | You get… |
|---|---|
| an error, stack trace, or broken code | the cause, plus the fix as a paste-ready command or diff |
| a math or homework problem | numbered steps and a final `Answer:` |
| an email, doc, or spreadsheet | a short summary plus a ready-to-use draft or formula |
| a confusing app screen | exact click-by-click steps |

**What sets it apart**

- **Gets smarter with use:** Fixel reads each screenshot on your Mac, finds similar problems you've solved before, and hands those fixes to the AI. Type `/worked` when a fix works so Fixel prefers it next time, and use `/remember <fact>` to teach it about you (your classes, tools, setup).
- **One-step actions:** `/copy` copies the fix, `/run` runs the suggested command (only after you type `y`), `/save` saves a Markdown note. Type `/` to see every command.
- **Stack shots:** double-tap again before asking to add more screenshots (error + code + config) to one question.
- **Learn mode:** `/learn` switches to hints and guiding questions instead of answers; `/answer` reveals the full solution.

**Meet Pix.** Fixel's mascot is a little face made from screenshot-selection corners. It focuses in when Fixel starts, blinks and glances around while it's thinking (*Squinting at your screenshot…*), cheers when you type `/worked`, and frowns at errors. Set `animations = false` in `~/.fixel/config.toml` to keep it still.

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
1. Ask for your **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com/settings/keys)) and, optionally, a **Gemini key** ([aistudio.google.com](https://aistudio.google.com/apikey)). Keys go into the macOS Keychain, never into a file.
2. Check that the key works and the model exists.
3. Open System Settings for **Input Monitoring** (the hotkey) and **Screen Recording** (screenshots). Switch Terminal on in both, then quit and reopen Terminal.

## Use

```bash
fixel           # opens Fixel in its own Terminal window
fixel --here    # runs in the current terminal instead
```

| Do this | To |
|---|---|
| ⌥⌥ (Right Option twice) | screenshot a region into the tray |
| Enter | ask (type a question first, or just press Enter) |
| `/` | see every command in a menu |
| `/deeper` | re-answer the last question with deep thinking |
| `/copy` · `/run` · `/save` | copy the fix · run its command (asks first) · save a note |
| `/worked` | mark a fix as proven, so Fixel prefers it next time |
| `/learn [on\|off]` · `/answer` | learn mode: hints instead of answers · show the full solution |
| `/follow` | add the tray to this case instead of starting a new one |
| `/remember <fact>` · `/memory` · `/forget <n>` | teach Fixel about you · list · remove |
| `/cases <words>` · `/open [n]` | search past cases · show one |
| `/new` · `/model sonnet\|opus\|gemini` · `/help` · `/exit` | new case · switch model · help · close Fixel |
| Ctrl+C | stop an answer that's streaming |

Prefer keys? Every one-step command also has a Ctrl shortcut (Ctrl+T `/deeper`, Ctrl+G `/worked`, Ctrl+Y `/copy`, Ctrl+R `/run`, Ctrl+S `/save`, Ctrl+N `/new`, Ctrl+F `/follow`, Ctrl+L `/learn`, Ctrl+O `/open`), listed at the bottom of `/help`.

## Customize

- `~/.fixel/config.toml` sets the default model, model IDs, the backup Gemini models used when Google is busy or slow (`gemini_fallbacks`, `slow_model_seconds`), the double-tap speed, the notes folder, and how closely a past problem must match before Fixel reuses it (`recall_threshold`).
- `fixel/prompts.py` holds Fixel's personality and answer formats. Edit it to change how Fixel talks.

## Privacy & cost

Screenshots go only to the model provider you've selected (Anthropic or Google). The case file, notes, and screenshots stay in `~/.fixel` and `~/Fixel Notes`. Claude bills per use, typically a fraction of a cent to a few cents per question; Opus costs more than Sonnet. Gemini has a free tier with rate limits.

## Develop

```bash
.venv/bin/pytest -q
```
