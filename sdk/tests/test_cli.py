"""`retrack test`: run memory-derived regression cases against the customer's agent."""

import json
import textwrap

import httpx
import pytest

from retrack.cli import main

AGENT_MODULE = '''
from typing import TypedDict
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return "delivered"

@tool
def refunds_api(order_id: str) -> dict:
    """Refund an order."""
    return {"refund_id": "rf_1"}

class State(TypedDict):
    task: str

def run_task(task, callbacks):
    def act(state):
        orders_api.invoke({"order_id": "1"})
        if "broken" in state["task"]:
            raise RuntimeError("agent crashed")
        if "refund" in state["task"]:
            refunds_api.invoke({"order_id": "1"})
        return {}
    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke({"task": task}, config={"callbacks": callbacks})
    return "done"
'''


def case(case_id, task, assertions, critical=False, last=None):
    return {
        "id": case_id,
        "source": "playbook",
        "input": {"task": task},
        "assertions": assertions,
        "critical": critical,
        "last_result": last,
    }


SEQ = [{"type": "completes"}, {"type": "tool_sequence", "tools": ["orders_api", "refunds_api"]}]


@pytest.fixture
def agent_module(tmp_path, monkeypatch):
    (tmp_path / "my_agent.py").write_text(textwrap.dedent(AGENT_MODULE))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("RETRACK_API_KEY", "rtk_test_" + "0" * 48)
    monkeypatch.setenv("RETRACK_BASE_URL", "https://retrack.test")


def server(cases):
    posted = []

    def handler(request):
        if request.method == "GET":
            assert request.url.path == "/v1/eval-cases"
            assert request.url.params["agent"] == "support-agent"
            return httpx.Response(200, json={"cases": cases})
        posted.append(json.loads(request.content))
        return httpx.Response(202, json={"recorded": len(posted[-1]["results"])})

    return httpx.MockTransport(handler), posted


def run_cli(transport, *extra):
    return main(
        ["test", "--entry", "my_agent:run_task", "--agent", "support-agent", *extra],
        transport=transport,
    )


def test_all_passing_cases_exit_zero_and_report(agent_module, capsys):
    transport, posted = server([case("c1", "refund order 1", SEQ)])
    assert run_cli(transport, "--model-id", "m2") == 0
    [report] = posted
    assert report["model_id"] == "m2"
    assert report["results"] == [
        {"case_id": "c1", "passed": True, "details": {"failures": [], "completed": True}}
    ]
    assert "1/1 passed" in capsys.readouterr().out


def test_pass_rate_below_threshold_fails(agent_module):
    transport, posted = server(
        [case("c1", "refund order 1", SEQ), case("c2", "look up order 2", SEQ)]
    )
    assert run_cli(transport, "--threshold", "0.9") == 1
    assert [r["passed"] for r in posted[0]["results"]] == [True, False]
    assert run_cli(transport, "--threshold", "0.5") == 0


def test_previously_passing_critical_case_failing_is_a_regression(agent_module, capsys):
    cases = [case(f"ok{i}", "refund order", SEQ) for i in range(9)]
    cases.append(case("crit", "broken refund", SEQ, critical=True, last="passed"))
    transport, _ = server(cases)
    assert run_cli(transport, "--threshold", "0.5") == 1
    assert "regression" in capsys.readouterr().out.lower()


def test_no_cases_is_not_a_failure(agent_module, capsys):
    transport, posted = server([])
    assert run_cli(transport) == 0
    assert posted == []
    assert "no eval cases" in capsys.readouterr().out.lower()


def test_bad_entry_point_is_a_usage_error(agent_module):
    transport, _ = server([])
    assert main(["test", "--entry", "nope:run", "--agent", "a"], transport=transport) == 2
