"""Request and response shapes of the public API (see docs/api.md)."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

MAX_BODY_BYTES = 1_000_000
MAX_STEPS = 500
MAX_OUTPUT_CHARS = 4000

AgentName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class OutcomeHint(BaseModel):
    outcome: Literal["success", "failure"]
    source: Literal["test", "feedback", "event"]


class StepIn(BaseModel):
    idx: NonNegativeInt
    type: Literal["llm", "tool"]
    tool_name: ShortText | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    result_class: ShortText | None = None
    error_class: ShortText | None = None
    latency_ms: NonNegativeInt | None = None
    tokens_in: NonNegativeInt | None = None
    tokens_out: NonNegativeInt | None = None
    input_trust: Literal["trusted", "untrusted"] = "untrusted"


class RunIn(BaseModel):
    id: UUID
    agent: AgentName
    task: Annotated[str, StringConstraints(min_length=1, max_length=50_000)]
    model_id: ShortText
    tool_versions: dict[ShortText, ShortText] = Field(default_factory=dict, max_length=100)
    tokens_in: NonNegativeInt = 0
    tokens_out: NonNegativeInt = 0
    cost_usd: Annotated[float, Field(ge=0)] | None = None
    latency_ms: NonNegativeInt | None = None
    outcome_hint: OutcomeHint | None = None
    # The agent's final answer; redacted and truncated to MAX_OUTPUT_CHARS when stored.
    output: Annotated[str, StringConstraints(max_length=200_000)] | None = None
    steps: list[StepIn] = Field(default_factory=list, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def step_indexes_unique(self) -> "RunIn":
        indexes = [step.idx for step in self.steps]
        if len(indexes) != len(set(indexes)):
            raise ValueError("step idx values must be unique")
        return self


MAX_FEEDBACK_BYTES = 16_000


class FeedbackIn(BaseModel):
    run_id: UUID
    outcome: Literal["success", "failure"]
    source: Literal["test", "feedback", "event"]
    detail: dict[str, Any] = Field(default_factory=dict)
