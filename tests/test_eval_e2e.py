"""End to end: an active playbook becomes a test case that `retrack test` runs and reports."""

import os
import socket
import textwrap
import threading
import time

import psycopg
import pytest
import uvicorn
from psycopg.types.json import Jsonb

from retrack.cli import main
from retrack_server.admin import create_project
from retrack_server.app import app

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("SERVER_DATABASE_URL")),
    reason="needs the dev database",
)

AGENT = '''
from typing import TypedDict
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

@tool
def orders_api(order_id: str) -> str:
    """Look up an order."""
    return "delivered"

@tool
def refunds_api(order_id: str) -> str:
    """Refund an order."""
    return "refunded"

class State(TypedDict):
    task: str

def run_task(task, callbacks):
    def act(state):
        orders_api.invoke({"order_id": "1"})
        refunds_api.invoke({"order_id": "1"})
        return {}
    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    graph.compile().invoke({"task": task}, config={"callbacks": callbacks})
    return "done"
'''


@pytest.fixture
def project():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        created = create_project(admin, "eval-e2e-test", "p", os.environ["RETRACK_KEY_PEPPER"])
        agent_id = admin.execute(
            "insert into public.agents (project_id, name) values (%s, 'e2e-agent') returning id",
            (created.project_id,),
        ).fetchone()[0]
        playbook_id = admin.execute(
            "insert into public.playbooks (project_id, agent_id, status, title, steps,"
            " content_hash, approved_at) values (%s, %s, 'candidate', 'Refund', %s, 'h', now())"
            " returning id",
            (
                created.project_id,
                agent_id,
                Jsonb(
                    [{"action": "a", "tool": "orders_api"}, {"action": "b", "tool": "refunds_api"}]
                ),
            ),
        ).fetchone()[0]
        admin.execute("update public.playbooks set status = 'active' where id = %s", (playbook_id,))
        yield created
        admin.execute("delete from public.organizations where id = %s", (created.org_id,))


@pytest.fixture
def server_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_retrack_test_runs_memory_cases_and_records_results(
    project, server_url, tmp_path, monkeypatch
):
    (tmp_path / "e2e_agent.py").write_text(textwrap.dedent(AGENT))
    monkeypatch.syspath_prepend(str(tmp_path))
    code = main(
        [
            "test",
            "--entry",
            "e2e_agent:run_task",
            "--agent",
            "e2e-agent",
            "--api-key",
            project.key.secret,
            "--base-url",
            server_url,
            "--model-id",
            "m-e2e",
        ]
    )
    assert code == 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as admin:
        row = admin.execute(
            "select last_result, last_model_id from public.eval_cases where project_id = %s",
            (project.project_id,),
        ).fetchone()
    assert row == ("passed", "m-e2e")
