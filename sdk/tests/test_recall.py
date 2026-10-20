"""SDK recall: fetch memory before a task, never block or break the agent."""

import json
import time
import uuid

import httpx

from retrack import Memory, Retrack

API_KEY = "rtk_test_" + "0" * 48

ANSWER = {
    "recall_id": "r1",
    "playbooks": [
        {
            "id": "p1",
            "version": 2,
            "score": 0.91,
            "title": "Refund a damaged order",
            "preconditions": "The order was delivered.",
            "steps": [
                {"action": "Look up the order", "tool": "orders_api"},
                {"action": "Issue the refund", "tool": "refunds_api"},
            ],
            "pitfalls": "refunds_api times out above 5 requests per second.",
        }
    ],
    "warnings": [{"message": "refunds_api has failed with TimeoutError 7 times"}],
    "holdout": False,
    "replay_eligible": False,
    "mode": "hybrid",
}


def client(handler, **kwargs):
    return Retrack(
        agent="support-agent",
        api_key=API_KEY,
        base_url="https://retrack.test",
        transport=httpx.MockTransport(handler),
        model_id="m1",
        tool_versions={"refunds_api": "v3"},
        **kwargs,
    )


def test_recall_sends_the_request_and_parses_memory():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    run_id = uuid.uuid4()
    memory = client(handler).recall("Refund order 42", run_id=run_id)

    assert seen[0].url.path == "/v1/recall"
    assert json.loads(seen[0].content) == {
        "agent": "support-agent",
        "task": "Refund order 42",
        "model_id": "m1",
        "tool_versions": {"refunds_api": "v3"},
        "max_playbooks": 3,
        "run_id": str(run_id),
    }
    assert memory and memory.playbooks[0]["title"] == "Refund a damaged order"
    assert memory.recall_id == "r1"


def test_memory_as_prompt_lists_playbooks_and_warnings():
    prompt = Memory.from_response(ANSWER).as_prompt()
    assert "Refund a damaged order" in prompt
    assert "1. Look up the order (orders_api)" in prompt
    assert "refunds_api times out" in prompt
    assert "TimeoutError 7 times" in prompt


def test_empty_memory_gives_an_empty_prompt():
    assert Memory().as_prompt() == ""
    assert not Memory()


def test_secrets_are_stripped_from_the_task():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=ANSWER)

    client(handler).recall("refund with key sk_live_51HxAbCdEfGhIjKlMnOpQr")
    assert seen[0]["task"] == "refund with key <SECRET>"


def test_fails_open_on_timeout():
    def slow(request):
        time.sleep(1.0)
        return httpx.Response(200, json=ANSWER)

    started = time.monotonic()
    memory = client(slow).recall("Refund order 42", timeout=0.2)
    assert time.monotonic() - started < 0.9
    assert memory == Memory()


def test_fails_open_on_errors_and_bad_responses():
    for handler in (
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(401, json={"error": {"code": "unauthorized"}}),
        lambda r: httpx.Response(200, content=b"not json"),
    ):
        assert client(handler).recall("task") == Memory()

    def down(request):
        raise httpx.ConnectError("refused")

    assert client(down).recall("task") == Memory()


def test_recall_without_configuration_returns_empty_memory(monkeypatch):
    monkeypatch.delenv("RETRACK_API_KEY", raising=False)
    monkeypatch.delenv("RETRACK_BASE_URL", raising=False)
    assert Retrack(agent="a").recall("task") == Memory()


def test_recall_node_adds_memory_to_graph_state():
    rt = client(lambda r: httpx.Response(200, json=ANSWER))
    node = rt.recall_node(task_key="question", into="memory")
    update = node({"question": "Refund order 42", "run_id": str(uuid.uuid4())})
    assert "Refund a damaged order" in update["memory"]


def test_recall_node_without_a_task_returns_empty_memory():
    rt = client(lambda r: httpx.Response(200, json=ANSWER))
    assert rt.recall_node()({}) == {"retrack_memory": ""}
