"""Run IDs are client-generated idempotency keys, unique per project."""

import psycopg
import pytest

from retrack_server.db import project_scope

INSERT_RUN = (
    "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
    " values (%s, %s, %s, 'again', 'm')"
)


def run_count(conn, run_id) -> int:
    return conn.execute("select count(*) from public.runs where id = %s", (run_id,)).fetchone()[0]


def test_same_run_id_twice_in_one_project_is_rejected(conn, tenants):
    a, _ = tenants
    with pytest.raises(psycopg.errors.UniqueViolation), project_scope(conn, a.project_id):
        conn.execute(INSERT_RUN, (a.run_id, a.project_id, a.agent_id))
    assert run_count(conn, a.run_id) == 1


def test_same_run_id_twice_with_on_conflict_keeps_one_row(conn, tenants):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        inserted = conn.execute(
            INSERT_RUN + " on conflict do nothing", (a.run_id, a.project_id, a.agent_id)
        ).rowcount
    assert inserted == 0
    assert run_count(conn, a.run_id) == 1


def test_same_run_id_in_another_project_is_independent(conn, tenants):
    a, b = tenants
    with project_scope(conn, b.project_id):
        conn.execute(INSERT_RUN, (a.run_id, b.project_id, b.agent_id))
    assert run_count(conn, a.run_id) == 2


def test_new_runs_are_untrusted_and_unknown_by_default(conn, tenants):
    a, _ = tenants
    row = conn.execute(
        "select taint_level, outcome, holdout from public.runs where id = %s", (a.run_id,)
    ).fetchone()
    assert row == ("untrusted", "unknown", False)
