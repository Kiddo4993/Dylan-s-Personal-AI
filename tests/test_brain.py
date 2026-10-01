import pytest

import fixel.brain as brain
from fixel.brain import ProviderError, Turn, make_provider
from fixel.brain.claude import ClaudeProvider, to_messages
from fixel.brain.fake import FakeProvider
from fixel.brain.gemini import GeminiProvider, to_contents
from fixel.config import Config


def test_to_messages_puts_images_first_and_one_cache_point():
    turns = [
        Turn("user", "what?", [b"img1", b"img2"]),
        Turn("assistant", "MODE: general\nKEY:\n---\nok"),
        Turn("user", "more"),
    ]
    messages = to_messages(turns)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    first = messages[0]["content"]
    assert [block["type"] for block in first] == ["image", "image", "text"]
    assert first[0]["source"] == {"type": "base64", "media_type": "image/png", "data": "aW1nMQ=="}
    cached = [b for m in messages for b in m["content"] if "cache_control" in b]
    assert cached == [messages[-1]["content"][-1]]


def test_to_contents_maps_roles():
    contents = to_contents([Turn("user", "q", [b"i"]), Turn("assistant", "a")])
    assert [c.role for c in contents] == ["user", "model"]
    assert len(contents[0].parts) == 2
    assert contents[0].parts[1].text == "q"


async def test_fake_provider_streams_and_records():
    provider = FakeProvider(["MODE: math\nKEY: k\n---\nAnswer: 4"], chunk=3)
    out = "".join([c async for c in provider.stream([Turn("user", "2+2")], "sys")])
    assert out.endswith("Answer: 4")
    assert provider.calls[0][1] == "sys"


def test_make_provider_unknown_alias(tmp_path):
    with pytest.raises(ProviderError, match="Unknown model"):
        make_provider("gpt", Config(home=tmp_path))


def test_make_provider_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "get_api_key", lambda vendor: None)
    with pytest.raises(ProviderError) as excinfo:
        make_provider("sonnet", Config(home=tmp_path))
    assert excinfo.value.auth


def test_make_provider_picks_vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "get_api_key", lambda vendor: f"key-{vendor}")
    cfg = Config(home=tmp_path)
    opus = make_provider("opus", cfg)
    assert isinstance(opus, ClaudeProvider) and opus.name == "claude-opus-5-5"
    assert isinstance(make_provider("gemini", cfg), GeminiProvider)
