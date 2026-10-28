"""The one place /canvas touches the network: a tiny urllib wrapper that tests replace with a fake."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlsplit

# (method, url, headers, body) -> (status, headers, body)
Fetch = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]


class HTTPFailure(Exception):
    """The request never got an answer (offline, DNS, timeout)."""


def host(url: str) -> str:
    """Just the host, for messages: a calendar-feed URL carries a secret, so it's never shown in full."""
    return urlsplit(url).netloc or "the server"


def urlopen_fetch(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as e:  # a real answer, just not a 2xx one
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise HTTPFailure(f"Couldn't reach {host(url)} ({reason}).") from None
