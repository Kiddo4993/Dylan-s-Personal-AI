from pathlib import Path

import fixel.config as config
from fixel.config import Config, get_api_key, load_config, provider_for_model, write_default_config


def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.default_model == "sonnet"
    assert cfg.models["sonnet"] == "claude-sonnet-5-5"
    assert cfg.shots_dir == tmp_path / "shots"
    assert cfg.casefile_path == tmp_path / "casefile.db"


def test_default_file_matches_dataclass_defaults(tmp_path):
    cfg = Config(home=tmp_path)
    assert write_default_config(cfg) is True
    assert write_default_config(cfg) is False
    assert load_config(tmp_path) == Config(home=tmp_path)


def test_file_overrides(tmp_path):
    (tmp_path / "config.toml").write_text(
        'default_model = "gemini"\nnotes_dir = "~/X"\n[models]\ngemini = "gemini-9"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.default_model == "gemini"
    assert cfg.notes_dir == Path.home() / "X"
    assert cfg.models["gemini"] == "gemini-9"
    assert cfg.models["sonnet"] == "claude-sonnet-5-5"


def test_env_key_beats_keychain(monkeypatch):
    monkeypatch.setattr(config.keyring, "get_password", lambda service, user: "from-keychain")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert get_api_key("anthropic") == "from-env"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert get_api_key("anthropic") == "from-keychain"


def test_provider_for_model():
    assert provider_for_model("gemini-2.5-flash") == "gemini"
    assert provider_for_model("claude-sonnet-5-5") == "anthropic"


def test_playground_settings(tmp_path):
    from fixel.config import load_config

    (tmp_path / "config.toml").write_text("playground_timeout = 3\n")
    cfg = load_config(tmp_path)
    assert cfg.playground_timeout == 3 and cfg.playground_dir == tmp_path / "playground"
