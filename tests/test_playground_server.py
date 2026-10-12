import asyncio
import http.client
import json

import pytest

from fixel.playground.runner import RunnerError, RunResult
from fixel.playground.scratch import Scratch
from fixel.playground.server import MAX_BODY, PlaygroundServer


@pytest.fixture
async def web(tmp_path):
    asked, runs = [], []

    async def fake_run(code, lang, stdin):
        runs.append((code, lang, stdin))
        if lang == "java":
            raise RunnerError("Java isn't installed.")
        return RunResult(0, "ok\n", 0.1)

    server = PlaygroundServer(asyncio.get_running_loop(), Scratch(tmp_path), fake_run, asked.append, token="T0KEN")
    server.start()
    server.asked, server.runs = asked, runs
    yield server
    server.stop()


async def call(server, method, path, body=None, *, token="T0KEN", origin=None, raw=None, headers=None):
    def go():
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        if token is not None:
            hdrs["X-Fixel-Token"] = token
        if origin is not None:
            hdrs["Origin"] = origin
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp.status, payload

    status, payload = await asyncio.to_thread(go)
    try:
        return status, json.loads(payload)
    except ValueError:
        return status, payload


async def test_page_is_served_and_url_carries_token(web):
    status, page = await call(web, "GET", "/", token=None)
    assert status == 200 and b"Fixel Playground" in page and b'sandbox="allow-scripts"' in page
    assert web.url == f"http://127.0.0.1:{web.port}/#T0KEN"


async def test_api_needs_the_token_and_our_origin(web):
    assert (await call(web, "GET", "/api/state", token=None))[0] == 403
    assert (await call(web, "GET", "/api/state", token="wrong"))[0] == 403
    assert (await call(web, "POST", "/api/run", {"lang": "python", "code": "1"}, origin="https://evil.example"))[0] == 403
    assert (await call(web, "POST", "/api/run", {"lang": "python", "code": "1"}, origin=web.origin))[0] == 200
    assert web.runs == [("1", "python", "")]


async def test_run_saves_scratch_and_reports_runner_errors(web, tmp_path):
    status, data = await call(web, "POST", "/api/run", {"lang": "python", "code": "print(1)", "stdin": "x"})
    assert status == 200 and data == {"exit_code": 0, "output": "ok\n", "seconds": 0.1}
    assert Scratch(tmp_path).load("python") == "print(1)"
    status, data = await call(web, "POST", "/api/run", {"lang": "java", "code": "x"})
    assert status == 200 and data["error"] is True and "isn't installed" in data["output"]
    assert (await call(web, "POST", "/api/run", {"lang": "html", "code": "<p>"}))[0] == 400


async def test_state_prefers_a_handoff_once_then_scratch(web, tmp_path):
    Scratch(tmp_path).save("javascript", "console.log(1)")
    web.hand_off("html", "<h1>clone</h1>")
    _, first = await call(web, "GET", "/api/state")
    _, second = await call(web, "GET", "/api/state")
    assert (first["lang"], first["code"]) == ("html", "<h1>clone</h1>")
    assert (second["lang"], second["code"]) == ("javascript", "console.log(1)")
    assert {"name": "cpp", "label": "C++", "runnable": True, "filename": "main.cpp"} in first["langs"]


async def test_scratch_endpoint_and_save(web):
    assert (await call(web, "POST", "/api/save", {"lang": "html", "code": "<p>saved</p>"}))[0] == 200
    _, data = await call(web, "GET", "/api/scratch?lang=html")
    assert data == {"lang": "html", "code": "<p>saved</p>"}
    assert (await call(web, "GET", "/api/scratch?lang=cobol"))[0] == 400


async def test_ask_hands_an_attachment_to_fixel(web):
    body = {"lang": "python", "code": "print(x)", "output": "NameError", "exit_code": 1, "ran": True}
    assert (await call(web, "POST", "/api/ask", body))[0] == 200
    await asyncio.sleep(0.05)  # on_ask runs on Fixel's loop
    (att,) = web.asked
    assert att.failed and att.code == "print(x)" and att.output == "NameError"


async def test_malformed_requests_get_400(web):
    assert (await call(web, "POST", "/api/run", raw=b"not json"))[0] == 400
    assert (await call(web, "POST", "/api/run", raw=b"[1, 2]"))[0] == 400
    assert (await call(web, "POST", "/api/run", {"lang": 5, "code": None}))[0] == 400
    assert (await call(web, "POST", "/api/run", raw=b"{}", headers={"Content-Length": "-1"}))[0] == 400
    assert (await call(web, "POST", "/api/nope", {}))[0] == 404


async def test_large_bodies_are_refused(web):
    status, _ = await call(web, "POST", "/api/save", raw=b"x" * (MAX_BODY + 1))
    assert status == 413


async def test_stop_frees_the_server(web):
    web.stop()
    assert not web.running
