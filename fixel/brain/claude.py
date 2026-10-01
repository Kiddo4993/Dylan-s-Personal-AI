"""Claude via the official Anthropic SDK (streaming, prompt caching, adaptive thinking)."""

from __future__ import annotations

import base64
from typing import AsyncIterator

import anthropic

from .base import ProviderError, Turn


def to_messages(turns: list[Turn]) -> list[dict]:
    """Turns → Messages API params. One cache breakpoint on the newest block caches
    the system prompt plus every earlier screenshot for follow-up questions."""
    messages = []
    for turn in turns:
        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(img).decode()},
            }
            for img in turn.images
        ]
        content.append({"type": "text", "text": turn.text})
        messages.append({"role": turn.role, "content": content})
    if messages:
        messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return messages


class ClaudeProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 16000,
        thinking: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.name = model
        self.model = model
        self.max_tokens = max_tokens
        self.thinking = thinking
        # The SDK already retries 429 / 5xx / connection errors twice with backoff.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    async def stream(self, turns: list[Turn], system: str) -> AsyncIterator[str]:
        params: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system}],
            "messages": to_messages(turns),
        }
        if self.thinking:
            params["thinking"] = {"type": "adaptive"}
        try:
            async with self._client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic rejected the API key. Run `fixel setup`.", auth=True) from e
        except anthropic.NotFoundError as e:
            raise ProviderError(
                f"Model '{self.model}' wasn't found. Fix [models] in ~/.fixel/config.toml or run `fixel setup`."
            ) from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Anthropic is rate-limiting you (already retried). Wait a moment, then press Enter.") from e
        except anthropic.BadRequestError as e:
            hint = " (try `thinking = false` in ~/.fixel/config.toml)" if "thinking" in str(e.message).lower() else ""
            raise ProviderError(f"Anthropic rejected the request: {e.message}{hint}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("Can't reach Anthropic. Check your internet, then press Enter.") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic error {e.status_code}: {e.message}") from e
