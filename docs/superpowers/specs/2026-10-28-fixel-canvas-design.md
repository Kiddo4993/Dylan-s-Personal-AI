# Fixel Canvas → AI → Notion: Design Spec

**Date:** 2026-10-28
**Status:** Built 2026-10-28 on `feature/canvas-notion` (roadmap item 1, agreed 2026-10-13)
**Builds on:** `docs/superpowers/specs/2026-09-30-fixel-design.md`

## 1. Purpose

`/canvas` shows your upcoming Canvas work in Fixel. Your selected AI model adds a priority, an hours estimate, a start-by date and one tip to each assignment. It can also keep a Notion database in sync. Everything runs on the user's own tokens: Canvas, Notion, and whichever model key Fixel already uses.

### Agreed choices

| Topic | Decision |
|---|---|
| Canvas access | Personal access token (preferred); calendar-feed `.ics` link as fallback |
| AI fields | priority (High/Medium/Low), hours, start-by, tip. Made once per assignment by the current `/model` |
| Notion | Optional. Fixel creates the database itself inside a page the user shares with their integration |
| Re-sync | Canvas facts follow Canvas; AI fields written once; Status set at creation, never again; deleted rows stay deleted |
| Secrets | Keychain only (`fixel` service: `canvas`, `notion`), or `CANVAS_TOKEN` / `NOTION_TOKEN` env vars |

## 2. Constraints

- **No new Python dependencies.** Network calls use stdlib `urllib` through one injectable `Fetch` function, so tests never touch the network.
- **A calendar-feed URL is a secret.** It carries a token, so it's stored in the Keychain and messages show only its host.
- **The Canvas token stays on the school's host.** It is only sent there over https, and `Link: rel="next"` pages are followed only on the same host.
- **Notion API version** `2022-06-28`. Status is a `select` column, because the API can't create `status` columns.
- `~/.fixel/canvas.json` (mode 600) holds the school address, the source kind, the database id, the AI plans, and a per-row fingerprint of the last Canvas facts written. It never holds a token.

## 3. Pieces (`fixel/canvas/`)

| File | Job |
|---|---|
| `items.py` | `Assignment` (Canvas facts) and `Plan` (AI fields) |
| `http.py` | `urlopen_fetch` and `HTTPFailure` |
| `source.py` | `CanvasAPI` (planner items API) and `CalendarFeed` + `parse_ics`. Both produce ids like `assignment-123`, so switching sources doesn't duplicate rows |
| `planner.py` | Batched prompt (20 per request) → JSON. `parse_plans` clamps every field (priority set, 0.25–40 h in quarter hours, start-by never after due or in the past) |
| `notion.py` | Create the database, list rows by Canvas ID, create/update pages, retry on 429 |
| `sync.py` | `push`: the re-sync rules above |
| `store.py` | `canvas.json` |
| `command.py` | `/canvas [setup\|notion\|forget]` |

`/api canvas` and `/api notion` open the same setup steps. `canvas_days` (default 14) in `config.toml` sets how far ahead to look. Unsubmitted work up to 7 days overdue still shows, marked late.

## 4. Errors

Every failure is one plain sentence naming the fix:

- a rejected token → make a new one, then `/canvas setup`
- an unshared Notion page → ••• → Connections
- a renamed Notion column → list the missing names
- offline

A model failure never blocks the sync: assignments still show and sync, and the next `/canvas` plans them. Ctrl+C stops a sync, and rows already written are remembered.
