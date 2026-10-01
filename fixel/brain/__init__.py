"""Model providers. `make_provider` turns a config alias into a ready provider."""

from __future__ import annotations

from ..config import Config, get_api_key, provider_for_model
from .base import Provider, ProviderError, Turn

__all__ = ["Provider", "ProviderError", "Turn", "make_provider"]


def make_provider(alias: str, cfg: Config) -> Provider:
    if alias not in cfg.models:
        raise ProviderError(f"Unknown model '{alias}'. Choose one of: {', '.join(cfg.models)}.")
    model = cfg.models[alias]
    vendor = provider_for_model(model)
    key = get_api_key(vendor)
    if not key:
        label = "Gemini" if vendor == "gemini" else "Anthropic"
        raise ProviderError(f"No {label} API key yet. Run `fixel setup`.", auth=True)
    if vendor == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider(key, model)
    from .claude import ClaudeProvider

    return ClaudeProvider(key, model, max_tokens=cfg.max_tokens, thinking=cfg.thinking)
