---
name: fixel
description: Use the Fixel app (a macOS screenshot-to-AI terminal tool) from Claude Code to see the user's screen, check their Canvas homework, and look up fixes they've used before. Use this whenever the user wants you to look at something on their screen ("look at my screen", "screenshot this", "see this error", "what's wrong with this window", "can you see what I'm looking at"), asks about schoolwork ("what homework is due", "what should I work on tonight", "what's due this week on Canvas", "plan my assignments"), or asks whether they've hit a problem before ("have I fixed this before", "what did I do last time I got this error"). Prefer it over asking the user to describe their screen or paste an error by hand.
---

# Fixel

Fixel is a macOS terminal app. It also gives Claude Code three one-shot commands, which this skill uses. All three print data to stdout and progress or problems to stderr, so `--json` output always parses.

Check that it's installed first: `command -v fixel`. If it isn't, point the user to https://github.com/Kiddo4993/Dylan-s-Personal-AI#install and stop, rather than guessing at another tool.

## See the user's screen: `fixel shot`

1. Tell the user to get ready first ("I'll open a screenshot selector. Drag over what you want me to see."), because the command waits for them to drag.
2. Run `fixel shot` (or `fixel shot --out <path>` to choose the file). It shows the macOS crosshair, and the user drags over the region.
3. stdout is the PNG's absolute path. Read that file to look at it, then answer what they asked about it.

- **Exit code 1** means they pressed Esc. Say so and don't retry by yourself, since they may have changed their mind.
- **A blank image or just the desktop wallpaper** means the terminal app lacks Screen Recording permission. Tell them to turn it on in System Settings → Privacy & Security → Screen & System Audio Recording for the app Claude Code runs in, then restart that app.

For several things at once (an error plus the code behind it), run it once per region.

## Homework: `fixel canvas --json`

This syncs Canvas the way Fixel's `/canvas` does, including the AI plan and the Notion database if those are set up, and prints a JSON list, soonest first:

```json
[{"id": "assignment-77", "title": "Essay 2", "course": "ENGL 101", "due": "2026-11-03T23:59:00-05:00",
  "url": "https://…", "points": 20, "submitted": false,
  "priority": "High", "hours": 3.0, "start_by": "2026-11-01", "tip": "Outline before you draft."}]
```

- Lead with what to do next: unsubmitted work, sorted by `start_by` and then `due`, with priority and hours. Give dates in plain words ("Thursday 11:59pm"). Point out anything already late (a past `due` with `submitted: false`).
- The plan fields come from the user's chosen AI model and may be `null` if no model key is set. Present them as suggestions, and don't invent plans for missing ones.
- **Exit code 1** with "isn't connected" means Canvas isn't set up. Tell the user to open `fixel` and run `/canvas setup`. Setup asks for their Canvas token in a hidden prompt there, so never ask them to paste a token or calendar-feed link into this chat: both are passwords, and chat logs aren't the Keychain.

## Past fixes: `fixel cases <words> --json`

Fixel remembers every problem it has answered. Search with the distinctive words of the problem, such as the exact error name or the package, not a whole sentence: `fixel cases ModuleNotFoundError pandas --json`. With no words it lists the 10 most recent cases.

Each result has `problem`, `question`, `answer`, `date`, `mode` and `worked`. `worked: true` means the user confirmed that fix worked, so offer that one first and say when it was from ("you fixed this on Oct 27 with …"). These are the user's own notes, so quote the part that matters rather than pasting whole answers back.
