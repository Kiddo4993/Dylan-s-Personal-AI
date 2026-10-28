# Contributing to Fixel

Thanks for helping. Fixel is small on purpose, and these rules keep it that way.

## Get set up

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

The tests never touch the network or need an API key. Models, Canvas, Notion, the editor and the playground server all have fakes. Please keep it that way: a new feature that talks to a service takes an injectable `fetch` (see `fixel/canvas/http.py`) or a factory (see `FixelApp.__init__`).

## House rules

- **One command registry.** Every slash command is a row in `COMMANDS` in `fixel/commands.py`. That row drives the `/` menu, `/help`, `/instruction` and the Ctrl shortcuts. Never add a second list.
- **Secrets live in the Keychain.** Use `get_api_key` and `set_api_key` from `fixel/config.py`. Never write a key or token to a file, a log, or a message. Fixel screenshots the screen, so hide pasted secrets (`is_password=True`).
- **Plain-English messages.** Every error is one sentence that says what to do next ("Canvas rejected your access token. Make a new one…, then run /canvas setup.").
- **Nothing runs without asking.** Code and shell commands from an answer only run when the user presses Run or types `y`.
- **Tests first.** Each change comes with tests next to the ones it touches. Keep `pytest -q` green.

## Ideas we'd love help with

- Windows and Linux support for the hotkey, capture and OCR layers
- More playground languages (Rust, Go)
- Google Classroom next to `/canvas`

Open an issue first for anything big, so we can agree on the shape before you build it.
