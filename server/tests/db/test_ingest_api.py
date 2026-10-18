"""POST /v1/runs against the dev database (everything rolled back after each test)."""

import json

import pytest
from fastapi.testclient import TestClient

from retrack_server.api_keys import create_api_key, revoke_api_key
from retrack_server.app import app, get_conn, get_settings
from retrack_server.config import Settings
from retrack_server.schemas import MAX_BODY_BYTES

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
def api_key(conn, tenants):
    a, _ = tenants
    return create_api_key(conn, a.project_id, "sdk", PEPPER)


def post_run(client, key, payload):
    headers = {"Authorization": f"Bearer {key.secret}"} if key else {}
    return client.post("/v1/runs", json=payload, headers=headers)


def stored_run(conn, run_id):
    return conn.execute(
        "select project_id, model_id, tool_versions, tokens_in, tokens_out, outcome,"
        " outcome_source, taint_level from public.runs where id = %s",
        (run_id,),
    ).fetchall()


def queue_count(conn, run_id) -> int:
    return conn.execute(
        "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (run_id,)
    ).fetchone()[0]


def runs_captured_today(conn, project_id) -> int:
    row = conn.execute(
        "select runs_captured from public.usage_daily"
        " where project_id = %s and day = (now() at time zone 'utc')::date",
        (project_id,),
    ).fetchone()
    return row[0] if row else 0


# Authentication ---------------------------------------------------------------------


def test_missing_key_is_401(client, run_payload):
    response = post_run(client, None, run_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_key_is_401(client, run_payload):
    response = client.post("/v1/runs", json=run_payload(), headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_revoked_key_is_401(client, conn, api_key, run_payload):
    revoke_api_key(conn, api_key.id)
    assert post_run(client, api_key, run_payload()).status_code == 401


# Storing a run ----------------------------------------------------------------------


def test_run_is_stored_in_the_keys_project(client, conn, api_key, tenants, run_payload):
    a, _ = tenants
    payload = run_payload()
    response = post_run(client, api_key, payload)

    assert response.status_code == 202
    assert response.json() == {"id": payload["id"], "duplicate": False}
    assert stored_run(conn, payload["id"]) == [
        (
            a.project_id,
            "claude-haiku-5-5",
            {"stripe": "2026-09", "orders_api": "v3"},
            1200,
            300,
            "unknown",
            None,
            "untrusted",
        )
    ]


def test_steps_store_redacted_args_never_raw(client, conn, api_key, run_payload):
    payload = run_payload()
    post_run(client, api_key, payload)
    steps = conn.execute(
        "select idx, type, tool_name, args_hash, args_redacted"
        " from public.steps where run_id = %s order by idx",
        (payload["id"],),
    ).fetchall()

    assert [(s[0], s[1], s[2]) for s in steps] == [(0, "llm", None), (1, "tool", "orders_api")]
    assert steps[1][4] == {"order_id": "123", "api_key": "<SECRET>"}
    assert len(steps[1][3]) == 64
    assert "sk_live_secret" not in json.dumps([list(map(str, s)) for s in steps])


def test_task_text_is_redacted(client, conn, api_key, run_payload):
    payload = run_payload(task="Refund order 77 for priya@example.com, card 4111 1111 1111 1111")
    post_run(client, api_key, payload)
    task = conn.execute(
        "select task_text from public.runs where id = %s", (payload["id"],)
    ).fetchone()[0]
    assert task == "Refund order 77 for <EMAIL>, card <CARD>"


def test_run_is_queued_and_counted(client, conn, api_key, tenants, run_payload):
    a, _ = tenants
    payload = run_payload()
    post_run(client, api_key, payload)
    assert queue_count(conn, payload["id"]) == 1
    assert runs_captured_today(conn, a.project_id) == 1


def test_outcome_hint_is_recorded(client, conn, api_key, run_payload):
    payload = run_payload(outcome_hint={"outcome": "success", "source": "test"})
    post_run(client, api_key, payload)
    row = stored_run(conn, payload["id"])[0]
    assert (row[5], row[6]) == ("success", "test")
    confidence, signal_count = conn.execute(
        "select r.confidence, (select count(*) from public.outcome_signals s where s.run_id = r.id)"
        " from public.runs r where r.id = %s",
        (payload["id"],),
    ).fetchone()
    assert (confidence, signal_count) == (1.0, 1)


def test_agent_is_created_once_and_reused(client, conn, api_key, tenants, run_payload):
    a, _ = tenants
    post_run(client, api_key, run_payload(agent="billing-agent"))
    post_run(client, api_key, run_payload(agent="billing-agent"))
    agents = conn.execute(
        "select count(*) from public.agents where project_id = %s and name = 'billing-agent'",
        (a.project_id,),
    ).fetchone()[0]
    assert agents == 1


# Idempotency ------------------------------------------------------------------------


def test_same_run_twice_is_stored_queued_and_counted_once(
    client, conn, api_key, tenants, run_payload
):
    a, _ = tenants
    payload = run_payload()
    first = post_run(client, api_key, payload)
    second = post_run(client, api_key, payload)

    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert len(stored_run(conn, payload["id"])) == 1
    assert queue_count(conn, payload["id"]) == 1
    assert runs_captured_today(conn, a.project_id) == 1


# Validation and limits --------------------------------------------------------------


def test_invalid_payload_is_422(client, api_key, run_payload):
    response = post_run(client, api_key, run_payload(tokens_in=-5))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_invalid_json_is_422(client, api_key):
    response = client.post(
        "/v1/runs",
        content=b"{not json",
        headers={"Authorization": f"Bearer {api_key.secret}"},
    )
    assert response.status_code == 422


def test_oversized_body_is_413(client, api_key, run_payload):
    payload = run_payload(task="x" * (MAX_BODY_BYTES + 1))
    response = post_run(client, api_key, payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
