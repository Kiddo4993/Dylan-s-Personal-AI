import pytest

from fixel import app as app_module
from fixel.app import FixelApp
from fixel.brain.fake import FakeProvider
from fixel.casefile import CaseFile
from fixel.config import Config, detect_vendor, mask_key, provider_for_model
from fixel.ui import UI


def make_app(tmp_path, console, provider=None):
    cfg = Config(home=tmp_path, notes_dir=tmp_path / "notes")
    app = FixelApp(
        cfg,
        UI(console),
        provider_factory=lambda alias, cfg: provider or FakeProvider(),
        casefile=CaseFile(tmp_path / "c.db"),
    )
    if provider:
        app.select_model("sonnet")
    return app


def test_detect_vendor():
    assert detect_vendor("sk-ant-api03-123456789") == "anthropic"
    assert detect_vendor("AIzaSyAbcd1234efgh") == "gemini"
    assert detect_vendor("sk-proj-987654321") == "openai"
    assert detect_vendor("sk-regular-openai-key") == "openai"
    assert detect_vendor("some-random-key") is None


def test_mask_key():
    assert mask_key("short") == "***"
    assert mask_key("123456789012") == "123...012"
    assert mask_key("sk-ant-api03-123456789abcdef") == "sk-ant-...cdef"


def test_provider_for_model():
    assert provider_for_model("gpt-4o") == "openai"
    assert provider_for_model("o1-mini") == "openai"
    assert provider_for_model("o3-mini") == "openai"
    assert provider_for_model("chatgpt-4o-latest") == "openai"
    assert provider_for_model("gemini-3.6-flash") == "gemini"
    assert provider_for_model("claude-sonnet-5-5") == "anthropic"


async def test_api_command_with_vendor_and_key(tmp_path, console, monkeypatch):
    saved_keys = {}
    monkeypatch.setattr(app_module, "set_api_key", lambda v, k: saved_keys.update({v: k}))
    monkeypatch.setattr(app_module, "check_api_key", lambda v, k, m: f"Mock check for {v}: ok")

    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_command("/api anthropic sk-ant-secret123")

    assert saved_keys.get("anthropic") == "sk-ant-secret123"
    out = console.file.getvalue()
    assert "Saved Anthropic API key" in out
    assert "Mock check for anthropic: ok" in out


async def test_api_command_with_direct_key_auto_detects(tmp_path, console, monkeypatch):
    saved_keys = {}
    monkeypatch.setattr(app_module, "set_api_key", lambda v, k: saved_keys.update({v: k}))
    monkeypatch.setattr(app_module, "check_api_key", lambda v, k, m: f"Checked {v}")

    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_command("/api AIzaSyGoogleKey123")

    assert saved_keys.get("gemini") == "AIzaSyGoogleKey123"
    assert "Saved Google Gemini API key" in console.file.getvalue()


async def test_api_command_unknown_vendor(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_command("/api mysterious_ai")
    assert "Unknown provider or unrecognized key format" in console.file.getvalue()


async def test_api_command_interactive_selection(tmp_path, console, monkeypatch):
    saved_keys = {}
    monkeypatch.setattr(app_module, "set_api_key", lambda v, k: saved_keys.update({v: k}))
    monkeypatch.setattr(app_module, "check_api_key", lambda v, k, m: "OpenAI check passed")

    app = make_app(tmp_path, console, FakeProvider())

    inputs = ["openai", "sk-proj-my-openai-key"]

    async def fake_ask_input(prompt, **kwargs):
        return inputs.pop(0) if inputs else ""

    app.ui.ask_input = fake_ask_input
    await app.handle_command("/api")

    assert saved_keys.get("openai") == "sk-proj-my-openai-key"
    out = console.file.getvalue()
    assert "AI Provider API Keys" in out
    assert "Saved OpenAI API key" in out
    assert "OpenAI is ready! Switch to it anytime with `/model gpt`" in out


async def test_api_command_hides_the_pasted_key(tmp_path, console, monkeypatch):
    monkeypatch.setattr(app_module, "set_api_key", lambda v, k: None)
    monkeypatch.setattr(app_module, "check_api_key", lambda v, k, m: "ok")
    app = make_app(tmp_path, console, FakeProvider())
    calls = []

    async def fake_ask_input(prompt, **kwargs):
        calls.append(kwargs)
        return "sk-ant-api03-hidden"

    app.ui.ask_input = fake_ask_input
    await app.handle_command("/api anthropic")

    assert calls == [{"is_password": True}]


async def test_api_command_unknown_token_is_not_echoed(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    await app.handle_command("/api xq-9f8a7b6c5d4e3f2a1b0c")
    out = console.file.getvalue()
    assert "Unknown provider or unrecognized key format" in out
    assert "9f8a7b6c5d4e3f2a1b0c" not in out


async def test_api_command_cancelled_provider(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    async def empty_input(*args, **kwargs): return ""
    app.ui.ask_input = empty_input
    await app.handle_command("/api")
    assert "Saved to the macOS Keychain" not in console.file.getvalue()


async def test_api_command_cancelled_key(tmp_path, console):
    app = make_app(tmp_path, console, FakeProvider())
    async def empty_input(*args, **kwargs): return ""
    app.ui.ask_input = empty_input
    await app.handle_command("/api anthropic")
    assert "Cancelled. No key saved." in console.file.getvalue()


async def test_api_initializes_unloaded_provider(tmp_path, console, monkeypatch):
    monkeypatch.setattr(app_module, "set_api_key", lambda v, k: None)
    monkeypatch.setattr(app_module, "check_api_key", lambda v, k, m: "✔ Key works")

    provider = FakeProvider()
    app = make_app(tmp_path, console, provider=None)
    assert app.provider is None

    app._provider_factory = lambda alias, cfg: provider
    await app.handle_command("/api anthropic sk-ant-working-key")

    assert app.provider is not None
    assert "ready to use!" in console.file.getvalue()


def test_help_lists_api_command(console):
    UI(console).help()
    assert "/api" in console.file.getvalue()
