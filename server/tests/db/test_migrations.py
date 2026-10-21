"""Model migration reports (Block I): replay memory on a new model, report per item."""

import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from retrack_server.api_keys import create_api_key
from retrack_server.app import app, get_conn, get_settings
from retrack_server.config import Settings

PEPPER = "test-pepper"


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


def active_playbook(conn, tenant, title):
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, steps, content_hash,"
        " approved_at, validated_models) values (%s, %s, 'candidate', %s, %s, md5(%s), now(),"
        " '{old-model}') returning id",
        (
            tenant.project_id,
            tenant.agent_id,
            title,
            Jsonb([{"action": "a", "tool": "orders_api"}]),
            title,
        ),
    ).fetchone()[0]
    conn.execute("update public.playbooks set status = 'active' where id = %s", (playbook_id,))
    return playbook_id


def repeated_failure(conn, tenant):
    conn.execute(
        "insert into public.failure_signatures (project_id, agent_id, tool_name, error_class,"
        " input_shape, fingerprint, occurrences) values (%s, %s, 'refunds_api', 'Timeout',"
        " '', 'fp', 2)",
        (tenant.project_id, tenant.agent_id),
    )


def start(client, auth, **body):
    return client.post(
        "/v1/migrations",
        headers=auth,
        json={"agent": "support-agent", "to_model": "new-model", "from_model": "old-model"} | body,
    )


def result(case_id, passed, completed=True):
    return {"case_id": case_id, "passed": passed, "details": {"completed": completed}}


def test_start_migration(client, auth):
    response = start(client, auth)
    assert response.status_code == 201
    assert response.json()["status"] == "running"


def test_unknown_agent_is_404(client, auth):
    assert start(client, auth, agent="never-seen").status_code == 404


def test_report_classifies_every_item_and_validates_passing_playbooks(client, conn, auth, tenants):
    a, _ = tenants
    keep = active_playbook(conn, a, "Keeps working")
    drift = active_playbook(conn, a, "Different path")
    broken = active_playbook(conn, a, "Breaks")
    repeated_failure(conn, a)
    cases = client.get("/v1/eval-cases", headers=auth).json()["cases"]
    by_title = {}
    for case in cases:
        source_id = conn.execute(
            "select source_id from public.eval_cases where id = %s", (case["id"],)
        ).fetchone()[0]
        by_title[source_id] = case["id"]
    failure_case = next(c["id"] for c in cases if c["source"] == "failure")

    migration_id = start(client, auth).json()["id"]
    posted = client.post(
        "/v1/eval-results",
        headers=auth,
        json={
            "test_run_id": str(uuid.uuid4()),
            "model_id": "new-model",
            "migration_id": migration_id,
            "results": [
                result(by_title[keep], True),
                result(by_title[drift], False, completed=True),
                result(by_title[broken], False, completed=False),
                result(failure_case, False),
            ],
        },
    )
    assert posted.status_code == 202

    report = client.get(f"/v1/migrations/{migration_id}", headers=auth).json()
    assert report["status"] == "completed"
    assert report["summary"]["counts"] == {
        "passes": 1,
        "needs_relearning": 1,
        "breaks": 1,
        "fixed": 0,
        "returns": 1,
    }
    outcomes = {item["title"]: item["result"] for item in report["summary"]["items"]}
    assert outcomes == {
        "Keeps working": "passes",
        "Different path": "needs_relearning",
        "Breaks": "breaks",
        "refunds_api failing with Timeout": "returns",
    }
    validated = dict(
        conn.execute(
            "select title, validated_models from public.playbooks where project_id = %s",
            (a.project_id,),
        ).fetchall()
    )
    assert validated["Keeps working"] == ["old-model", "new-model"]
    assert validated["Breaks"] == ["old-model"]


def test_migration_results_do_not_overwrite_the_current_models_latest_result(
    client, conn, auth, tenants
):
    a, _ = tenants
    active_playbook(conn, a, "P")
    case_id = client.get("/v1/eval-cases", headers=auth).json()["cases"][0]["id"]
    migration_id = start(client, auth).json()["id"]
    client.post(
        "/v1/eval-results",
        headers=auth,
        json={
            "test_run_id": str(uuid.uuid4()),
            "migration_id": migration_id,
            "results": [result(case_id, False, completed=False)],
        },
    )
    assert (
        conn.execute(
            "select last_result from public.eval_cases where id = %s", (case_id,)
        ).fetchone()[0]
        is None
    )


def test_validating_twice_does_not_duplicate_the_model(client, conn, auth, tenants):
    a, _ = tenants
    playbook_id = active_playbook(conn, a, "P")
    case_id = client.get("/v1/eval-cases", headers=auth).json()["cases"][0]["id"]
    migration_id = start(client, auth).json()["id"]
    for _ in range(2):
        client.post(
            "/v1/eval-results",
            headers=auth,
            json={
                "test_run_id": str(uuid.uuid4()),
                "migration_id": migration_id,
                "results": [result(case_id, True)],
            },
        )
    assert conn.execute(
        "select validated_models from public.playbooks where id = %s", (playbook_id,)
    ).fetchone()[0] == ["old-model", "new-model"]


def test_other_projects_migrations_are_invisible(client, conn, auth, tenants):
    _, b = tenants
    agent_b = conn.execute(
        "select id from public.agents where project_id = %s", (b.project_id,)
    ).fetchone()[0]
    other = conn.execute(
        "insert into public.migration_reports (project_id, agent_id, to_model)"
        " values (%s, %s, 'x') returning id",
        (b.project_id, agent_b),
    ).fetchone()[0]
    assert client.get(f"/v1/migrations/{other}", headers=auth).status_code == 404
    posted = client.post(
        "/v1/eval-results",
        headers=auth,
        json={
            "test_run_id": str(uuid.uuid4()),
            "migration_id": str(other),
            "results": [{"case_id": str(uuid.uuid4()), "passed": True}],
        },
    )
    assert posted.status_code == 404


def test_oversized_migration_body_is_413(client, auth):
    body = {"agent": "support-agent", "to_model": "m", "from_model": "x" * 20_000}
    assert client.post("/v1/migrations", json=body, headers=auth).status_code == 413
