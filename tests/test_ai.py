from types import SimpleNamespace

import pytest

from bot.services.ai import AIClient, AIDisabled


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def resp(stop, text="hi"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


def make(responses):
    ai = AIClient("sk-test", "claude-opus-5", "medium", True)
    fake = FakeMessages(responses)
    ai._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return ai, fake


async def test_request_shape():
    ai, fake = make([resp("end_turn", "hello")])
    assert await ai.chat([], "hey") == "hello"
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["tools"][0]["type"] == "web_search_20260209"
    assert kw["messages"] == [{"role": "user", "content": "hey"}]


async def test_pause_turn_is_resumed():
    ai, fake = make([resp("pause_turn", ""), resp("end_turn", "done")])
    assert await ai.chat([], "q") == "done"
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"


async def test_refusal():
    ai, _ = make([resp("refusal", "")])
    assert "can't help" in await ai.chat([], "q")


async def test_disabled_without_key():
    with pytest.raises(AIDisabled):
        await AIClient("", "m", "low", False).chat([], "q")
