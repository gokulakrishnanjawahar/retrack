"""Assertion checks used by `retrack test`."""

from retrack.evals import check

STEPS = [
    {"type": "llm"},
    {"type": "tool", "tool_name": "orders_api", "result_class": "ok"},
    {"type": "tool", "tool_name": "check_delivery", "result_class": "ok"},
    {"type": "tool", "tool_name": "refunds_api", "result_class": "error", "error_class": "Timeout"},
    {"type": "tool", "tool_name": "refunds_api", "result_class": "ok"},
]


def run(assertions, completed=True, steps=STEPS, output="Refunded order 42"):
    return check(assertions, completed=completed, steps=steps, output=output)


def test_completes():
    assert run([{"type": "completes"}]) == []
    assert run([{"type": "completes"}], completed=False) == ["the agent raised an error"]


def test_tool_sequence_is_an_ordered_subsequence():
    assert run([{"type": "tool_sequence", "tools": ["orders_api", "refunds_api"]}]) == []
    [message] = run([{"type": "tool_sequence", "tools": ["refunds_api", "orders_api"]}])
    assert "refunds_api -> orders_api" in message


def test_no_failure():
    assert run([{"type": "no_failure", "tool": "orders_api", "error_class": "Timeout"}]) == []
    [message] = run([{"type": "no_failure", "tool": "refunds_api", "error_class": "Timeout"}])
    assert "refunds_api failed with Timeout" in message


def test_output_contains():
    assert run([{"type": "output_contains", "value": "Refunded"}]) == []
    assert run([{"type": "output_contains", "value": "Cancelled"}]) != []
    assert run([{"type": "output_contains", "value": "x"}], output=None) != []


def test_unknown_assertions_are_skipped_not_failed():
    assert run([{"type": "llm_judge", "criteria": "polite"}]) == []
