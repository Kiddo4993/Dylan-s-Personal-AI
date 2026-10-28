import json
import stat
from datetime import date, datetime, timedelta, timezone

import pytest

from fixel.brain.fake import FakeProvider
from fixel.canvas import command as command_module
from fixel.canvas.command import CanvasCommand
from fixel.canvas.http import HTTPFailure
from fixel.canvas.items import Assignment, Plan
from fixel.canvas.notion import Notion, NotionError, page_id_from
from fixel.canvas.planner import PlannerError, build_prompt, make_plans, parse_plans
from fixel.canvas.source import CalendarFeed, CanvasAPI, CanvasError, looks_like_feed, normalize_base, parse_ics
from fixel.canvas.store import CanvasStore, Synced
from fixel.canvas.sync import push
from fixel.config import Config
from fixel.ui import UI

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
BASE = "https://school.instructure.com"
FEED = f"{BASE}/feeds/calendars/user_SECRETfeedtoken123.ics"


class FakeNet:
    """Answers requests from a list of (method, url-start, handler) routes and records every call."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, method, url, handler):
        self.routes.append((method, url, handler))
        return self

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        for m, start, handler in self.routes:
            if m == method and url.startswith(start):
                result = handler(url, json.loads(body) if body else None)
                status, data = result[:2]
                response_headers = result[2] if len(result) > 2 else {}
                raw = data if isinstance(data, bytes) else json.dumps(data).encode()
                return status, response_headers, raw
        raise AssertionError(f"unexpected request {method} {url}")


def planner_item(pid, title, due, *, kind="assignment", submitted=False, course="AP CSA"):
    return {
        "plannable_type": kind,
        "plannable_id": pid,
        "plannable_date": due.isoformat().replace("+00:00", "Z") if due else None,
        "context_name": course,
        "html_url": f"/courses/1/assignments/{pid}",
        "plannable": {"title": title, "points_possible": 10},
        "submissions": {"submitted": submitted} if kind != "announcement" else False,
    }


def make(uid="assignment-1", title="Lab 1", due=NOW + timedelta(days=2), **kw):
    return Assignment(uid=uid, title=title, course=kw.pop("course", "AP CSA"), due=due, **kw)


# ---- sources


def test_normalize_base():
    assert normalize_base("school.instructure.com") == BASE
    assert normalize_base("https://school.instructure.com/courses/5") == BASE
    assert normalize_base("http://school.instructure.com") == BASE  # tokens only go over https
    assert normalize_base("not a url") is None
    assert normalize_base("") is None


def test_looks_like_feed():
    assert looks_like_feed(FEED)
    assert looks_like_feed("webcal://school.instructure.com/feeds/calendars/user_x.ics")
    assert not looks_like_feed("7~abcdefTOKEN")


def test_api_reads_planner_items_and_keeps_the_right_ones():
    items = [
        planner_item(1, "Lab 1", NOW + timedelta(days=2)),
        planner_item(2, "Old quiz", NOW - timedelta(days=2), kind="quiz", submitted=True),  # done and past: dropped
        planner_item(3, "Missing essay", NOW - timedelta(days=2)),  # overdue, not handed in: kept
        planner_item(4, "Announcement", NOW + timedelta(days=1), kind="announcement"),  # not work: dropped
        planner_item(5, "Far away", NOW + timedelta(days=40)),  # outside the window: dropped
        planner_item(6, "Discuss", NOW + timedelta(days=1), kind="discussion_topic"),
    ]
    net = FakeNet().on("GET", f"{BASE}/api/v1/planner/items", lambda url, body: (200, items))
    found = CanvasAPI(BASE, "tok", net).upcoming(NOW, 14)
    assert [a.uid for a in found] == ["assignment-3", "discussion_topic-6", "assignment-1"]
    assert found[2].url == f"{BASE}/courses/1/assignments/1" and found[2].points == 10
    assert net.calls[0][2]["Authorization"] == "Bearer tok"


def test_api_follows_pages_only_on_the_same_school():
    page2 = f"{BASE}/api/v1/planner/items?page=2"
    pages = {
        "first": (200, [planner_item(1, "A", NOW + timedelta(days=1))], {"Link": f'<{page2}>; rel="next"'}),
        "second": (200, [planner_item(2, "B", NOW + timedelta(days=1))], {"Link": '<https://evil.example/steal>; rel="next"'}),
    }
    net = FakeNet().on("GET", page2, lambda url, body: pages["second"]).on("GET", f"{BASE}/api/v1/planner", lambda url, body: pages["first"])
    found = CanvasAPI(BASE, "tok", net).upcoming(NOW, 14)
    assert {a.uid for a in found} == {"assignment-1", "assignment-2"}
    assert all("evil" not in call[1] for call in net.calls)  # the token never left the school


def test_api_explains_a_rejected_token():
    net = FakeNet().on("GET", BASE, lambda url, body: (401, {"errors": []}))
    with pytest.raises(CanvasError, match="rejected your access token"):
        CanvasAPI(BASE, "bad", net).whoami()


def test_api_explains_being_offline():
    def offline(*args):
        raise HTTPFailure("Couldn't reach school.instructure.com (offline).")

    with pytest.raises(CanvasError, match="Couldn't reach"):
        CanvasAPI(BASE, "tok", offline).upcoming(NOW, 14)


ICS = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-assignment-77\r\n"
    "DTSTART:20261030T055900Z\r\n"
    "SUMMARY:Essay 2\\, final draft [ENGL 101]\r\n"
    "URL:https://school.instructure.com/courses/2/assignments/77\r\n"
    "DESCRIPTION:A long description that Canvas folds onto\r\n"
    "  a second line\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-calendar-event-5\r\n"
    "DTSTART:20261029T150000Z\r\n"
    "SUMMARY:Club meeting [Robotics]\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-assignment-78\r\n"
    "DTSTART;VALUE=DATE:20261101\r\n"
    "SUMMARY:Reading log [ENGL 101]\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_parse_ics_reads_canvas_assignments_only():
    found = parse_ics(ICS)
    assert [a.uid for a in found] == ["assignment-77", "assignment-78"]  # same ids as the API gives
    essay = found[0]
    assert (essay.title, essay.course) == ("Essay 2, final draft", "ENGL 101")
    assert essay.due == datetime(2026, 10, 30, 5, 59, tzinfo=timezone.utc)
    assert found[1].due.astimezone().hour == 23  # all-day: due by the end of the day


def test_feed_fetches_and_filters():
    net = FakeNet().on("GET", FEED, lambda url, body: (200, ICS.encode()))
    found = CalendarFeed(FEED.replace("https://", "webcal://"), net).upcoming(NOW, 14)
    assert len(found) == 2 and net.calls[0][1] == FEED


def test_feed_errors_never_show_the_secret_link():
    net = FakeNet().on("GET", FEED, lambda url, body: (403, b"no"))
    with pytest.raises(CanvasError) as raised:
        CalendarFeed(FEED, net).upcoming(NOW, 14)
    assert "SECRET" not in str(raised.value) and "school.instructure.com" in str(raised.value)


# ---- planner


def test_parse_plans_forces_every_field_into_range():
    due = datetime(2026, 11, 2, 23, 59, tzinfo=timezone.utc)
    a = make(due=due)
    reply = "```json\n" + json.dumps([
        {"id": "assignment-1", "priority": "urgent", "hours": 99, "start_by": "2026-12-01", "tip": "  Start   early.  "},
        {"id": "made-up", "priority": "High", "hours": 1, "start_by": "2026-11-01", "tip": "x"},
    ]) + "\n```"
    plans = parse_plans(reply, [a], date(2026, 10, 28))
    assert list(plans) == ["assignment-1"]
    plan = plans["assignment-1"]
    assert plan.priority == "Medium" and plan.hours == 40
    assert plan.start_by == due.astimezone().date()  # never after it's due
    assert plan.tip == "Start early."


def test_parse_plans_keeps_start_dates_out_of_the_past():
    plans = parse_plans('[{"id": "assignment-1", "priority": "low", "hours": 0.3, "start_by": "2020-01-01", "tip": "t"}]', [make()], date(2026, 10, 28))
    assert plans["assignment-1"] == Plan("Low", 0.25, date(2026, 10, 28), "t")


def test_parse_plans_rejects_answers_without_json():
    with pytest.raises(PlannerError):
        parse_plans("Sorry, I can't help with that.", [make()], date(2026, 10, 28))


async def test_make_plans_asks_the_model_with_todays_date():
    provider = FakeProvider(['[{"id": "assignment-1", "priority": "High", "hours": 2, "start_by": "2026-10-29", "tip": "Outline first."}]'])
    plans = await make_plans(provider, [make()], date(2026, 10, 28))
    assert plans["assignment-1"].priority == "High"
    turns, system, deep = provider.calls[0]
    assert "Today is 2026-10-28" in turns[0].text and "JSON array" in system and not deep


def test_build_prompt_lists_each_assignment():
    prompt = build_prompt([make(title="Unit 3 FRQ")], date(2026, 10, 28))
    assert "Unit 3 FRQ" in prompt and "assignment-1" in prompt


# ---- notion


def test_page_id_from_links_and_ids():
    hex_id = "1a2b3c4d5e6f708192a3b4c5d6e7f809"
    assert page_id_from(f"https://www.notion.so/me/Bad-Cafe-{hex_id}?pvs=4") == hex_id
    assert page_id_from("1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809") == hex_id
    assert page_id_from("https://www.notion.so/me/My-Page") is None


class FakeNotion:
    """Stands in for the Notion class: a dict of rows."""

    def __init__(self, rows=None):
        self.pages = dict(rows or {})  # uid -> page id
        self.created = []
        self.updates = []

    def check_database(self, database_id):
        pass

    def rows(self, database_id):
        return dict(self.pages)

    def create(self, database_id, a, plan):
        self.created.append((a.uid, plan))
        self.pages[a.uid] = f"page-{a.uid}"
        return self.pages[a.uid]

    def update(self, page_id, properties):
        self.updates.append((page_id, properties))


def test_push_adds_new_rows_with_the_plan(tmp_path):
    store = CanvasStore(tmp_path / "c.json", plans={"assignment-1": Plan("High", 2, None, "tip")})
    notion = FakeNotion()
    assert push(notion, "db", [make()], store) == (1, 0)
    assert notion.created == [("assignment-1", store.plans["assignment-1"])]
    assert store.synced["assignment-1"].planned


def test_push_rewrites_canvas_facts_but_never_your_fields(tmp_path):
    store = CanvasStore(tmp_path / "c.json", plans={"assignment-1": Plan("High", 2, None, "tip")})
    notion = FakeNotion()
    push(notion, "db", [make()], store)
    assert push(notion, "db", [make()], store) == (0, 0)  # nothing changed: nothing written
    push(notion, "db", [make(title="Lab 1 (extended)", due=NOW + timedelta(days=5))], store)
    (_, properties), = notion.updates
    assert properties["Name"]["title"][0]["text"]["content"] == "Lab 1 (extended)"
    assert not {"Status", "Priority", "Hours", "Start by", "Tip"} & set(properties)


def test_push_fills_in_a_plan_once_if_it_was_missing(tmp_path):
    store = CanvasStore(tmp_path / "c.json")
    notion = FakeNotion()
    push(notion, "db", [make()], store)  # the AI was down: no plan yet
    store.plans["assignment-1"] = Plan("Low", 1, None, "t")
    push(notion, "db", [make()], store)
    push(notion, "db", [make()], store)
    assert len(notion.updates) == 1 and "Priority" in notion.updates[0][1]


def test_push_leaves_rows_you_deleted_deleted(tmp_path):
    store = CanvasStore(tmp_path / "c.json")
    notion = FakeNotion()
    push(notion, "db", [make()], store)
    notion.pages.clear()  # you deleted the row in Notion
    assert push(notion, "db", [make()], store) == (0, 0)


def test_notion_create_sets_status_once_and_sends_the_token():
    net = FakeNet().on("POST", "https://api.notion.com/v1/pages", lambda url, body: (200, {"id": "p1"}))
    Notion("secret_tok", net).create("db", make(submitted=True), Plan("High", 2, date(2026, 10, 29), "tip"))
    method, url, headers, body = net.calls[0]
    assert headers["Authorization"] == "Bearer secret_tok" and headers["Notion-Version"]
    props = body["properties"]
    assert props["Status"]["select"]["name"] == "Done" and props["Priority"]["select"]["name"] == "High"
    assert props["Course"]["select"]["name"] == "AP CSA"


def test_notion_course_names_lose_commas():
    net = FakeNet().on("POST", "https://api.notion.com/v1/pages", lambda url, body: (200, {"id": "p1"}))
    Notion("t", net).create("db", make(course="Math, Period 3"), None)
    assert "," not in net.calls[0][3]["properties"]["Course"]["select"]["name"]


def test_notion_rows_pages_through_the_database():
    pages = [
        {"results": [{"id": "p1", "properties": {"Canvas ID": {"rich_text": [{"plain_text": "assignment-1"}]}}}], "has_more": True, "next_cursor": "c2"},
        {"results": [{"id": "p2", "properties": {"Canvas ID": {"rich_text": [{"plain_text": "assignment-2"}]}}}], "has_more": False},
    ]
    net = FakeNet().on("POST", "https://api.notion.com/v1/databases/db/query", lambda url, body: (200, pages.pop(0)))
    assert Notion("t", net).rows("db") == {"assignment-1": "p1", "assignment-2": "p2"}
    assert net.calls[1][3]["start_cursor"] == "c2"


def test_notion_explains_an_unshared_page():
    net = FakeNet().on("POST", "https://api.notion.com/v1/databases", lambda url, body: (404, {"message": "Could not find page"}))
    with pytest.raises(NotionError, match="Connections"):
        Notion("t", net).create_database("abc")


def test_notion_retries_when_rate_limited(monkeypatch):
    monkeypatch.setattr("fixel.canvas.notion.time.sleep", lambda s: None)
    answers = [(429, {}, {"Retry-After": "1"}), (200, {"id": "p1"})]
    net = FakeNet().on("POST", "https://api.notion.com/v1/pages", lambda url, body: answers.pop(0))
    assert Notion("t", net).create("db", make(), None) == "p1"


# ---- store


def test_store_round_trips_and_is_private(tmp_path):
    path = tmp_path / "canvas.json"
    store = CanvasStore(path, source="api", base=BASE, notion_database="db")
    store.plans["assignment-1"] = Plan("High", 1.5, date(2026, 10, 29), "tip")
    store.synced["assignment-1"] = Synced("abc", True)
    store.save()
    again = CanvasStore.load(path)
    assert again == CanvasStore(path, "api", BASE, "db", store.plans, store.synced)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "tok" not in path.read_text()


def test_store_survives_a_broken_file(tmp_path):
    path = tmp_path / "canvas.json"
    path.write_text("{not json")
    assert CanvasStore.load(path).source == ""


# ---- the /canvas command


class Inputs:
    def __init__(self, ui, answers):
        self.answers = list(answers)
        self.asked = []
        ui.ask_input = self

    async def __call__(self, question, *, is_password=False, default=""):
        self.asked.append((question, is_password))
        return self.answers.pop(0) if self.answers else ""


@pytest.fixture
def keys(monkeypatch):
    saved = {}
    monkeypatch.setattr(command_module, "get_api_key", lambda name: saved.get(name))
    monkeypatch.setattr(command_module, "set_api_key", lambda name, key: saved.__setitem__(name, key))
    monkeypatch.setattr(command_module, "delete_api_key", lambda name: saved.pop(name, None) is not None)
    return saved


def canvas_command(tmp_path, console, net, provider=None):
    ui = UI(console)
    cmd = CanvasCommand(Config(home=tmp_path), ui, lambda: provider, fetch=net, now=lambda: NOW)
    return cmd, ui


async def test_setup_with_a_token_checks_it_then_saves_it(tmp_path, console, keys):
    net = FakeNet().on("GET", f"{BASE}/api/v1/users/self", lambda url, body: (200, {"short_name": "Sam"}))
    cmd, ui = canvas_command(tmp_path, console, net)
    inputs = Inputs(ui, ["7~token", "school.instructure.com"])
    await cmd.run("setup")
    assert keys == {"canvas": "7~token"}
    assert inputs.asked[0][1] is True  # the token prompt is hidden
    assert CanvasStore.load(tmp_path / "canvas.json").base == BASE
    out = console.file.getvalue()
    assert "connected as Sam" in out and "7~token" not in out


async def test_setup_does_not_save_a_rejected_token(tmp_path, console, keys):
    net = FakeNet().on("GET", BASE, lambda url, body: (401, {}))
    cmd, ui = canvas_command(tmp_path, console, net)
    Inputs(ui, ["bad", "school.instructure.com"])
    await cmd.run("setup")
    assert keys == {} and "rejected" in console.file.getvalue()


async def test_setup_with_a_feed_link(tmp_path, console, keys):
    net = FakeNet().on("GET", FEED, lambda url, body: (200, ICS.encode()))
    cmd, ui = canvas_command(tmp_path, console, net)
    Inputs(ui, [FEED])
    await cmd.run("setup")
    assert keys["canvas"] == FEED and CanvasStore.load(tmp_path / "canvas.json").source == "feed"
    assert "SECRET" not in console.file.getvalue()


async def test_sync_before_setup_points_to_setup(tmp_path, console, keys):
    cmd, _ = canvas_command(tmp_path, console, FakeNet())
    await cmd.run("")
    assert "/canvas setup" in console.file.getvalue()


async def test_sync_plans_shows_and_pushes_to_notion(tmp_path, console, keys):
    keys.update(canvas="tok", notion="ntok")
    CanvasStore(tmp_path / "canvas.json", source="api", base=BASE, notion_database="db").save()
    net = (
        FakeNet()
        .on("GET", f"{BASE}/api/v1/planner/items", lambda url, body: (200, [planner_item(1, "Lab 1", NOW + timedelta(days=2))]))
        .on("GET", "https://api.notion.com/v1/databases/db", lambda url, body: (200, {"properties": dict.fromkeys(
            ["Name", "Course", "Due", "Status", "Priority", "Hours", "Start by", "Tip", "Submitted", "Points", "Link", "Canvas ID"], {})}))
        .on("POST", "https://api.notion.com/v1/databases/db/query", lambda url, body: (200, {"results": [], "has_more": False}))
        .on("POST", "https://api.notion.com/v1/pages", lambda url, body: (200, {"id": "p1"}))
    )
    provider = FakeProvider(['[{"id": "assignment-1", "priority": "High", "hours": 2, "start_by": "2026-10-29", "tip": "Read the rubric first."}]'])
    cmd, _ = canvas_command(tmp_path, console, net, provider)
    await cmd.run("")
    out = console.file.getvalue()
    assert "Lab 1" in out and "High" in out and "Read the rubric first." in out and "1 added" in out
    await cmd.run("")  # second sync: no new plan asked for, nothing rewritten
    assert len(provider.calls) == 1 and "0 added, 0 updated" in console.file.getvalue()


async def test_sync_without_a_model_still_lists_assignments(tmp_path, console, keys):
    keys.update(canvas="tok")
    CanvasStore(tmp_path / "canvas.json", source="api", base=BASE).save()
    net = FakeNet().on("GET", f"{BASE}/api/v1/planner/items", lambda url, body: (200, [planner_item(1, "Lab 1", NOW + timedelta(days=2))]))
    cmd, _ = canvas_command(tmp_path, console, net)
    await cmd.run("")
    out = console.file.getvalue()
    assert "Lab 1" in out and "No AI model" in out


async def test_notion_setup_makes_the_database(tmp_path, console, keys):
    net = FakeNet().on("POST", "https://api.notion.com/v1/databases", lambda url, body: (200, {"id": "newdb"}))
    cmd, ui = canvas_command(tmp_path, console, net)
    Inputs(ui, ["secret_tok", "https://www.notion.so/me/School-1a2b3c4d5e6f708192a3b4c5d6e7f809"])
    await cmd.run("notion")
    assert keys["notion"] == "secret_tok" and CanvasStore.load(tmp_path / "canvas.json").notion_database == "newdb"
    assert net.calls[0][3]["parent"]["page_id"] == "1a2b3c4d5e6f708192a3b4c5d6e7f809"


async def test_forget_removes_tokens_and_settings(tmp_path, console, keys):
    keys.update(canvas="tok", notion="ntok")
    CanvasStore(tmp_path / "canvas.json", source="api", base=BASE).save()
    cmd, _ = canvas_command(tmp_path, console, FakeNet())
    await cmd.run("forget")
    assert keys == {} and not (tmp_path / "canvas.json").exists()


async def test_unknown_subcommand_shows_usage(tmp_path, console, keys):
    cmd, _ = canvas_command(tmp_path, console, FakeNet())
    await cmd.run("bogus")
    assert "Usage: /canvas" in console.file.getvalue()


# ---- wired into Fixel


class RecordingCanvas:
    def __init__(self, cfg, ui, provider):
        self.provider = provider
        self.runs = []

    async def run(self, arg):
        self.runs.append(arg)


def fixel_app(tmp_path, console):
    from fixel.app import FixelApp

    return FixelApp(Config(home=tmp_path), UI(console), provider_factory=lambda alias, cfg: FakeProvider(), canvas_factory=RecordingCanvas)


async def test_slash_canvas_runs_the_canvas_command(tmp_path, console):
    app = fixel_app(tmp_path, console)
    await app.handle_command("/canvas setup")
    await app.handle_command("/canvas")
    assert app.canvas.runs == ["setup", ""]


async def test_api_canvas_and_notion_go_to_their_setup(tmp_path, console):
    app = fixel_app(tmp_path, console)
    await app.handle_command("/api canvas")
    await app.handle_command("/api Notion")
    assert app.canvas.runs == ["setup", "notion"]


def test_canvas_uses_whichever_model_is_selected(tmp_path, console):
    app = fixel_app(tmp_path, console)
    assert app.canvas.provider() is None
    app.select_model("sonnet")
    assert app.canvas.provider() is app.provider


async def test_a_failing_model_does_not_stop_the_sync(tmp_path, console, keys):
    keys.update(canvas="tok")
    CanvasStore(tmp_path / "canvas.json", source="api", base=BASE).save()
    net = FakeNet().on("GET", f"{BASE}/api/v1/planner/items", lambda url, body: (200, [planner_item(1, "Lab 1", NOW + timedelta(days=2))]))
    cmd, _ = canvas_command(tmp_path, console, net, FakeProvider(error=RuntimeError("boom")))
    await cmd.run("")
    out = console.file.getvalue()
    assert "Lab 1" in out and "Unexpected error from fake" in out
    assert CanvasStore.load(tmp_path / "canvas.json").plans == {}  # nothing half-saved: next sync plans it
