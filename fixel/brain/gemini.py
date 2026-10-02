"""Gemini via the google-genai SDK."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from .base import ProviderError, Turn


def to_contents(turns: list[Turn]) -> list:
    from google.genai import types

    return [
        types.Content(
            role="user" if turn.role == "user" else "model",
            parts=[
                *(types.Part.from_bytes(data=img, mime_type="image/png") for img in turn.images),
                types.Part.from_text(text=turn.text),
            ],
        )
        for turn in turns
    ]


def make_config(system: str, model: str = "", *, deep: bool = False):
    from google.genai import types

    # Gemini 3+ takes a thinking level: low answers fast, high is ⌃T "think harder".
    # Older models use a different knob, so leave them on their defaults.
    thinking = None
    if model.startswith("gemini-3"):
        thinking = types.ThinkingConfig(thinking_level="high" if deep else "low")
    # Fixel passes no tools, so turn off automatic function calling; otherwise the SDK
    # logs a warning into Fixel's window on every request.
    return types.GenerateContentConfig(
        system_instruction=system,
        thinking_config=thinking,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


class _Busy(Exception):
    """This model is overloaded or rate-limited and nothing was streamed yet: try the next one."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        fallbacks: list[str] | None = None,
        client=None,
        retry_delay: float = 1.0,
    ) -> None:
        from google import genai

        self.name = model
        self.model = model
        self.fallbacks = list(fallbacks or [])
        self.last_model = model  # the model that produced the latest answer
        self.retry_delay = retry_delay
        self._client = client or genai.Client(api_key=api_key)

    async def stream(self, turns: list[Turn], system: str, *, deep: bool = False) -> AsyncIterator[str]:
        contents = to_contents(turns)
        models = [self.model, *self.fallbacks]
        for index, model in enumerate(models):
            self.last_model = model
            try:
                async for text in self._stream_model(model, contents, system, deep):
                    yield text
                return
            except _Busy as busy:
                if index == len(models) - 1:
                    if busy.code == 429:
                        raise ProviderError("Gemini's rate limit hit (the free tier is small). Wait a minute, then press Enter.") from busy
                    raise ProviderError("Google's Gemini models are all busy right now. Wait a moment, then press Enter.") from busy

    async def _stream_model(self, model: str, contents: list, system: str, deep: bool) -> AsyncIterator[str]:
        """Stream one model, retrying once if it's busy. Raises _Busy only if nothing was streamed."""
        from google.genai import errors

        config = make_config(system, model, deep=deep)
        for attempt in range(2):
            yielded = False
            try:
                chunks = await self._client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config
                )
                async for chunk in chunks:
                    if chunk.text:
                        yielded = True
                        yield chunk.text
                return
            except errors.APIError as e:
                code = e.code or 0
                busy = code == 429 or code >= 500
                if busy and not yielded:
                    if attempt == 0:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    raise _Busy(code) from e
                message = e.message or str(e)
                if code in (401, 403) or "api key" in message.lower():
                    raise ProviderError("Google rejected the Gemini API key. Run `fixel setup`.", auth=True) from e
                if code == 404:
                    raise ProviderError(f"Gemini model '{model}' wasn't found. Fix it in ~/.fixel/config.toml.") from e
                if busy:
                    raise ProviderError(f"Gemini ({model}) stopped mid-answer because it got busy. Press Enter to retry.") from e
                raise ProviderError(f"Gemini error {code}: {message}") from e
            except httpx.TransportError as e:
                raise ProviderError("Can't reach Google. Check your internet, then press Enter.") from e
