"""Queue access for background workers: only `retrack_worker` can read or remove jobs."""

import psycopg
import pytest

from retrack_server.db import enqueue_run, project_scope, worker_scope
from retrack_server.worker import complete_job, dead_letter_job, read_jobs


@pytest.fixture
def queued(conn, tenants):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        enqueue_run(conn, a.run_id)
    return a


def our_job(jobs, tenant):
    return next(j for j in jobs if j.run_id == tenant.run_id)


def test_worker_reads_job_with_project_and_run(conn, queued):
    jobs = read_jobs(conn, batch=1000, visibility_seconds=30)
    job = our_job(jobs, queued)
    assert (job.project_id, job.read_count) == (queued.project_id, 1)


def test_read_jobs_are_hidden_until_visibility_timeout(conn, queued):
    read_jobs(conn, batch=1000, visibility_seconds=30)
    again = read_jobs(conn, batch=1000, visibility_seconds=30)
    assert all(j.run_id != queued.run_id for j in again)


def test_complete_removes_job(conn, queued):
    job = our_job(read_jobs(conn, batch=1000, visibility_seconds=0), queued)
    complete_job(conn, job.msg_id)
    remaining = conn.execute(
        "select count(*) from pgmq.q_runs where msg_id = %s", (job.msg_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_dead_letter_moves_job(conn, queued):
    job = our_job(read_jobs(conn, batch=1000, visibility_seconds=0), queued)
    dead_letter_job(conn, job.msg_id, "boom")
    assert (
        conn.execute(
            "select count(*) from pgmq.q_runs where msg_id = %s", (job.msg_id,)
        ).fetchone()[0]
        == 0
    )
    dead = conn.execute(
        "select message from pgmq.q_runs_dlq where message->>'run_id' = %s", (str(queued.run_id),)
    ).fetchone()[0]
    assert dead["error"] == "boom"


def test_api_role_cannot_read_jobs(conn, queued):
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        project_scope(conn, queued.project_id),
    ):
        conn.execute("select * from private.read_run_jobs(10, 30)")


def test_worker_role_cannot_read_customer_tables_directly(conn, queued):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), worker_scope(conn):
        conn.execute("select * from public.runs")
