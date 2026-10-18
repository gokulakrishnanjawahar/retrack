"""Capturing LangGraph runs with the Retrack callback."""

import contextlib
import json
import uuid
from typing import TypedDict

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from retrack import Retrack

API_KEY = "rtk_test_" + "0" * 48


@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return f"order {order_id}: damaged"


@tool
def refunds_api(order_id: str) -> str:
    """Issue a refund."""
    raise TimeoutError("refund service timed out")


class State(TypedDict):
    messages: list
    result: str


def build_graph():
    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="Looking up the order",
                    usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    response_metadata={"model_name": "fake-model-1"},
                ),
                AIMessage(
                    content="Refund issued",
                    usage_metadata={"input_tokens": 150, "output_tokens": 30, "total_tokens": 180},
                    response_metadata={"model_name": "fake-model-1"},
                ),
            ]
        )
    )

    def plan(state: State) -> dict:
        reply = model.invoke(state["messages"])
        return {"messages": [*state["messages"], reply]}

    def act(state: State) -> dict:
        found = orders_api.invoke({"order_id": "123"})
        with contextlib.suppress(TimeoutError):
            refunds_api.invoke({"order_id": "123"})
        return {"result": found}

    def answer(state: State) -> dict:
        reply = model.invoke(state["messages"])
        return {"messages": [*state["messages"], reply]}

    graph = StateGraph(State)
    graph.add_node("plan", plan)
    graph.add_node("act", act)
    graph.add_node("answer", answer)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "act")
    graph.add_edge("act", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


@pytest.fixture
def captured():
    return []


@pytest.fixture
def rt(captured):
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(202)

    return Retrack(
        api_key=API_KEY,
        agent="support-agent",
        base_url="https://retrack.test",
        tool_versions={"orders_api": "v3"},
        trusted_tools=["orders_api"],
        transport=httpx.MockTransport(handler),
    )


def run_agent(rt, task="My order #123 arrived damaged, refund it"):
    return build_graph().invoke(
        {"messages": [HumanMessage(task)], "result": ""}, config={"callbacks": [rt.callback()]}
    )


def test_one_payload_per_graph_run(rt, captured):
    run_agent(rt)
    assert rt.flush(timeout=2)
    assert len(captured) == 1
    uuid.UUID(captured[0]["id"])


def test_run_fields(rt, captured):
    run_agent(rt)
    rt.flush(timeout=2)
    run = captured[0]
    assert run["agent"] == "support-agent"
    assert run["task"] == "My order #123 arrived damaged, refund it"
    assert run["model_id"] == "fake-model-1"
    assert run["tool_versions"] == {"orders_api": "v3"}
    assert (run["tokens_in"], run["tokens_out"]) == (250, 50)
    assert run["latency_ms"] >= 0


def test_steps_in_order_with_tools_and_errors(rt, captured):
    run_agent(rt)
    rt.flush(timeout=2)
    steps = captured[0]["steps"]
    assert [(s["idx"], s["type"], s.get("tool_name")) for s in steps] == [
        (0, "llm", None),
        (1, "tool", "orders_api"),
        (2, "tool", "refunds_api"),
        (3, "llm", None),
    ]
    assert steps[0]["tokens_in"] == 100
    assert steps[1]["args"] == {"order_id": "123"}
    assert steps[1]["result_class"] == "ok"
    assert steps[1]["input_trust"] == "trusted"
    assert steps[2]["result_class"] == "error"
    assert steps[2]["error_class"] == "TimeoutError"
    assert steps[2]["input_trust"] == "untrusted"


def test_explicit_task_overrides_derived_task(rt, captured):
    build_graph().invoke(
        {"messages": [HumanMessage("raw text")], "result": ""},
        config={"callbacks": [rt.callback(task="Refund damaged order")]},
    )
    rt.flush(timeout=2)
    assert captured[0]["task"] == "Refund damaged order"


def test_separate_invocations_get_separate_run_ids(rt, captured):
    handler = rt.callback()
    for _ in range(2):
        build_graph().invoke(
            {"messages": [HumanMessage("task")], "result": ""}, config={"callbacks": [handler]}
        )
    rt.flush(timeout=2)
    assert len({run["id"] for run in captured}) == 2


def test_agent_works_without_api_key_or_url(monkeypatch):
    monkeypatch.delenv("RETRACK_API_KEY", raising=False)
    monkeypatch.delenv("RETRACK_BASE_URL", raising=False)
    rt = Retrack(agent="support-agent")
    result = run_agent(rt)
    assert result["result"] == "order 123: damaged"
    assert rt.flush(timeout=1)


def test_capture_failure_never_reaches_the_agent(rt, monkeypatch):
    def broken_submit(payload):
        raise RuntimeError("sender exploded")

    monkeypatch.setattr(rt._sender, "submit", broken_submit)
    result = run_agent(rt)
    assert result["result"] == "order 123: damaged"


def test_secrets_never_leave_the_process(rt, captured):
    run_agent(rt, task="Refund using key sk_live_51HxAbCdEfGhIjKlMnOpQr")
    rt.flush(timeout=2)
    assert captured[0]["task"] == "Refund using key <SECRET>"
    assert "sk_live_51HxAbCdEfGhIjKlMnOpQr" not in str(captured[0])
