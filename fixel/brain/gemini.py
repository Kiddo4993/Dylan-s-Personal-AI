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


def make_config(system: str):
    from google.genai import types

    # Fixel passes no tools, so turn off automatic function calling; otherwise the SDK
    # logs a warning into Fixel's window on every request.
    return types.GenerateContentConfig(
        system_instruction=system,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


class GeminiProvider:
    def __init__(self, api_key: str, model: str, *, client=None) -> None:
        from google import genai

        self.name = model
        self.model = model
        self._client = client or genai.Client(api_key=api_key)

    async def stream(self, turns: list[Turn], system: str) -> AsyncIterator[str]:
        from google.genai import errors

        config = make_config(system)
        contents = to_contents(turns)
        for attempt in range(3):
            yielded = False
            try:
                chunks = await self._client.aio.models.generate_content_stream(
                    model=self.model, contents=contents, config=config
                )
                async for chunk in chunks:
                    if chunk.text:
                        yielded = True
                        yield chunk.text
                return
            except errors.APIError as e:
                code = e.code or 0
                if (code == 429 or code >= 500) and attempt < 2 and not yielded:
                    await asyncio.sleep(2**attempt)
                    continue
                message = e.message or str(e)
                if code in (401, 403) or "api key" in message.lower():
                    raise ProviderError("Google rejected the Gemini API key. Run `fixel setup`.", auth=True) from e
                if code == 404:
                    raise ProviderError(f"Gemini model '{self.model}' wasn't found. Fix it in ~/.fixel/config.toml.") from e
                if code == 429:
                    raise ProviderError("Gemini's rate limit hit (the free tier is small). Wait a minute, then press Enter.") from e
                raise ProviderError(f"Gemini error {code}: {message}") from e
            except httpx.TransportError as e:
                raise ProviderError("Can't reach Google. Check your internet, then press Enter.") from e
