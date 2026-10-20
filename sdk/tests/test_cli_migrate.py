"""`retrack migrate`: replay memory on a new model and print the report."""

import json
import textwrap

import httpx
import pytest

from retrack.cli import main

THREE_ARG_AGENT = '''
from typing import TypedDict
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

MODELS_SEEN = []

@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return "ok"

@tool
def refunds_api(order_id: str) -> str:
    """Refund an order."""
    return "ok"

class State(TypedDict):
    task: str

def run_task(task, callbacks, model_id):
    MODELS_SEEN.append(model_id)
    def act(state):
        if "crash" in state["task"]:
            raise RuntimeError("new model broke this")
        orders_api.invoke({"order_id": "1"})
        if "refund" in state["task"]:
            refunds_api.invoke({"order_id": "1"})
        return {}
    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke({"task": task}, config={"callbacks": callbacks})
    return "done"

def two_arg_task(task, callbacks):
    return run_task(task, callbacks, None)
'''

SEQ = [{"type": "completes"}, {"type": "tool_sequence", "tools": ["orders_api", "refunds_api"]}]


def case(case_id, task):
    return {
        "id": case_id,
        "source": "playbook",
        "input": {"task": task},
        "assertions": SEQ,
        "critical": False,
        "last_result": None,
    }


CASES = [case("ok", "refund order"), case("drift", "look up order"), case("bad", "crash refund")]
REPORT = {
    "id": "mig-1",
    "status": "completed",
    "to_model": "new-model",
    "model_applied": True,
    "summary": {
        "counts": {"passes": 1, "needs_relearning": 1, "breaks": 1, "fixed": 0, "returns": 0},
        "items": [
            {"title": "Refund", "result": "passes", "failures": []},
            {"title": "Look up", "result": "needs_relearning", "failures": ["tools"]},
            {"title": "Crash", "result": "breaks", "failures": ["raised"]},
        ],
    },
}


@pytest.fixture
def agent_module(tmp_path, monkeypatch):
    (tmp_path / "mig_agent.py").write_text(textwrap.dedent(THREE_ARG_AGENT))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("RETRACK_API_KEY", "rtk_test_" + "0" * 48)
    monkeypatch.setenv("RETRACK_BASE_URL", "https://retrack.test")


def server(cases=CASES, report=REPORT):
    seen = {"migration": None, "results": None}

    def handler(request):
        path = request.url.path
        if request.method == "POST" and path == "/v1/migrations":
            seen["migration"] = json.loads(request.content)
            return httpx.Response(201, json={"id": "mig-1", "status": "running"})
        if request.method == "GET" and path == "/v1/eval-cases":
            return httpx.Response(200, json={"cases": cases})
        if request.method == "POST" and path == "/v1/eval-results":
            seen["results"] = json.loads(request.content)
            return httpx.Response(202, json={"recorded": 3})
        if request.method == "GET" and path == "/v1/migrations/mig-1":
            return httpx.Response(200, json=report)
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def migrate(transport, entry="mig_agent:run_task", *extra):
    return main(
        [
            "migrate",
            "--to",
            "new-model",
            "--from",
            "old-model",
            "--entry",
            entry,
            "--agent",
            "support-agent",
            *extra,
        ],
        transport=transport,
    )


def test_migration_passes_the_new_model_and_reports(agent_module, capsys):
    import mig_agent

    transport, seen = server()
    code = migrate(transport)
    assert set(mig_agent.MODELS_SEEN) == {"new-model"}
    assert seen["migration"] == {
        "agent": "support-agent",
        "to_model": "new-model",
        "from_model": "old-model",
        "model_applied": True,
    }
    assert seen["results"]["migration_id"] == "mig-1"
    assert seen["results"]["model_id"] == "new-model"
    details = {r["case_id"]: r["details"]["completed"] for r in seen["results"]["results"]}
    assert details == {"ok": True, "drift": True, "bad": False}
    out = capsys.readouterr().out
    assert "breaks" in out and "Crash" in out
    assert code == 1  # something breaks: block the switch


def test_clean_migration_exits_zero(agent_module):
    report = json.loads(json.dumps(REPORT))
    report["summary"]["counts"] = {
        "passes": 3,
        "needs_relearning": 0,
        "breaks": 0,
        "fixed": 0,
        "returns": 0,
    }
    transport, _ = server(report=report)
    assert migrate(transport) == 0


def test_two_argument_entry_warns_that_the_model_may_not_change(agent_module, capsys):
    transport, seen = server()
    migrate(transport, "mig_agent:two_arg_task")
    assert seen["migration"]["model_applied"] is False
    assert "may not" in capsys.readouterr().out


def test_sample_limits_the_replayed_cases(agent_module):
    transport, seen = server()
    migrate(transport, "mig_agent:run_task", "--sample", "2", "--seed", "1")
    assert len(seen["results"]["results"]) == 2


def test_retrack_test_passes_the_model_to_three_argument_entries(agent_module):
    import mig_agent

    mig_agent.MODELS_SEEN.clear()
    transport, _ = server(cases=[case("ok", "refund order")])
    main(
        ["test", "--entry", "mig_agent:run_task", "--agent", "support-agent", "--model-id", "m9"],
        transport=transport,
    )
    assert mig_agent.MODELS_SEEN == ["m9"]
