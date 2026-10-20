"""Known-fix recovery, circuit breaker and plan replay in the SDK (Phase 11)."""

import json
import uuid
from typing import TypedDict

import httpx
import pytest
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from retrack import Memory, Retrack
from retrack.recovery import KnownFailureError, UnrecoverableToolError, fingerprint

# Same values as server/tests/test_distill_helpers.py: SDK and server must agree.
SHARED_VECTORS = [
    (
        ("refunds_api", "ReportedError", {"order_id": "42", "amount_paise": 129900}),
        "36cbb4a457bf8c25f6813b3fb5954042",
    ),
    (("orders_api", "TimeoutError", {}), "119791be4d6eae6cec2db0b065fd2b43"),
    (
        (
            "email_api",
            "ValueError",
            {"to": "x", "cc": ["a"], "meta": {"urgent": True, "n": 1.5, "x": None}},
        ),
        "9e083667ab314636aa376aaa0cc5d900",
    ),
]


def test_fingerprints_match_the_server():
    for args, expected in SHARED_VECTORS:
        assert fingerprint(*args) == expected


@tool
def refunds_api(order_id: str, amount_paise: int) -> dict:
    """Refund an order."""
    return {"error": "delivery not verified", "status": 409}


@tool
def flaky_api(order_id: str) -> str:
    """Times out."""
    raise TimeoutError("upstream timed out")


@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return "delivered"


ARGS = {"order_id": "42", "amount_paise": 129900}


def memory_with(*warnings):
    return Memory(warnings=list(warnings))


def warning(tool_name, error, args, recovery=None, unrecoverable=False):
    return {
        "fingerprint": fingerprint(tool_name, error, args),
        "tool": tool_name,
        "recovery": recovery,
        "unrecoverable": unrecoverable,
    }


def test_known_fix_is_added_to_a_returned_error():
    memory = memory_with(
        warning(
            "refunds_api",
            "ReportedError",
            ARGS,
            recovery="call check_delivery, then retry refunds_api",
        )
    )
    [protected] = memory.protect([refunds_api])
    result = protected.invoke(ARGS)
    assert result["error"] == "delivery not verified"
    assert result["known_fix"] == "call check_delivery, then retry refunds_api"


def test_known_fix_is_added_to_a_raised_error():
    memory = memory_with(
        warning(
            "flaky_api",
            "TimeoutError",
            {"order_id": "1"},
            recovery="call status_api, then retry flaky_api",
        )
    )
    [protected] = memory.protect([flaky_api])
    with pytest.raises(KnownFailureError) as caught:
        protected.invoke({"order_id": "1"})
    assert "call status_api" in str(caught.value)
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_unrecoverable_failures_stop_immediately():
    memory = memory_with(
        warning("flaky_api", "TimeoutError", {"order_id": "1"}, unrecoverable=True)
    )
    [protected] = memory.protect([flaky_api])
    with pytest.raises(UnrecoverableToolError):
        protected.invoke({"order_id": "1"})


def test_the_same_unknown_failure_three_times_trips_the_breaker():
    [protected] = Memory().protect([flaky_api])
    for _ in range(2):
        with pytest.raises(TimeoutError):
            protected.invoke({"order_id": "1"})
    with pytest.raises(UnrecoverableToolError):
        protected.invoke({"order_id": "1"})


def test_unknown_returned_errors_pass_through_unchanged():
    [protected] = Memory().protect([refunds_api])
    assert protected.invoke(ARGS) == {"error": "delivery not verified", "status": 409}


def test_successes_and_tool_metadata_are_unchanged():
    [protected] = Memory().protect([orders_api])
    assert protected.invoke({"order_id": "1"}) == "delivered"
    assert (protected.name, protected.description) == (orders_api.name, orders_api.description)


def test_protected_tools_are_captured_once_per_call():
    captured = []
    rt = Retrack(
        agent="a",
        api_key="rtk_test_" + "0" * 48,
        base_url="https://retrack.test",
        transport=httpx.MockTransport(
            lambda r: captured.append(json.loads(r.content)) or httpx.Response(202)
        ),
    )
    [protected] = Memory().protect([orders_api])

    class State(TypedDict):
        x: int

    def act(state):
        protected.invoke({"order_id": "1"})
        return {}

    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke({"x": 1}, config={"callbacks": [rt.callback(task="t")]})
    rt.flush(timeout=2)
    assert [s["tool_name"] for s in captured[0]["steps"]] == ["orders_api"]


# Plan replay ----------------------------------------------------------------------------


def test_replay_plan_is_parsed_from_recall():
    memory = Memory.from_response(
        {
            "playbooks": [],
            "warnings": [],
            "replay_eligible": True,
            "replay_plan": {"playbook_id": "p1", "version": 3, "steps": [{"tool": "orders_api"}]},
        }
    )
    assert memory.replay_plan["playbook_id"] == "p1"
    assert Memory().replay_plan is None


def test_runs_report_which_plan_they_replayed():
    captured = []
    rt = Retrack(
        agent="a",
        api_key="rtk_test_" + "0" * 48,
        base_url="https://retrack.test",
        transport=httpx.MockTransport(
            lambda r: captured.append(json.loads(r.content)) or httpx.Response(202)
        ),
    )
    playbook_id = str(uuid.uuid4())

    class State(TypedDict):
        x: int

    graph = StateGraph(State)
    graph.add_node("act", lambda state: {})
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke(
        {"x": 1}, config={"callbacks": [rt.callback(task="t", replay_of=playbook_id)]}
    )
    rt.flush(timeout=2)
    assert captured[0]["replay_of"] == playbook_id
