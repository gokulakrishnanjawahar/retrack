"""End to end: a LangGraph agent with the SDK -> local API server -> dev database.

Creates a throwaway organization and deletes it afterwards (cascading to every row).
"""

import os
import socket
import threading
import time
import uuid
from typing import TypedDict

import httpx
import psycopg
import pytest
import uvicorn
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from retrack import Retrack
from retrack_server.api_keys import create_api_key
from retrack_server.app import app

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("SERVER_DATABASE_URL")),
    reason="DATABASE_URL and SERVER_DATABASE_URL not set",
)


@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return f"order {order_id}: damaged"


class State(TypedDict):
    messages: list


def build_graph():
    model = GenericFakeChatModel(
        messages=iter([AIMessage(content="done", response_metadata={"model_name": "fake-1"})])
    )

    def act(state: State) -> dict:
        orders_api.invoke({"order_id": "123"})
        return {"messages": [*state["messages"], model.invoke(state["messages"])]}

    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    return graph.compile()


@pytest.fixture
def admin():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@pytest.fixture
def project(admin):
    org_id = admin.execute(
        "insert into public.organizations (name) values ('e2e-test') returning id"
    ).fetchone()[0]
    project_id = admin.execute(
        "insert into public.projects (org_id, name) values (%s, 'e2e') returning id", (org_id,)
    ).fetchone()[0]
    key = create_api_key(admin, project_id, "e2e", os.environ["RETRACK_KEY_PEPPER"])
    yield project_id, key.secret
    admin.execute("delete from pgmq.q_runs where message->>'project_id' = %s", (str(project_id),))
    admin.execute("delete from public.organizations where id = %s", (org_id,))


@pytest.fixture(scope="module")
def server_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_agent_run_lands_in_database_with_all_steps(admin, project, server_url):
    project_id, secret = project
    rt = Retrack(agent="e2e-agent", api_key=secret, base_url=server_url)
    build_graph().invoke(
        {"messages": [HumanMessage("Refund order #123")]}, config={"callbacks": [rt.callback()]}
    )
    assert rt.flush(timeout=10)

    runs = admin.execute(
        "select id, task_text, model_id from public.runs where project_id = %s", (project_id,)
    ).fetchall()
    assert [(r[1], r[2]) for r in runs] == [("Refund order #123", "fake-1")]
    run_id = runs[0][0]

    steps = admin.execute(
        "select idx, type, tool_name from public.steps where run_id = %s order by idx", (run_id,)
    ).fetchall()
    assert steps == [(0, "tool", "orders_api"), (1, "llm", None)]

    queued = admin.execute(
        "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (str(run_id),)
    ).fetchone()[0]
    assert queued == 1


def test_same_run_sent_twice_creates_one_row(admin, project, server_url):
    project_id, secret = project
    payload = {"id": str(uuid.uuid4()), "agent": "e2e-agent", "task": "t", "model_id": "m"}
    headers = {"Authorization": f"Bearer {secret}"}
    first = httpx.post(f"{server_url}/v1/runs", json=payload, headers=headers)
    second = httpx.post(f"{server_url}/v1/runs", json=payload, headers=headers)

    assert (first.status_code, first.json()["duplicate"]) == (202, False)
    assert (second.status_code, second.json()["duplicate"]) == (202, True)
    count = admin.execute(
        "select count(*) from public.runs where project_id = %s", (project_id,)
    ).fetchone()[0]
    assert count == 1


def test_sdk_never_raises_when_server_is_down():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
    rt = Retrack(
        agent="e2e-agent",
        api_key="rtk_test_" + "0" * 48,
        base_url=f"http://127.0.0.1:{closed_port}",
    )
    rt._sender._backoff = 0.01
    result = build_graph().invoke(
        {"messages": [HumanMessage("task")]}, config={"callbacks": [rt.callback()]}
    )
    assert result["messages"][-1].content == "done"
    assert rt.flush(timeout=5)


def test_connections_are_reused_across_requests(project, server_url):
    from retrack_server.app import get_pool, get_settings

    _, secret = project
    headers = {"Authorization": f"Bearer {secret}"}
    with httpx.Client(base_url=server_url, headers=headers) as client:
        client.post(
            "/v1/runs", json={"id": str(uuid.uuid4()), "agent": "a", "task": "t", "model_id": "m"}
        )
        opened_before = get_pool(get_settings()).get_stats().get("connections_num", 0)
        for _ in range(5):
            payload = {"id": str(uuid.uuid4()), "agent": "a", "task": "t", "model_id": "m"}
            assert client.post("/v1/runs", json=payload).status_code == 202
    opened_after = get_pool(get_settings()).get_stats().get("connections_num", 0)
    assert opened_after == opened_before


def test_pooled_connections_come_back_clean(project, server_url):
    from retrack_server.app import get_pool, get_settings

    _, secret = project
    payload = {"id": str(uuid.uuid4()), "agent": "a", "task": "t", "model_id": "m"}
    httpx.post(f"{server_url}/v1/runs", json=payload, headers={"Authorization": f"Bearer {secret}"})
    with get_pool(get_settings()).connection() as conn:
        user, project_setting = conn.execute(
            "select current_user, current_setting('app.project_id', true)"
        ).fetchone()
    assert user == "retrack_server"
    assert project_setting in (None, "")


def test_queued_run_is_processed_by_the_drain_endpoint(admin, project, server_url):
    project_id, secret = project
    rt = Retrack(agent="e2e-agent", api_key=secret, base_url=server_url)
    build_graph().invoke(
        {"messages": [HumanMessage("Refund order #9 for a@b.co")]},
        config={"callbacks": [rt.callback()]},
    )
    assert rt.flush(timeout=10)

    response = httpx.post(
        f"{server_url}/internal/drain",
        headers={"X-Retrack-Worker-Secret": os.environ["RETRACK_WORKER_SECRET"]},
        timeout=120,
    )
    assert response.status_code == 200

    task, taint, processed = admin.execute(
        "select task_text, taint_level, processed_at is not null from public.runs"
        " where project_id = %s",
        (project_id,),
    ).fetchone()
    assert (task, taint, processed) == ("Refund order #9 for <EMAIL>", "untrusted", True)
