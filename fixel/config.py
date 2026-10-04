"""Settings (~/.fixel/config.toml) and API keys (macOS Keychain)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import keyring

KEYRING_SERVICE = "fixel"
ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}

DEFAULT_CONFIG_TOML = """\
# Fixel settings. Delete a line to fall back to its default.
# name = "Dylan"                # how the homepage greets you (default: your Mac account's first name)
default_model = "sonnet"        # sonnet | opus | gemini
notes_dir = "~/Fixel Notes"
recall_threshold = 0.6          # 0-1: how much of a past problem must be on screen for Fixel to reuse it
double_tap_window = 0.4         # seconds allowed between Right Option taps
thinking = false                # Claude: think on every answer (slower). /deeper always thinks harder.
max_tokens = 16000
animations = true               # Pix's thinking face and the startup moment
gemini_fallbacks = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]   # tried in order when Gemini is busy
slow_model_seconds = 20         # no words after this long? try the next Gemini model (/deeper allows 3x)

[models]
sonnet = "claude-sonnet-5-5"
opus = "claude-opus-5-5"
gemini = "gemini-3.6-flash"
"""


def _default_models() -> dict[str, str]:
    return {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "gemini": "gemini-3.6-flash"}


@dataclass
class Config:
    home: Path
    name: str | None = None
    default_model: str = "sonnet"
    notes_dir: Path = field(default_factory=lambda: Path.home() / "Fixel Notes")
    recall_threshold: float = 0.6
    double_tap_window: float = 0.4
    thinking: bool = False
    max_tokens: int = 16000
    animations: bool = True
    gemini_fallbacks: list[str] = field(default_factory=lambda: ["gemini-3.5-flash", "gemini-3.5-flash-lite"])
    slow_model_seconds: float = 20.0
    models: dict[str, str] = field(default_factory=_default_models)

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def shots_dir(self) -> Path:
        return self.home / "shots"

    @property
    def casefile_path(self) -> Path:
        return self.home / "casefile.db"

    @property
    def about_me_path(self) -> Path:
        return self.home / "about-me.md"


def fixel_home() -> Path:
    return Path(os.environ.get("FIXEL_HOME", Path.home() / ".fixel")).expanduser()


def load_config(home: Path | None = None) -> Config:
    cfg = Config(home=home or fixel_home())
    if cfg.config_path.exists():
        data = tomllib.loads(cfg.config_path.read_text())
        for name in ("name", "default_model", "recall_threshold", "double_tap_window", "thinking", "max_tokens", "animations", "gemini_fallbacks", "slow_model_seconds"):
            if name in data:
                setattr(cfg, name, data[name])
        if "notes_dir" in data:
            cfg.notes_dir = Path(data["notes_dir"]).expanduser()
        cfg.models = {**cfg.models, **data.get("models", {})}
    return cfg


def write_default_config(cfg: Config) -> bool:
    """Create config.toml if it's missing. Returns True if it was created."""
    if cfg.config_path.exists():
        return False
    cfg.home.mkdir(parents=True, exist_ok=True)
    cfg.config_path.write_text(DEFAULT_CONFIG_TOML)
    return True


def provider_for_model(model_id: str) -> str:
    return "gemini" if model_id.startswith("gemini") else "anthropic"


def get_api_key(vendor: str) -> str | None:
    return os.environ.get(ENV_VARS[vendor]) or keyring.get_password(KEYRING_SERVICE, vendor)


def set_api_key(vendor: str, key: str) -> None:
    keyring.set_password(KEYRING_SERVICE, vendor, key)
