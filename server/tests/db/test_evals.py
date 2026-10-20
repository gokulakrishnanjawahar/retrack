"""Eval cases created from memory, served to `retrack test`, results recorded (Block H)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from retrack_server.api_keys import create_api_key
from retrack_server.app import app, get_conn, get_settings
from retrack_server.config import Settings

PEPPER = "test-pepper"
STEPS = [
    {"action": "Look up", "tool": "orders_api"},
    {"action": "Note", "tool": "none"},
    {"action": "Refund", "tool": "refunds_api"},
]


def add_playbook(conn, tenant, status="candidate"):
    """Like the distiller: insert as a candidate with provenance, then change status."""
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, task_pattern,"
        " steps, content_hash, approved_at) values (%s, %s, 'candidate', 'Refund',"
        " 'Refund an order', %s, 'h', now()) returning id",
        (tenant.project_id, tenant.agent_id, Jsonb(STEPS)),
    ).fetchone()[0]
    conn.execute(
        "insert into public.provenance (project_id, object_type, object_id, source_run_ids,"
        " trust_level) values (%s, 'playbook', %s, %s, 'trusted')",
        (tenant.project_id, playbook_id, [tenant.run_id]),
    )
    if status != "candidate":
        conn.execute("update public.playbooks set status = %s where id = %s", (status, playbook_id))
    return playbook_id


def cases(conn, project_id):
    return conn.execute(
        "select source, input, expected_assertions, critical, status from public.eval_cases"
        " where project_id = %s order by source",
        (project_id,),
    ).fetchall()


def test_activating_a_playbook_creates_an_eval_case(conn, tenants):
    a, _ = tenants
    playbook_id = add_playbook(conn, a)
    assert cases(conn, a.project_id) == []
    conn.execute("update public.playbooks set status = 'active' where id = %s", (playbook_id,))
    [(source, case_input, assertions, critical, status)] = cases(conn, a.project_id)
    assert (source, critical, status) == ("playbook", False, "active")
    assert case_input == {"task": "task for project-a"}  # the source run's task
    assert assertions == [
        {"type": "completes"},
        {"type": "tool_sequence", "tools": ["orders_api", "refunds_api"]},
    ]


def test_retiring_the_playbook_retires_its_case_and_reactivation_restores_it(conn, tenants):
    a, _ = tenants
    playbook_id = add_playbook(conn, a, status="active")
    conn.execute("update public.playbooks set status = 'retired' where id = %s", (playbook_id,))
    assert cases(conn, a.project_id)[0][4] == "retired"
    conn.execute("update public.playbooks set status = 'active' where id = %s", (playbook_id,))
    assert cases(conn, a.project_id)[0][4] == "active"
    assert len(cases(conn, a.project_id)) == 1


def test_repeated_failure_creates_a_critical_case(conn, tenants):
    a, _ = tenants
    signature_id = conn.execute(
        "insert into public.failure_signatures (project_id, agent_id, tool_name, error_class,"
        " input_shape, fingerprint, example_run_id) values (%s, %s, 'refunds_api',"
        " 'TimeoutError', 'order_id:str', 'fp', %s) returning id",
        (a.project_id, a.agent_id, a.run_id),
    ).fetchone()[0]
    assert cases(conn, a.project_id) == []  # seen once: not yet a pattern
    conn.execute(
        "update public.failure_signatures set occurrences = 2 where id = %s", (signature_id,)
    )
    [(source, case_input, assertions, critical, _)] = cases(conn, a.project_id)
    assert (source, critical, case_input) == ("failure", True, {"task": "task for project-a"})
    assert assertions == [
        {"type": "no_failure", "tool": "refunds_api", "error_class": "TimeoutError"}
    ]


# API --------------------------------------------------------------------------------


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="unused", key_pepper=PEPPER
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(conn, tenants):
    a, _ = tenants
    return {"Authorization": f"Bearer {create_api_key(conn, a.project_id, 'ci', PEPPER).secret}"}


def test_list_eval_cases_for_an_agent(client, conn, auth, tenants):
    a, b = tenants
    add_playbook(conn, a, status="active")
    add_playbook(conn, b, status="active")
    response = client.get("/v1/eval-cases", params={"agent": "support-agent"}, headers=auth)
    assert response.status_code == 200
    [case] = response.json()["cases"]
    assert set(case) == {"id", "source", "input", "assertions", "critical", "last_result"}
    assert case["input"] == {"task": "task for project-a"}


def test_record_results_updates_latest_and_history(client, conn, auth, tenants):
    a, _ = tenants
    add_playbook(conn, a, status="active")
    case_id = client.get("/v1/eval-cases", headers=auth).json()["cases"][0]["id"]
    test_run = str(uuid.uuid4())
    response = client.post(
        "/v1/eval-results",
        headers=auth,
        json={
            "test_run_id": test_run,
            "model_id": "m2",
            "results": [{"case_id": case_id, "passed": False, "details": {"why": "x"}}],
        },
    )
    assert response.status_code == 202
    assert response.json() == {"recorded": 1}
    latest = conn.execute(
        "select last_result, last_model_id, last_run_at is not null from public.eval_cases"
        " where id = %s",
        (case_id,),
    ).fetchone()
    assert latest == ("failed", "m2", True)
    assert (
        conn.execute(
            "select count(*) from public.eval_results where test_run_id = %s", (test_run,)
        ).fetchone()[0]
        == 1
    )


def test_results_for_another_projects_case_are_rejected(client, conn, auth, tenants):
    _, b = tenants
    add_playbook(conn, b, status="active")
    other = conn.execute(
        "select id from public.eval_cases where project_id = %s", (b.project_id,)
    ).fetchone()[0]
    response = client.post(
        "/v1/eval-results",
        headers=auth,
        json={
            "test_run_id": str(uuid.uuid4()),
            "results": [{"case_id": str(other), "passed": True}],
        },
    )
    assert response.status_code == 404
