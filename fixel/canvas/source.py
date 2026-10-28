"""Where assignments come from: the Canvas API (your access token) or, as a fallback, your calendar feed."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .http import Fetch, HTTPFailure, host, urlopen_fetch
from .items import Assignment

PLANNABLE = ("assignment", "quiz", "discussion_topic")  # planner items worth planning; not announcements
LOOK_BACK = timedelta(days=7)  # unsubmitted work this recently overdue still shows up


class CanvasError(Exception):
    """Something worth telling the user about their Canvas connection."""


class Source(Protocol):
    def upcoming(self, now: datetime, days: int) -> list[Assignment]: ...


def normalize_base(text: str) -> str | None:
    """'myschool.instructure.com' or a full Canvas link -> 'https://myschool.instructure.com'."""
    text = text.strip()
    if not text:
        return None
    parts = urlsplit(text if "://" in text else f"https://{text}")
    if parts.scheme not in ("https", "http") or "." not in parts.netloc:
        return None
    return f"https://{parts.netloc}"  # tokens only ever travel over https


def looks_like_feed(text: str) -> bool:
    text = text.strip().lower()
    return text.startswith(("https://", "http://", "webcal://")) and (".ics" in text or "/feeds/calendars/" in text)


def keep(assignments: list[Assignment], now: datetime, days: int) -> list[Assignment]:
    """Due in the window, or recently overdue and not handed in. Soonest first; undated last."""
    end = now + timedelta(days=days)
    kept = [
        a for a in assignments
        if (a.due is None and not a.submitted)
        or (a.due is not None and a.due <= end and (a.due >= now or (not a.submitted and a.due >= now - LOOK_BACK)))
    ]
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(kept, key=lambda a: (a.due or far, a.course, a.title))


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CanvasAPI:
    """Canvas's REST API with a personal access token (Account → Settings → New Access Token)."""

    def __init__(self, base: str, token: str, fetch: Fetch = urlopen_fetch) -> None:
        self.base = base
        self._token = token
        self._fetch = fetch

    def _get(self, url: str) -> tuple[object, str | None]:
        """GET one page. Returns (json, next page's url)."""
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        try:
            status, response_headers, body = self._fetch("GET", url, headers, None)
        except HTTPFailure as e:
            raise CanvasError(str(e)) from None
        if status == 401:
            raise CanvasError(
                "Canvas rejected your access token. Make a new one (Canvas → Account → Settings → "
                "New Access Token), then run /canvas setup."
            )
        if status == 404:
            raise CanvasError(f"No Canvas API at {host(url)}. Check your school's Canvas address with /canvas setup.")
        if status >= 400:
            raise CanvasError(f"Canvas answered {status} from {host(url)}. Try again in a minute.")
        try:
            data = json.loads(body)
        except ValueError:
            raise CanvasError(f"{host(url)} didn't answer like Canvas does. Check the address with /canvas setup.") from None
        return data, self._next_link(response_headers)

    def _next_link(self, headers: dict[str, str]) -> str | None:
        link = next((v for k, v in headers.items() if k.lower() == "link"), "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        # Only follow pages on the same school: the token goes with every request.
        if match and urlsplit(match.group(1)).netloc == urlsplit(self.base).netloc:
            return match.group(1)
        return None

    def whoami(self) -> str:
        data, _ = self._get(f"{self.base}/api/v1/users/self")
        return (data.get("short_name") or data.get("name") or "you") if isinstance(data, dict) else "you"

    def upcoming(self, now: datetime, days: int) -> list[Assignment]:
        query = urlencode({
            "start_date": (now - LOOK_BACK).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date": (now + timedelta(days=days)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_page": 100,
        })
        url: str | None = f"{self.base}/api/v1/planner/items?{query}"
        found: list[Assignment] = []
        for _ in range(20):  # 2,000 items is plenty; stops a server that pages forever
            if url is None:
                break
            data, url = self._get(url)
            for item in data if isinstance(data, list) else []:
                assignment = self._assignment(item)
                if assignment is not None:
                    found.append(assignment)
        return keep(found, now, days)

    def _assignment(self, item: dict) -> Assignment | None:
        kind = item.get("plannable_type")
        if kind not in PLANNABLE or item.get("plannable_id") is None:
            return None
        plannable = item.get("plannable") or {}
        submissions = item.get("submissions")
        submitted = isinstance(submissions, dict) and bool(submissions.get("submitted") or submissions.get("graded"))
        url = item.get("html_url") or ""
        return Assignment(
            uid=f"{kind}-{item['plannable_id']}",
            title=(plannable.get("title") or "Untitled").strip(),
            course=(item.get("context_name") or "").strip(),
            due=_iso(item.get("plannable_date") or plannable.get("due_at")),
            url=f"{self.base}{url}" if url.startswith("/") else url,
            points=plannable.get("points_possible"),
            submitted=submitted,
        )


class CalendarFeed:
    """Canvas's calendar feed (Calendar → Calendar Feed). No token needed, but no submitted status either."""

    def __init__(self, url: str, fetch: Fetch = urlopen_fetch) -> None:
        self.url = "https://" + url.strip()[len("webcal://"):] if url.strip().startswith("webcal://") else url.strip()
        self.base = f"https://{urlsplit(self.url).netloc}"
        self._fetch = fetch

    def upcoming(self, now: datetime, days: int) -> list[Assignment]:
        try:
            status, _, body = self._fetch("GET", self.url, {"Accept": "text/calendar"}, None)
        except HTTPFailure as e:
            raise CanvasError(str(e)) from None
        if status >= 400:
            raise CanvasError(f"{host(self.url)} answered {status} for your calendar feed. Copy a fresh link with /canvas setup.")
        text = body.decode("utf-8", errors="replace")
        if "BEGIN:VCALENDAR" not in text:
            raise CanvasError("That link isn't a calendar feed. In Canvas: Calendar → Calendar Feed, then /canvas setup.")
        return keep(parse_ics(text), now, days)


def _unfold(text: str) -> list[str]:
    """iCalendar wraps long lines by starting the next one with a space."""
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _ics_time(value: str, params: str) -> datetime | None:
    try:
        if "VALUE=DATE" in params.upper() or len(value) == 8:  # all-day: due by the end of that day
            return datetime.strptime(value[:8], "%Y%m%d").replace(hour=23, minute=59).astimezone()
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        moment = datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    tzid = re.search(r"TZID=([^;:]+)", params)
    if tzid:
        try:
            return moment.replace(tzinfo=ZoneInfo(tzid.group(1).strip('"')))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return moment.astimezone()  # floating time: the Mac's own zone


def parse_ics(text: str) -> list[Assignment]:
    """Assignments in a Canvas calendar feed. Plain calendar events (no assignment) are skipped."""
    found: list[Assignment] = []
    event: dict[str, tuple[str, str]] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            event = {}
        elif line == "END:VEVENT" and event is not None:
            assignment = _event_assignment(event)
            if assignment is not None:
                found.append(assignment)
            event = None
        elif event is not None and ":" in line:
            name_params, value = line.split(":", 1)
            name, _, params = name_params.partition(";")
            event[name.upper()] = (params, value)
    return found


def _event_assignment(event: dict[str, tuple[str, str]]) -> Assignment | None:
    uid = event.get("UID", ("", ""))[1]
    match = re.search(r"assignment-(\d+)", uid)
    if not match:
        return None
    summary = _unescape(event.get("SUMMARY", ("", "Untitled"))[1]).strip()
    course = ""
    named = re.match(r"^(.*?)\s*\[([^\]]+)\]$", summary)  # Canvas writes "Essay 2 [ENGL 101]"
    if named:
        summary, course = named.group(1), named.group(2)
    params, start = event.get("DTSTART", ("", ""))
    return Assignment(
        uid=f"assignment-{match.group(1)}",
        title=summary or "Untitled",
        course=course,
        due=_ics_time(start, params) if start else None,
        url=event.get("URL", ("", ""))[1].strip(),
    )
