"""The public API role cannot change trust or processing state; only the worker can."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from retrack_server.db import project_scope, worker_scope


@pytest.mark.parametrize(
    "statement",
    [
        "update public.runs set taint_level = 'trusted' where id = %s",
        "update public.runs set processed_at = now() where id = %s",
        "update public.runs set task_text = 'changed' where id = %s",
        "update public.steps set input_trust = 'trusted' where run_id = %s",
        "update public.agents set name = 'x' where id is not null and %s is not null",
    ],
)
def test_api_role_cannot_change_trust_or_history(conn, tenants, statement):
    a, _ = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege), project_scope(conn, a.project_id):
        conn.execute(statement, (a.run_id,))


def test_api_role_can_still_update_outcome(conn, tenants):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        conn.execute(
            "update public.runs set outcome = 'success', outcome_source = 'test', confidence = 1"
            " where id = %s",
            (a.run_id,),
        )


def test_api_role_cannot_record_firewall_results(conn, tenants):
    a, _ = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege), project_scope(conn, a.project_id):
        conn.execute(
            "select private.record_firewall_result(%s, %s, 'trusted', %s)",
            (a.project_id, a.run_id, Jsonb({})),
        )


def test_worker_records_firewall_results_for_one_run(conn, tenants):
    a, b = tenants
    with worker_scope(conn):
        conn.execute(
            "select private.record_firewall_result(%s, %s, 'trusted', %s)",
            (a.project_id, a.run_id, Jsonb({"0": "trusted"})),
        )
    rows = conn.execute(
        "select r.id, r.taint_level, r.processed_at is not null, s.input_trust"
        " from public.runs r join public.steps s on s.run_id = r.id and s.project_id = r.project_id"
        " where r.id in (%s, %s) order by r.id = %s desc",
        (a.run_id, b.run_id, a.run_id),
    ).fetchall()
    assert [row[1:] for row in rows] == [
        ("trusted", True, "trusted"),
        ("untrusted", False, "untrusted"),
    ]
