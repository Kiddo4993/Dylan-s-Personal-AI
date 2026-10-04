"""OpenAI via the official openai SDK (streaming, vision support)."""

from __future__ import annotations

import base64
from typing import AsyncIterator

import openai

from .base import ProviderError, Turn


def to_messages(turns: list[Turn], system: str) -> list[dict]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for turn in turns:
        if turn.images:
            content: list[dict] = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(img).decode()}"},
                }
                for img in turn.images
            ]
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            messages.append({"role": turn.role, "content": content})
        else:
            messages.append({"role": turn.role, "content": turn.text})
    return messages


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self.name = model
        self.model = model
        self.last_model = model
        self._client = client or openai.AsyncOpenAI(api_key=api_key, max_retries=2)

    def build_params(self, turns: list[Turn], system: str, *, deep: bool = False) -> dict:
        messages = to_messages(turns, system)
        params: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if deep and any(m in self.model.lower() for m in ("o1", "o3", "o4")):
            params["reasoning_effort"] = "high"
        return params

    async def stream(self, turns: list[Turn], system: str, *, deep: bool = False) -> AsyncIterator[str]:
        params = self.build_params(turns, system, deep=deep)
        try:
            response = await self._client.chat.completions.create(**params)
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.AuthenticationError as e:
            raise ProviderError("OpenAI rejected the API key. Run `/api openai`.", auth=True) from e
        except openai.NotFoundError as e:
            raise ProviderError(
                f"Model '{self.model}' wasn't found. Fix [models] in ~/.fixel/config.toml or run `/api openai`."
            ) from e
        except openai.RateLimitError as e:
            raise ProviderError("OpenAI is rate-limiting you (already retried). Wait a moment, then press Enter.") from e
        except openai.BadRequestError as e:
            raise ProviderError(f"OpenAI rejected the request: {e.message}") from e
        except openai.APIConnectionError as e:
            raise ProviderError("Can't reach OpenAI. Check your internet, then press Enter.") from e
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI error {e.status_code}: {e.message}") from e
