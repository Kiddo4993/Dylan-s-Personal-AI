"""The /canvas command: setup, Notion setup, sync, and forget."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable

from ..brain.base import Provider, ProviderError
from ..config import Config, delete_api_key, get_api_key, set_api_key
from ..ui import UI
from .http import Fetch, urlopen_fetch
from .notion import Notion, NotionError, page_id_from
from .planner import PlannerError, make_plans
from .source import CalendarFeed, CanvasAPI, CanvasError, Source, looks_like_feed, normalize_base
from .store import CanvasStore
from .sync import push

USAGE = "Usage: /canvas (sync), /canvas setup, /canvas notion, or /canvas forget"


def _local_now() -> datetime:
    return datetime.now().astimezone()


class CanvasCommand:
    def __init__(
        self,
        cfg: Config,
        ui: UI,
        provider: Callable[[], Provider | None],
        *,
        fetch: Fetch = urlopen_fetch,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        self.cfg = cfg
        self.ui = ui
        self._provider = provider
        self._fetch = fetch
        self._now = now

    def _store(self) -> CanvasStore:
        return CanvasStore.load(self.cfg.canvas_path)

    async def run(self, arg: str) -> None:
        sub = arg.strip().lower()
        if sub in ("", "sync"):
            await self.sync()
        elif sub == "setup":
            await self.setup()
        elif sub == "notion":
            await self.setup_notion()
        elif sub == "forget":
            self.forget()
        else:
            self.ui.warn(USAGE)

    # ---- connecting

    async def setup(self) -> None:
        store = self._store()
        self.ui.console.print(
            "\n[bold cyan]Connect Canvas[/]\n"
            "  Best: an access token. Canvas → Account → Settings → [bold]+ New Access Token[/].\n"
            "  No token button at your school? Use your calendar feed: Canvas → Calendar → [bold]Calendar Feed[/].\n"
            "  [dim]Either one is saved in the macOS Keychain, never in a file.[/]\n"
        )
        # Hidden: Fixel screenshots this screen, and both a token and a feed link unlock your Canvas.
        secret = await self.ui.ask_input("Paste your Canvas token or calendar-feed link (hidden; Enter to cancel): ", is_password=True)
        if not secret:
            self.ui.info("Cancelled. Nothing saved.")
            return
        if looks_like_feed(secret):
            feed = CalendarFeed(secret, self._fetch)
            try:
                found = await asyncio.to_thread(feed.upcoming, self._now(), self.cfg.canvas_days)
            except CanvasError as e:
                self.ui.error(str(e))
                return
            set_api_key("canvas", feed.url)
            store.source, store.base = "feed", feed.base
            store.save()
            self.ui.react(f"Calendar feed connected: {len(found)} coming up.")
            self.ui.info("A feed can't tell Fixel what you've handed in. An access token can, if your school allows one.")
        else:
            address = await self.ui.ask_input(
                "Your school's Canvas address (e.g. myschool.instructure.com): ", default=store.base.removeprefix("https://")
            )
            base = normalize_base(address)
            if base is None:
                self.ui.warn("That doesn't look like a web address. Nothing saved; run /canvas setup again.")
                return
            try:
                name = await asyncio.to_thread(CanvasAPI(base, secret, self._fetch).whoami)
            except CanvasError as e:
                self.ui.error(str(e))
                return
            set_api_key("canvas", secret)
            store.source, store.base = "api", base
            store.save()
            self.ui.react(f"Canvas connected as {name}.")
        follow = "/canvas syncs now." if store.notion_database else "/canvas syncs now; /canvas notion adds a Notion database."
        self.ui.info(follow)

    async def setup_notion(self) -> None:
        store = self._store()
        saved = get_api_key("notion")
        self.ui.console.print(
            "\n[bold cyan]Connect Notion[/]\n"
            "  1. notion.so/my-integrations → [bold]New integration[/] → copy its secret.\n"
            "  2. Open the Notion page the database should go in → [bold]•••[/] → Connections → add your integration.\n"
        )
        hint = "Enter keeps the saved one" if saved else "Enter to cancel"
        token = await self.ui.ask_input(f"Paste your Notion integration secret (hidden; {hint}): ", is_password=True) or saved
        if not token:
            self.ui.info("Cancelled. Nothing saved.")
            return
        page = page_id_from(await self.ui.ask_input("Link to that Notion page: "))
        if page is None:
            self.ui.warn("That isn't a Notion page link (it ends in a long id). Nothing saved; run /canvas notion again.")
            return
        try:
            database = await asyncio.to_thread(Notion(token, self._fetch).create_database, page)
        except NotionError as e:
            self.ui.error(str(e))
            return
        set_api_key("notion", token)
        store.notion_database = database
        store.synced = {}  # a new, empty database: every assignment gets a fresh row
        store.save()
        self.ui.react("Made a Canvas database in that Notion page.")
        self.ui.info("/canvas fills it." if store.source else "Now /canvas setup to connect Canvas.")

    def forget(self) -> None:
        removed = [name for name in ("canvas", "notion") if delete_api_key(name)]
        self.cfg.canvas_path.unlink(missing_ok=True)
        what = " and ".join(name.title() for name in removed) or "No"
        self.ui.info(f"{what} token{'s' if len(removed) > 1 else ''} removed from the Keychain; /canvas settings cleared. Your Notion database stays.")

    # ---- syncing

    def _source(self, store: CanvasStore) -> Source | None:
        secret = get_api_key("canvas")
        if not secret or store.source not in ("api", "feed"):
            return None
        if store.source == "feed":
            return CalendarFeed(secret, self._fetch)
        return CanvasAPI(store.base, secret, self._fetch)

    async def sync(self) -> None:
        store = self._store()
        source = self._source(store)
        if source is None:
            self.ui.info("Canvas isn't connected yet. /canvas setup connects it (about a minute).")
            return
        now = self._now()
        self.ui.info(f"Checking Canvas ({store.base.removeprefix('https://')})…")
        try:
            assignments = await asyncio.to_thread(source.upcoming, now, self.cfg.canvas_days)
        except CanvasError as e:
            self.ui.error(str(e))
            return
        await self._plan(store, assignments, now)
        self.ui.canvas_table(assignments, store.plans, now, self.cfg.canvas_days)
        token = get_api_key("notion")
        if not (store.notion_database and token and assignments):
            return
        try:
            added, updated = await asyncio.to_thread(push, Notion(token, self._fetch), store.notion_database, assignments, store)
        except NotionError as e:
            self.ui.error(str(e))
        else:
            self.ui.info(f"Notion: {added} added, {updated} updated.")
        finally:
            store.save()  # rows written before a failure are remembered, so they aren't added twice

    async def _plan(self, store: CanvasStore, assignments, now: datetime) -> None:
        """Plan only what's new: a plan is made once, so re-syncing is free and your Notion edits stand."""
        new = [a for a in assignments if a.uid not in store.plans and not a.submitted]
        if not new:
            return
        provider = self._provider()
        if provider is None:
            self.ui.warn("No AI model is ready, so no priorities this time. /api adds a key; /canvas tries again.")
            return
        self.ui.info(f"Planning {len(new)} assignment{'s' if len(new) != 1 else ''} with {provider.name}…")
        try:
            store.plans.update(await make_plans(provider, new, now.date()))
        except Exception as e:  # PlannerError/ProviderError are expected; anything else is an SDK surprise
            reason = str(e) if isinstance(e, (PlannerError, ProviderError)) else f"Unexpected error from {provider.name}: {e!r}."
            self.ui.warn(f"{reason} Assignments still synced; /canvas tries planning again.")
        store.save()
