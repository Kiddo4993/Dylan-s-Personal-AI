"""/web: the browser playground. Serves one page and a small JSON API on 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .attachment import CodeAttachment
from .editor import RunFn
from .langs import LANGS, RUNNABLE
from .runner import RunnerError
from .scratch import Scratch

MAX_BODY = 1_000_000
PAGE = files(__package__) / "web" / "index.html"


class PlaygroundServer:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        scratch: Scratch,
        run: RunFn,
        on_ask: Callable[[CodeAttachment], None],
        *,
        token: str | None = None,
    ) -> None:
        self.loop = loop
        self.scratch = scratch
        self.token = token or secrets.token_urlsafe(32)
        self._run = run
        self._on_ask = on_ask
        self._handoff: tuple[str, str] | None = None
        self._httpd: ThreadingHTTPServer | None = None

    # ---- lifecycle (Fixel's loop)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.origin}/#{self.token}"  # a fragment: the browser never sends it by itself

    def start(self, port: int = 0) -> None:
        if self._httpd is not None:
            return
        handler = type("Handler", (_Handler,), {"playground": self})
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, name="fixel-web", daemon=True).start()
        self._httpd = httpd

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def hand_off(self, lang: str, code: str) -> None:
        """⌃P: the next page load opens this code instead of the scratch file."""
        self._handoff = (lang, code)

    # ---- API (server thread). Each returns (status, payload).

    def api_state(self, query: dict) -> tuple[int, dict]:
        if self._handoff is not None:
            (lang, code), self._handoff = self._handoff, None
        else:
            lang = self.scratch.last_lang(choices=tuple(LANGS))
            code = self.scratch.load(lang)
        langs = [
            {"name": name, "label": spec.label, "runnable": bool(spec.run), "filename": spec.filename}
            for name, spec in LANGS.items()
        ]
        return 200, {"lang": lang, "code": code, "langs": langs}

    def api_scratch(self, query: dict) -> tuple[int, dict]:
        lang = query.get("lang", [""])[0]
        if lang not in LANGS:
            return 400, {"error": f"Unknown language {lang!r}."}
        return 200, {"lang": lang, "code": self.scratch.load(lang)}

    def api_run(self, body: dict) -> tuple[int, dict]:
        lang, code, stdin = body["lang"], body["code"], body["stdin"]
        if lang not in RUNNABLE:
            return 400, {"error": f"{lang} runs in the preview, not the runner."}
        future = asyncio.run_coroutine_threadsafe(self._run(code, lang, stdin), self.loop)
        try:
            result = future.result()
        except RunnerError as e:
            return 200, {"exit_code": None, "output": str(e), "seconds": 0.0, "error": True}
        self.scratch.save(lang, code)
        return 200, {"exit_code": result.exit_code, "output": result.output, "seconds": round(result.seconds, 2)}

    def api_ask(self, body: dict) -> tuple[int, dict]:
        lang = body["lang"]
        if lang not in LANGS:
            return 400, {"error": f"Unknown language {lang!r}."}
        exit_code = body.get("exit_code")
        att = CodeAttachment(
            lang, body["code"], body["output"],
            exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
            ran=body.get("ran") is True,
        )
        self.loop.call_soon_threadsafe(self._on_ask, att)
        return 200, {"ok": True}

    def api_save(self, body: dict) -> tuple[int, dict]:
        if body["lang"] not in LANGS:
            return 400, {"error": f"Unknown language {body['lang']!r}."}
        self.scratch.save(body["lang"], body["code"])
        return 200, {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    playground: PlaygroundServer
    server_version = "Fixel"

    def log_message(self, format, *args) -> None:  # keep Fixel's terminal clean
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        routes = {"/api/state": self.playground.api_state, "/api/scratch": self.playground.api_scratch}
        route = routes.get(url.path)
        if route is None:
            self._json(404, {"error": "Not found."})
        elif self._allowed():
            self._json(*route(parse_qs(url.query)))

    def do_POST(self) -> None:
        routes = {"/api/run": self.playground.api_run, "/api/ask": self.playground.api_ask,
                  "/api/save": self.playground.api_save}
        route = routes.get(urlsplit(self.path).path)
        if route is None:
            self._json(404, {"error": "Not found."})
            return
        if not self._allowed():
            return
        body = self._read_body()
        if body is not None:
            self._json(*route(body))

    def _allowed(self) -> bool:
        token = self.headers.get("X-Fixel-Token", "")
        origin = self.headers.get("Origin")
        if not hmac.compare_digest(token.encode(), self.playground.token.encode()) or (
            origin is not None and origin != self.playground.origin
        ):
            self._json(403, {"error": "Open the playground from Fixel with /web."})
            return False
        return True

    def _read_body(self) -> dict | None:
        """The JSON body with string fields guaranteed, or None after sending an error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self._json(400, {"error": "Bad Content-Length."})
            return None
        if length > MAX_BODY:
            self.rfile.read(min(length, MAX_BODY * 2))  # read it first, or the client sees a broken pipe instead of 413
            self.close_connection = True
            self._json(413, {"error": "That's too much code for the playground (1 MB max)."})
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "Expected a JSON object."})
            return None
        for field in ("lang", "code", "stdin", "output"):
            value = body.get(field, "")
            if not isinstance(value, str):
                self._json(400, {"error": f"{field} must be text."})
                return None
            body[field] = value
        return body

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
