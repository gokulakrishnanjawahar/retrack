"""What tools returned: captured, stripped of secrets, truncated, and errors detected."""

import json
from typing import TypedDict

import httpx
import pytest
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from retrack import Retrack
from retrack.capture import reported_error

API_KEY = "rtk_test_" + "0" * 48


class State(TypedDict):
    done: bool


def run_tools(*tools_and_args):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(202)

    rt = Retrack(
        api_key=API_KEY,
        agent="a",
        base_url="https://retrack.test",
        transport=httpx.MockTransport(handler),
    )

    def act(state: State) -> dict:
        for fn, args in tools_and_args:
            fn.invoke(args)
        return {"done": True}

    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke({"done": False}, config={"callbacks": [rt.callback(task="t")]})
    rt.flush(timeout=2)
    return captured[0]["steps"]


@tool
def lookup(order_id: str) -> str:
    """Look up an order."""
    return f"order {order_id}: damaged, paid with key sk_live_51HxAbCdEfGhIjKlMnOpQr"


@tool
def charge(order_id: str) -> dict:
    """Charge a card."""
    return {"error": "card declined", "status": 402}


@tool
def report(order_id: str) -> str:
    """Make a long report."""
    return "r" * 5000


def test_tool_result_is_captured_without_secrets():
    step = run_tools((lookup, {"order_id": "1"}))[0]
    assert step["result"] == "order 1: damaged, paid with key <SECRET>"
    assert step["result_class"] == "ok"


def test_returned_errors_mark_the_step_as_failed():
    step = run_tools((charge, {"order_id": "1"}))[0]
    assert (step["result_class"], step["error_class"]) == ("error", "ReportedError")
    assert json.loads(step["result"]) == {"error": "card declined", "status": 402}


def test_long_results_are_truncated():
    assert len(run_tools((report, {"order_id": "1"}))[0]["result"]) == 1000


@pytest.mark.parametrize(
    ("output", "is_error"),
    [
        ({"error": "x"}, True),
        ({"errors": ["x"]}, True),
        ({"status": 500}, True),
        ({"status_code": 404}, True),
        ({"ok": False}, True),
        ({"success": False}, True),
        ("Error: tool failed", True),
        ({"status": 200, "error": None}, False),
        ({"ok": True}, False),
        ("all good", False),
        (None, False),
    ],
)
def test_reported_error_detection(output, is_error):
    assert reported_error(output) is is_error
