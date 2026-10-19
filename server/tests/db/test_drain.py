"""POST /internal/drain and the drain loop: process queued runs, retry, dead-letter."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from retrack_server.api_keys import create_api_key
from retrack_server.app import app, get_conn, get_settings
from retrack_server.config import Settings
from retrack_server.worker import drain

PEPPER = "test-pepper"
WORKER_SECRET = "test-worker-secret"


def client_with(conn, worker_secret):
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="unused", key_pepper=PEPPER, worker_secret=worker_secret
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def drain_call(client, secret=WORKER_SECRET):
    headers = {"X-Retrack-Worker-Secret": secret} if secret else {}
    return client.post("/internal/drain", headers=headers)


def test_drain_requires_the_worker_secret(conn):
    client = client_with(conn, WORKER_SECRET)
    assert drain_call(client, None).status_code == 401
    assert drain_call(client, "wrong").status_code == 401


def test_drain_is_disabled_without_a_configured_secret(conn):
    client = client_with(conn, None)
    assert drain_call(client).status_code == 503


def test_api_keys_do_not_open_the_drain(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "sdk", PEPPER)
    client = client_with(conn, WORKER_SECRET)
    response = client.post("/internal/drain", headers={"Authorization": f"Bearer {key.secret}"})
    assert response.status_code == 401


def test_ingested_run_is_processed_by_drain(conn, tenants, run_payload):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "sdk", PEPPER)
    client = client_with(conn, WORKER_SECRET)
    payload = run_payload()
    assert (
        client.post(
            "/v1/runs", json=payload, headers={"Authorization": f"Bearer {key.secret}"}
        ).status_code
        == 202
    )

    response = drain_call(client)
    assert response.status_code == 200
    assert response.json()["processed"] >= 1

    taint, processed = conn.execute(
        "select taint_level, processed_at is not null from public.runs where id = %s",
        (payload["id"],),
    ).fetchone()
    assert (taint, processed) == ("untrusted", True)
    left = conn.execute(
        "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (payload["id"],)
    ).fetchone()[0]
    assert left == 0


def poison_job(conn, project_id) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "select pgmq.send('runs', %s)",
        (Jsonb({"project_id": str(project_id), "run_id": run_id}),),
    )
    return run_id


def test_failing_job_is_retried_later(conn, tenants):
    a, _ = tenants
    run_id = poison_job(conn, a.project_id)
    result = drain(conn, visibility_seconds=30, time_budget_seconds=20)
    assert result.retrying >= 1
    read_ct = conn.execute(
        "select read_ct from pgmq.q_runs where message->>'run_id' = %s", (run_id,)
    ).fetchone()[0]
    assert read_ct == 1


def test_job_failing_too_often_moves_to_dead_letter_queue(conn, tenants):
    a, _ = tenants
    run_id = poison_job(conn, a.project_id)
    result = drain(conn, visibility_seconds=0, max_attempts=1, time_budget_seconds=20)
    assert result.dead_lettered >= 1
    assert (
        conn.execute(
            "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (run_id,)
        ).fetchone()[0]
        == 0
    )
    dead = conn.execute(
        "select message from pgmq.q_runs_dlq where message->>'run_id' = %s", (run_id,)
    ).fetchone()[0]
    assert dead["error"].startswith("firewall: LookupError")


def test_drain_scores_runs_with_the_judge_when_enabled(conn, tenants):
    from retrack_server.llm import FakeLLM

    a, _ = tenants
    from retrack_server.db import enqueue_run, project_scope

    with project_scope(conn, a.project_id):
        enqueue_run(conn, a.run_id)
    llm = FakeLLM([{"outcome": "success", "confidence": 0.9, "reason": "done"}] * 1000)
    drain(conn, llm=llm, time_budget_seconds=20)
    assert conn.execute(
        "select outcome, outcome_source from public.runs where id = %s", (a.run_id,)
    ).fetchone() == ("success", "judge")


def add_runs(conn, tenant, n):
    from retrack_server.db import enqueue_run, project_scope

    run_ids = []
    for _ in range(n):
        run_id = uuid.uuid4()
        conn.execute(
            "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
            " values (%s, %s, %s, 't', 'm')",
            (run_id, tenant.project_id, tenant.agent_id),
        )
        with project_scope(conn, tenant.project_id):
            enqueue_run(conn, run_id)
        run_ids.append(run_id)
    return run_ids


def processed(conn, run_ids):
    return conn.execute(
        "select count(*) from public.runs where id = any(%s) and processed_at is not null",
        (run_ids,),
    ).fetchone()[0]


def test_time_budget_is_checked_before_every_job(conn, tenants):
    from retrack_server.llm import FakeLLM

    a, _ = tenants
    run_ids = add_runs(conn, a, 6)
    verdict = {"outcome": "success", "confidence": 0.9, "reason": "ok"}
    slow = FakeLLM([verdict] * 1000, delay_seconds=0.4)
    started = time.monotonic()
    drain(conn, llm=slow, batch=50, time_budget_seconds=1.0)
    assert time.monotonic() - started < 3.0
    assert 0 < processed(conn, run_ids) < 6


def test_judge_outage_keeps_the_firewall_result_and_retries_later(conn, tenants):
    from retrack_server.db import enqueue_run, project_scope
    from retrack_server.llm import FakeLLM, LLMError

    a, _ = tenants
    with project_scope(conn, a.project_id):
        enqueue_run(conn, a.run_id)
    down = FakeLLM([LLMError("overloaded")] * 1000)
    result = drain(conn, llm=down, visibility_seconds=30, time_budget_seconds=20)
    assert result.retrying >= 1 and result.dead_lettered == 0
    assert processed(conn, [a.run_id]) == 1  # firewall result was kept
    still_queued = conn.execute(
        "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (str(a.run_id),)
    ).fetchone()[0]
    assert still_queued == 1


def test_judge_failing_every_attempt_completes_the_job_instead_of_dead_lettering(conn, tenants):
    from retrack_server.db import enqueue_run, project_scope
    from retrack_server.llm import FakeLLM, LLMError

    a, _ = tenants
    with project_scope(conn, a.project_id):
        enqueue_run(conn, a.run_id)
    down = FakeLLM([LLMError("overloaded")] * 1000)
    drain(conn, llm=down, visibility_seconds=0, max_attempts=1, time_budget_seconds=20)
    queued = conn.execute(
        "select (select count(*) from pgmq.q_runs where message->>'run_id' = %s),"
        " (select count(*) from pgmq.q_runs_dlq where message->>'run_id' = %s)",
        (str(a.run_id), str(a.run_id)),
    ).fetchone()
    assert queued == (0, 0)
    assert conn.execute(
        "select outcome, processed_at is not null from public.runs where id = %s", (a.run_id,)
    ).fetchone() == ("unknown", True)
