import httpx
import pytest

import openai
from fixel.brain.base import ProviderError, Turn
from fixel.brain.openai import OpenAIProvider, to_messages
from fixel.setup import _check_openai


def test_to_messages_conversion():
    turns = [
        Turn("user", "Hello with image", images=[b"PNG_BYTES"]),
        Turn("assistant", "Hi there"),
        Turn("user", "Simple text question"),
    ]
    messages = to_messages(turns, "You are a helpful assistant.")
    assert len(messages) == 4
    assert messages[0] == {"role": "system", "content": "You are a helpful assistant."}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "image_url"
    assert "data:image/png;base64," in messages[1]["content"][0]["image_url"]["url"]
    assert messages[1]["content"][1] == {"type": "text", "text": "Hello with image"}
    assert messages[2] == {"role": "assistant", "content": "Hi there"}
    assert messages[3] == {"role": "user", "content": "Simple text question"}


class FakeChunk:
    def __init__(self, content):
        self.choices = [FakeChoice(content)] if content is not None else []


class FakeChoice:
    def __init__(self, content):
        self.delta = FakeDelta(content)


class FakeDelta:
    def __init__(self, content):
        self.content = content


class FakeCompletions:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or ["Hello ", "world!"]
        self.error = error
        self.last_params = None

    async def create(self, **params):
        self.last_params = params
        if self.error:
            raise self.error

        async def gen():
            for c in self.chunks:
                yield FakeChunk(c)

        return gen()


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAIClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


async def test_openai_provider_streaming():
    completions = FakeCompletions(["This ", "is ", "GPT-4o"])
    client = FakeOpenAIClient(completions)
    provider = OpenAIProvider("fake-key", "gpt-4o", client=client)

    chunks = [c async for c in provider.stream([Turn("user", "hi")], "system prompt")]
    assert "".join(chunks) == "This is GPT-4o"
    assert completions.last_params["model"] == "gpt-4o"
    assert "reasoning_effort" not in completions.last_params


async def test_openai_provider_deep_reasoning_for_o1():
    completions = FakeCompletions(["Deep answer"])
    client = FakeOpenAIClient(completions)
    provider = OpenAIProvider("fake-key", "o3-mini", client=client)

    chunks = [c async for c in provider.stream([Turn("user", "think")], "system prompt", deep=True)]
    assert "".join(chunks) == "Deep answer"
    assert completions.last_params["reasoning_effort"] == "high"


async def test_openai_provider_authentication_error():
    fake_response = httpx.Response(401, request=httpx.Request("POST", "http://fake"))
    error = openai.AuthenticationError("Invalid API key", response=fake_response, body=None)
    client = FakeOpenAIClient(FakeCompletions(error=error))
    provider = OpenAIProvider("fake-key", "gpt-4o", client=client)

    with pytest.raises(ProviderError) as exc_info:
        async for _ in provider.stream([Turn("user", "hi")], "sys"):
            pass

    assert exc_info.value.auth
    assert "OpenAI rejected the API key" in str(exc_info.value)


async def test_openai_provider_not_found_error():
    fake_response = httpx.Response(404, request=httpx.Request("POST", "http://fake"))
    error = openai.NotFoundError("Model not found", response=fake_response, body=None)
    client = FakeOpenAIClient(FakeCompletions(error=error))
    provider = OpenAIProvider("fake-key", "gpt-nonexistent", client=client)

    with pytest.raises(ProviderError) as exc_info:
        async for _ in provider.stream([Turn("user", "hi")], "sys"):
            pass

    assert "Model 'gpt-nonexistent' wasn't found" in str(exc_info.value)


def test_check_openai_success(monkeypatch):
    class FakeModels:
        def retrieve(self, model):
            return {"id": model}

    class FakeSyncClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr(openai, "OpenAI", FakeSyncClient)
    msg = _check_openai("fake-key", "gpt-4o")
    assert "Key works" in msg and "gpt-4o is available" in msg


def test_check_openai_invalid_key(monkeypatch):
    class FakeSyncClient:
        def __init__(self, **kwargs):
            fake_response = httpx.Response(401, request=httpx.Request("POST", "http://fake"))
            raise openai.AuthenticationError("Unauthorized", response=fake_response, body=None)

    monkeypatch.setattr(openai, "OpenAI", FakeSyncClient)
    msg = _check_openai("bad-key", "gpt-4o")
    assert "OpenAI rejected this key" in msg
