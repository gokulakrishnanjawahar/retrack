"""Run-processing queue (pgmq): the API can only enqueue its own project's runs."""

import uuid

import psycopg
import pytest

from retrack_server.db import enqueue_run, project_scope


def queued_messages(conn, run_id):
    return conn.execute(
        "select message from pgmq.q_runs where message->>'run_id' = %s", (str(run_id),)
    ).fetchall()


def test_enqueue_adds_message_for_own_project(conn, tenants):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        enqueue_run(conn, a.run_id)
    assert queued_messages(conn, a.run_id) == [
        ({"project_id": str(a.project_id), "run_id": str(a.run_id)},)
    ]


def test_cannot_enqueue_another_projects_run(conn, tenants):
    a, b = tenants
    with pytest.raises(psycopg.errors.RaiseException), project_scope(conn, a.project_id):
        enqueue_run(conn, b.run_id)
    assert queued_messages(conn, b.run_id) == []


def test_cannot_enqueue_unknown_run(conn, tenants):
    a, _ = tenants
    with pytest.raises(psycopg.errors.RaiseException), project_scope(conn, a.project_id):
        enqueue_run(conn, uuid.uuid4())


def test_api_role_cannot_touch_queue_tables(conn, tenants):
    a, _ = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege), project_scope(conn, a.project_id):
        conn.execute("select * from pgmq.q_runs")
