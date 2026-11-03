# Changelog

## 0.2.0 (2026-11-03)

The first public release.

**Screenshots and answers**
- Double-tap Right Option anywhere, drag over what you're stuck on, and read the answer in your terminal.
- Each screenshot is sorted into a mode (error, math, writing, email, webpage, …) and answered in the format that fits: a command to run, numbered steps, essay feedback, a draft reply, or an HTML file that recreates the page.
- Fixel remembers what worked: when a solved error comes back, the fix that worked last time goes into the prompt.
- Learn mode gives hints instead of answers.
- Bring your own Claude, Gemini or OpenAI key, kept in the macOS Keychain.

**Playground**
- `/ide [language]` opens an IDE for Python, Java, JavaScript or C++ in its own Terminal window. Find, go to line, completion and auto-indent are built in.
- `/ide here` (or `/code`) keeps it in the current window. `/ide web` opens a Monaco editor in the browser.
- Send your code back to Fixel to ask about it.

**Canvas and Notion**
- `/canvas` lists what's due, with a suggested priority, hours, start-by date and tip for each assignment. It works with a Canvas API token or a calendar feed.
- It can keep a Notion database in sync without overwriting the Status you set.

**Claude Code**
- Fixel ships as a Claude Code plugin: `/plugin install fixel --marketplace Kiddo4993/fixel`.
- New one-shot commands for scripts and for Claude: `fixel shot`, `fixel canvas --json`, `fixel cases <words> --json`.
