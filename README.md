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

- **Case file:** every solved problem is saved on your Mac. Hit the same error again and Fixel says *"Seen before: Sep 12"* (⌃O opens it).
- **One-key actions:** ⌃Y copies the fix, ⌃R runs the suggested command (only after you type `y`), ⌃S saves a Markdown note.
- **Stack shots:** double-tap again before asking to add more screenshots (error + code + config) to one question.
- **Learn mode:** ⌃L switches to hints and guiding questions instead of answers; `/answer` reveals the full solution.

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

| Key | Does |
|---|---|
| ⌥⌥ (Right Option twice) | screenshot a region into the tray |
| Enter | ask (type a question first, or just press Enter) |
| ⌃T | think harder: re-answer the last question with deep thinking |
| ⌃Y / ⌃R / ⌃S | copy fix / run command / save note |
| ⌃L | learn mode |
| ⌃F | attach the tray to the current case instead of starting a new one |
| ⌃O | open the "Seen before" case |
| ⌃N | new case |
| ⌃C | stop an answer that's streaming |

Commands: `/model sonnet|opus|gemini`, `/answer`, `/cases <words>`, `/open <n>`, `/help`, `/quit`.

## Customize

- `~/.fixel/config.toml` sets the default model, model IDs, the backup Gemini models used when Google is busy (`gemini_fallbacks`), the double-tap speed, the notes folder, and how strict "Seen before" matching is.
- `fixel/prompts.py` holds Fixel's personality and answer formats. Edit it to change how Fixel talks.

## Privacy & cost

Screenshots go only to the model provider you've selected (Anthropic or Google). The case file, notes, and screenshots stay in `~/.fixel` and `~/Fixel Notes`. Claude bills per use, typically a fraction of a cent to a few cents per question; Opus costs more than Sonnet. Gemini has a free tier with rate limits.

## Develop

```bash
.venv/bin/pytest -q
```
