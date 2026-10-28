"""Write assignments into Notion without ever undoing your own edits there."""

from __future__ import annotations

from .items import Assignment
from .notion import Notion, facts, fingerprint, plan_fields
from .store import CanvasStore, Synced


def push(notion: Notion, database_id: str, assignments: list[Assignment], store: CanvasStore) -> tuple[int, int]:
    """Add new rows and refresh changed ones. Returns (added, updated).

    The rules: Canvas facts (title, due, link, submitted…) follow Canvas on every sync; the AI fields are
    written once; Status is set when a row is made and never touched again; a row you deleted stays deleted.
    """
    notion.check_database(database_id)
    rows = notion.rows(database_id)
    added = updated = 0
    for a in assignments:
        known = store.synced.get(a.uid)
        plan = store.plans.get(a.uid)
        page = rows.get(a.uid)
        if page is None:
            if known is not None:  # Fixel made this row before and it's gone: you deleted it
                continue
            notion.create(database_id, a, plan)
            store.synced[a.uid] = Synced(facts=fingerprint(a), planned=plan is not None)
            added += 1
            continue
        known = known or Synced()
        changes: dict = {}
        if known.facts != fingerprint(a):
            changes.update(facts(a))
        if plan is not None and not known.planned:  # the AI couldn't plan it last time; fill in once now
            changes.update(plan_fields(plan))
        if changes:
            notion.update(page, changes)
            updated += 1
        store.synced[a.uid] = Synced(facts=fingerprint(a), planned=known.planned or plan is not None)
    return added, updated
