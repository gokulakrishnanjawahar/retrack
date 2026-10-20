"""Regression tests from memory (docs/regression-migration.md): serve cases, record results.

Eval cases are created by database triggers when playbooks become active or failures
repeat; `retrack test` (SDK) runs them against the customer's agent and reports back.
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from retrack_server.db import project_scope
from retrack_server.schemas import EvalResultsIn


def list_cases(conn: psycopg.Connection, project_id: UUID, agent: str | None) -> list[dict]:
    with project_scope(conn, project_id):
        rows = conn.execute(
            "select c.id, c.source, c.input, c.expected_assertions, c.critical, c.last_result"
            " from public.eval_cases c join public.agents a on a.id = c.agent_id"
            " where c.project_id = %s and c.status = 'active'"
            " and (%s::text is null or a.name = %s) order by c.created_at",
            (project_id, agent, agent),
        ).fetchall()
    return [
        {
            "id": str(case_id),
            "source": source,
            "input": case_input,
            "assertions": assertions,
            "critical": critical,
            "last_result": last_result,
        }
        for case_id, source, case_input, assertions, critical, last_result in rows
    ]


def record_results(conn: psycopg.Connection, project_id: UUID, body: EvalResultsIn) -> int | None:
    """Store results; returns how many, or None if a case is not in this project."""
    with project_scope(conn, project_id):
        ids = [r.case_id for r in body.results]
        known = conn.execute(
            "select count(*) from public.eval_cases where project_id = %s and id = any(%s)",
            (project_id, ids),
        ).fetchone()[0]
        if known != len(set(ids)):
            return None
        for result in body.results:
            outcome = "passed" if result.passed else "failed"
            details: dict[str, Any] = result.details
            conn.execute(
                "insert into public.eval_results"
                " (project_id, eval_case_id, test_run_id, passed, model_id, details)"
                " values (%s, %s, %s, %s, %s, %s)",
                (
                    project_id,
                    result.case_id,
                    body.test_run_id,
                    result.passed,
                    body.model_id,
                    Jsonb(details),
                ),
            )
            conn.execute(
                "update public.eval_cases set last_result = %s, last_model_id = %s,"
                " last_run_at = now() where project_id = %s and id = %s",
                (outcome, body.model_id, project_id, result.case_id),
            )
    return len(body.results)
