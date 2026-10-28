"""Notion with your own integration token: make the Canvas database, then add and update its rows."""

from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from .http import Fetch, HTTPFailure, urlopen_fetch
from .items import Assignment, Plan

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
STATUSES = ("Not started", "In progress", "Done")

SCHEMA = {
    "Name": {"title": {}},
    "Course": {"select": {}},
    "Due": {"date": {}},
    "Status": {"select": {"options": [
        {"name": "Not started", "color": "gray"}, {"name": "In progress", "color": "blue"}, {"name": "Done", "color": "green"},
    ]}},
    "Priority": {"select": {"options": [
        {"name": "High", "color": "red"}, {"name": "Medium", "color": "yellow"}, {"name": "Low", "color": "gray"},
    ]}},
    "Hours": {"number": {"format": "number"}},
    "Start by": {"date": {}},
    "Tip": {"rich_text": {}},
    "Submitted": {"checkbox": {}},
    "Points": {"number": {"format": "number"}},
    "Link": {"url": {}},
    "Canvas ID": {"rich_text": {}},
}


class NotionError(Exception):
    """Something worth telling the user about their Notion connection."""


def page_id_from(text: str) -> str | None:
    """The page id at the end of a Notion link ('…/My-Page-1a2b…'), or a bare id, as 32 hex digits."""
    text = text.strip()
    segment = (urlsplit(text).path if "://" in text else text).rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})$", segment)
    return match.group(1).replace("-", "").lower() if match else None


def _text(value: str) -> list[dict]:
    return [{"text": {"content": value[:2000]}}] if value else []


def _date(value) -> dict | None:
    return {"start": value.isoformat()} if value is not None else None


def facts(a: Assignment) -> dict:
    """The Canvas side of a row: rewritten on every sync when it changes."""
    return {
        "Name": {"title": _text(a.title)},
        "Course": {"select": {"name": a.course.replace(",", " ")[:100]} if a.course else None},  # Notion bans commas here
        "Due": {"date": _date(a.due)},
        "Submitted": {"checkbox": a.submitted},
        "Points": {"number": a.points},
        "Link": {"url": a.url or None},
        "Canvas ID": {"rich_text": _text(a.uid)},
    }


def plan_fields(plan: Plan) -> dict:
    """The AI side of a row: written once, then it's yours to change."""
    return {
        "Priority": {"select": {"name": plan.priority}},
        "Hours": {"number": plan.hours},
        "Start by": {"date": _date(plan.start_by)},
        "Tip": {"rich_text": _text(plan.tip)},
    }


def fingerprint(a: Assignment) -> str:
    return hashlib.sha256(json.dumps(facts(a), sort_keys=True).encode()).hexdigest()[:16]


class Notion:
    def __init__(self, token: str, fetch: Fetch = urlopen_fetch) -> None:
        self._token = token
        self._fetch = fetch

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        }
        payload = json.dumps(body).encode() if body is not None else None
        for attempt in range(3):
            try:
                status, response_headers, raw = self._fetch(method, f"{API}{path}", headers, payload)
            except HTTPFailure as e:
                raise NotionError(str(e)) from None
            if status != 429 or attempt == 2:
                break
            wait = next((v for k, v in response_headers.items() if k.lower() == "retry-after"), "1")
            time.sleep(min(float(wait) if wait.replace(".", "", 1).isdigit() else 1.0, 10.0))  # Notion allows ~3 requests/s
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if status == 401:
            raise NotionError("Notion rejected your integration token. Copy it again from notion.so/my-integrations, then /canvas notion.")
        if status == 404:
            raise NotionError(
                "Notion can't see that page or database. In Notion open it, then ••• → Connections → add your "
                "integration, and try again."
            )
        if status >= 400:
            raise NotionError(f"Notion said: {data.get('message') or f'error {status}'}")
        return data

    def create_database(self, page_id: str, title: str = "Canvas") -> str:
        data = self._call("POST", "/databases", {
            "parent": {"type": "page_id", "page_id": page_id},
            "title": _text(title),
            "properties": SCHEMA,
        })
        return data["id"]

    def check_database(self, database_id: str) -> None:
        """Make sure the database still has the columns Fixel writes (someone may have renamed one)."""
        data = self._call("GET", f"/databases/{database_id}")
        missing = [name for name in SCHEMA if name not in data.get("properties", {})]
        if missing:
            raise NotionError(f"Your Canvas database is missing: {', '.join(missing)}. Rename them back, or /canvas notion for a new one.")

    def rows(self, database_id: str) -> dict[str, str]:
        """Canvas ID -> Notion page id, for every row in the database."""
        found: dict[str, str] = {}
        body: dict = {"page_size": 100}
        for _ in range(50):
            data = self._call("POST", f"/databases/{database_id}/query", body)
            for page in data.get("results", []):
                pieces = page.get("properties", {}).get("Canvas ID", {}).get("rich_text", [])
                uid = "".join(piece.get("plain_text", "") for piece in pieces)
                if uid:
                    found[uid] = page["id"]
            if not data.get("has_more"):
                break
            body = {"page_size": 100, "start_cursor": data.get("next_cursor")}
        return found

    def create(self, database_id: str, a: Assignment, plan: Plan | None) -> str:
        properties = {**facts(a), "Status": {"select": {"name": "Done" if a.submitted else "Not started"}}}
        if plan is not None:
            properties.update(plan_fields(plan))
        return self._call("POST", "/pages", {"parent": {"database_id": database_id}, "properties": properties})["id"]

    def update(self, page_id: str, properties: dict) -> None:
        self._call("PATCH", f"/pages/{page_id}", {"properties": properties})
