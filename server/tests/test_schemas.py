import pytest
from pydantic import ValidationError

from retrack_server.schemas import MAX_STEPS, RunIn


def test_valid_payload_parses(run_payload):
    run = RunIn.model_validate(run_payload())
    assert run.agent == "support-agent"
    assert run.steps[1].tool_name == "orders_api"


def test_minimal_payload_uses_safe_defaults(run_payload):
    full = run_payload()
    run = RunIn.model_validate(
        {k: full[k] for k in ("id", "agent", "task", "model_id")}
        | {"steps": [{"idx": 0, "type": "tool", "tool_name": "x"}]}
    )
    assert run.tool_versions == {}
    assert run.tokens_in == 0
    assert run.steps[0].input_trust == "untrusted"


def test_unknown_fields_are_ignored_for_newer_sdks(run_payload):
    assert RunIn.model_validate(run_payload(new_field=1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "not-a-uuid"},
        {"agent": ""},
        {"agent": "has spaces"},
        {"task": ""},
        {"model_id": ""},
        {"tokens_in": -1},
        {"cost_usd": -0.1},
        {"outcome_hint": {"outcome": "success", "source": "judge"}},
        {"outcome_hint": {"outcome": "great", "source": "test"}},
        {"steps": [{"idx": 0, "type": "browser"}]},
        {"steps": [{"idx": 0, "type": "tool", "input_trust": "maybe"}]},
        {"steps": [{"idx": 0, "type": "llm"}, {"idx": 0, "type": "llm"}]},
        {"steps": [{"idx": i, "type": "llm"} for i in range(MAX_STEPS + 1)]},
    ],
)
def test_invalid_payloads_rejected(run_payload, overrides):
    with pytest.raises(ValidationError):
        RunIn.model_validate(run_payload(**overrides))
