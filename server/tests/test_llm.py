"""LLM client layer. No test here ever reaches the network or spends credits."""

from types import SimpleNamespace

import pytest

from retrack_server.config import Settings
from retrack_server.llm import AnthropicLLM, FakeLLM, LLMError, llm_from_settings

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def settings(**overrides) -> Settings:
    values = {"database_url": "unused", "key_pepper": "p"} | overrides
    return Settings(**values)


def fake_response(text='{"ok": true}', stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
        model="claude-haiku-5-5",
    )


@pytest.fixture
def stubbed(monkeypatch):
    """An AnthropicLLM whose SDK call is replaced by a stub that records the request."""
    llm = AnthropicLLM(api_key="sk-ant-test-not-real", model="claude-haiku-5-5", effort="low")
    stub = SimpleNamespace(calls=[], response=fake_response())

    def create(**kwargs):
        stub.calls.append(kwargs)
        return stub.response

    monkeypatch.setattr(llm._client.messages, "create", create)
    return llm, stub


def test_request_uses_structured_output_and_low_effort(stubbed):
    llm, stub = stubbed
    result = llm.generate_json(system="sys", user="data", schema=SCHEMA, max_tokens=500)

    assert result.data == {"ok": True}
    assert (result.input_tokens, result.output_tokens) == (120, 30)
    request = stub.calls[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["max_tokens"] == 500
    assert request["system"] == "sys"
    assert request["messages"] == [{"role": "user", "content": "data"}]
    assert request["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "low",
    }


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_stop_reasons_raise(stubbed, stop_reason):
    llm, stub = stubbed
    stub.response = fake_response(stop_reason=stop_reason)
    with pytest.raises(LLMError):
        llm.generate_json(system="s", user="u", schema=SCHEMA, max_tokens=100)


def test_invalid_json_raises(stubbed):
    llm, stub = stubbed
    stub.response = fake_response(text="not json")
    with pytest.raises(LLMError):
        llm.generate_json(system="s", user="u", schema=SCHEMA, max_tokens=100)


def test_llm_is_off_unless_explicitly_enabled():
    assert llm_from_settings(settings(anthropic_api_key="sk-ant-x")) is None
    assert llm_from_settings(settings(llm_enabled=True)) is None
    enabled = llm_from_settings(settings(anthropic_api_key="sk-ant-x", llm_enabled=True))
    assert isinstance(enabled, AnthropicLLM)


def test_settings_read_llm_switches_from_environment(monkeypatch):
    monkeypatch.setenv("SERVER_DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("RETRACK_KEY_PEPPER", "p")
    monkeypatch.setenv("RETRACK_LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    s = Settings.from_env()
    assert (s.llm_enabled, s.anthropic_api_key, s.llm_model, s.llm_effort) == (
        True,
        "sk-ant-x",
        "claude-haiku-5-5",
        "low",
    )
    monkeypatch.setenv("RETRACK_LLM_ENABLED", "no")
    assert Settings.from_env().llm_enabled is False


def test_fake_llm_replays_answers_and_records_calls():
    fake = FakeLLM([{"ok": True}, {"ok": False}])
    assert fake.generate_json(system="s", user="u1", schema=SCHEMA, max_tokens=10).data == {
        "ok": True
    }
    assert fake.generate_json(system="s", user="u2", schema=SCHEMA, max_tokens=10).data == {
        "ok": False
    }
    assert [c["user"] for c in fake.calls] == ["u1", "u2"]
