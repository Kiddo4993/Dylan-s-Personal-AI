"""What every model provider looks like to the rest of Fixel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str
    images: list[bytes] = field(default_factory=list)  # PNG bytes


class ProviderError(Exception):
    """A model failure worth showing the user. `auth` means the key is missing or rejected."""

    def __init__(self, message: str, *, auth: bool = False) -> None:
        super().__init__(message)
        self.auth = auth


class Provider(Protocol):
    name: str  # the configured model
    last_model: str  # the model that actually produced the latest answer (may be a busy-fallback)

    def stream(self, turns: list[Turn], system: str, *, deep: bool = False) -> AsyncIterator[str]:
        """Stream reply text. `deep` asks for maximum thinking (/deeper)."""
        ...
