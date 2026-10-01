"""Deterministic provider for tests: replays canned replies in small chunks."""

from __future__ import annotations

from typing import AsyncIterator

from .base import Turn

DEFAULT_REPLY = "MODE: general\nKEY:\n---\nok"


class FakeProvider:
    def __init__(
        self,
        replies: list[str] | None = None,
        *,
        chunk: int = 7,
        error: Exception | None = None,
        error_after: int = 0,
    ) -> None:
        self.name = "fake"
        self.replies = list(replies or [])
        self.chunk = chunk
        self.error = error
        self.error_after = error_after  # chunks to yield before raising `error`
        self.calls: list[tuple[list[Turn], str]] = []

    async def stream(self, turns: list[Turn], system: str) -> AsyncIterator[str]:
        self.calls.append((list(turns), system))
        reply = self.replies.pop(0) if self.replies else DEFAULT_REPLY
        for sent, start in enumerate(range(0, len(reply), self.chunk)):
            if self.error is not None and sent >= self.error_after:
                raise self.error
            yield reply[start : start + self.chunk]
        if self.error is not None:
            raise self.error
