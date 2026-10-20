"""Model-migration reports (docs/regression-migration.md, "Model migration").

`retrack migrate` replays the eval cases on the customer's agent with a new model and
posts the results with a migration id. Each item is classified:

    playbook case:  passes (and the model joins validated_models) | needs_relearning
                    (completed, but not as the playbook describes) | breaks (errored)
    failure case:   fixed | returns
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from retrack_server.db import project_scope
from retrack_server.schemas import MigrationIn

COUNT_KEYS = ("passes", "needs_relearning", "breaks", "fixed", "returns")


def create_migration(conn: psycopg.Connection, project_id: UUID, body: MigrationIn) -> UUID | None:
    with project_scope(conn, project_id):
        agent = conn.execute(
            "select id from public.agents where project_id = %s and name = %s",
            (project_id, body.agent),
        ).fetchone()
        if agent is None:
            return None
        return conn.execute(
            "insert into public.migration_reports"
            " (project_id, agent_id, from_model, to_model, model_applied)"
            " values (%s, %s, %s, %s, %s) returning id",
            (project_id, agent[0], body.from_model, body.to_model, body.model_applied),
        ).fetchone()[0]


def _classify(source: str, passed: bool, completed: bool) -> str:
    if source == "failure":
        return "fixed" if passed else "returns"
    if passed:
        return "passes"
    return "needs_relearning" if completed else "breaks"


def finalize(conn: psycopg.Connection, project_id: UUID, migration_id: UUID) -> None:
    """Rebuild the report from its latest result per case. Call inside project_scope."""
    to_model = conn.execute(
        "select to_model from public.migration_reports where project_id = %s and id = %s",
        (project_id, migration_id),
    ).fetchone()[0]
    rows = conn.execute(
        "select distinct on (r.eval_case_id) r.eval_case_id, r.passed, r.details,"
        " c.source, c.source_id, c.expected_assertions"
        " from public.eval_results r join public.eval_cases c on c.id = r.eval_case_id"
        " where r.project_id = %s and r.migration_id = %s"
        " order by r.eval_case_id, r.created_at desc",
        (project_id, migration_id),
    ).fetchall()
    counts = dict.fromkeys(COUNT_KEYS, 0)
    items: list[dict[str, Any]] = []
    for case_id, passed, details, source, source_id, assertions in rows:
        outcome = _classify(source, passed, bool((details or {}).get("completed", passed)))
        counts[outcome] += 1
        if source == "playbook":
            title = conn.execute(
                "select title from public.playbooks where project_id = %s and id = %s",
                (project_id, source_id),
            ).fetchone()
            title = title[0] if title else "(playbook not visible)"
            if outcome == "passes":
                conn.execute(
                    "select private.validate_playbook_model(%s, %s, %s)",
                    (project_id, source_id, to_model),
                )
        else:
            check = next((a for a in assertions if a.get("type") == "no_failure"), {})
            title = f"{check.get('tool', '?')} failing with {check.get('error_class', '?')}"
        items.append(
            {
                "case_id": str(case_id),
                "source": source,
                "source_id": str(source_id),
                "title": title,
                "result": outcome,
                "failures": (details or {}).get("failures", []),
            }
        )
    conn.execute(
        "update public.migration_reports set status = 'completed', completed_at = now(),"
        " summary = %s where project_id = %s and id = %s",
        (Jsonb({"counts": counts, "items": items}), project_id, migration_id),
    )


def migration_is_open(conn: psycopg.Connection, project_id: UUID, migration_id: UUID) -> bool:
    return (
        conn.execute(
            "select 1 from public.migration_reports where project_id = %s and id = %s",
            (project_id, migration_id),
        ).fetchone()
        is not None
    )


def get_migration(
    conn: psycopg.Connection, project_id: UUID, migration_id: UUID
) -> dict[str, Any] | None:
    with project_scope(conn, project_id):
        row = conn.execute(
            "select m.id, a.name, m.from_model, m.to_model, m.model_applied, m.status,"
            " m.summary, m.created_at, m.completed_at"
            " from public.migration_reports m join public.agents a on a.id = m.agent_id"
            " where m.project_id = %s and m.id = %s",
            (project_id, migration_id),
        ).fetchone()
    if row is None:
        return None
    keys = (
        "id",
        "agent",
        "from_model",
        "to_model",
        "model_applied",
        "status",
        "summary",
        "created_at",
        "completed_at",
    )
    report = dict(zip(keys, row, strict=True))
    report["id"] = str(report["id"])
    for key in ("created_at", "completed_at"):
        report[key] = report[key].isoformat() if report[key] else None
    return report
