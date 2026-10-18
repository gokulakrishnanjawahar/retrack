"""Provider-agnostic LLM access (docs/architecture.md, "Provider-agnostic models").

Retrack's own model is Claude Haiku 5.5 (docs/decisions.md). Calls are made only when
the LLM is explicitly enabled (RETRACK_LLM_ENABLED=true) and a key is present; tests
use FakeLLM and never see a real key.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from retrack_server.config import Settings


class LLMError(Exception):
    """The model did not return a usable answer (refusal, truncation, invalid JSON)."""


@dataclass(frozen=True)
class LLMResponse:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(self, *, api_key: str, model: str, effort: str, timeout_seconds: float = 30.0):
        self.model = model
        self.effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": schema},
                "effort": self.effort,
            },
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LLMError(f"model stopped with {response.stop_reason}")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("model returned invalid JSON") from exc
        return LLMResponse(
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )


@dataclass
class FakeLLM:
    """Scripted answers for tests and local development; costs nothing."""

    answers: list[dict[str, Any] | Exception]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "schema": schema})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(data=answer, input_tokens=100, output_tokens=20, model="fake")


def llm_from_settings(settings: Settings) -> LLMClient | None:
    """The configured LLM, or None when it is not explicitly enabled with a key."""
    if not (settings.llm_enabled and settings.anthropic_api_key):
        return None
    return AnthropicLLM(
        api_key=settings.anthropic_api_key, model=settings.llm_model, effort=settings.llm_effort
    )
