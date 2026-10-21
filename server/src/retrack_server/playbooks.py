"""Playbook endpoints (docs/api.md, Phase 13): list memory, read a playbook's versions, and
take a playbook out of service. Reads and writes run in `pipeline_scope`, so row-level
security keeps every query inside the API key's project. Approving and rolling back are not
here: they need a person in the dashboard (docs/decisions.md)."""

from typing import Any
from uuid import UUID

import psycopg

from retrack_server.db import pipeline_scope

STATUSES = ("active", "candidate", "quarantined", "retired")


def list_playbooks(
    conn: psycopg.Connection, project_id: UUID, agent: str | None, status: str, limit: int
) -> list[dict[str, Any]]:
    with pipeline_scope(conn, project_id):
        rows = conn.execute(
            "select p.id, a.name, p.status, p.version, p.title, p.task_pattern, p.preconditions,"
            " p.steps, p.pitfalls, p.uses, p.successes, p.success_rate, p.confidence,"
            " p.validated_models, p.tool_versions, p.origin_playbook_id, p.updated_at"
            " from public.playbooks p"
            " join public.agents a on a.id = p.agent_id and a.project_id = p.project_id"
            " where p.project_id = %(project)s"
            " and (%(agent)s::text is null or a.name = %(agent)s)"
            " and (%(status)s = 'all' or p.status = %(status)s)"
            " order by p.updated_at desc limit %(limit)s",
            {"project": project_id, "agent": agent, "status": status, "limit": limit},
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "agent": row[1],
            "status": row[2],
            "version": row[3],
            "title": row[4],
            "task_pattern": row[5],
            "preconditions": row[6],
            "steps": row[7],
            "pitfalls": row[8],
            "uses": row[9],
            "successes": row[10],
            "success_rate": row[11],
            "confidence": row[12],
            "validated_models": row[13],
            "tool_versions": row[14],
            "origin_playbook_id": str(row[15]) if row[15] else None,
            "updated_at": row[16].isoformat(),
        }
        for row in rows
    ]


def list_versions(
    conn: psycopg.Connection, project_id: UUID, playbook_id: UUID
) -> list[dict[str, Any]] | None:
    """Versions newest first, or None if the playbook is not in this project."""
    with pipeline_scope(conn, project_id):
        found = conn.execute(
            "select 1 from public.playbooks where project_id = %s and id = %s",
            (project_id, playbook_id),
        ).fetchone()
        if found is None:
            return None
        rows = conn.execute(
            "select version, snapshot, change_reason, created_at from public.playbook_versions"
            " where project_id = %s and playbook_id = %s order by version desc",
            (project_id, playbook_id),
        ).fetchall()
    return [
        {"version": v, "snapshot": snap, "change_reason": reason, "created_at": at.isoformat()}
        for v, snap, reason, at in rows
    ]


def set_status(
    conn: psycopg.Connection,
    project_id: UUID,
    playbook_id: UUID,
    status: str,
    who: str,
    note: str | None,
) -> str | None:
    """Quarantine (back to review) or retire; the same rule the dashboard uses. Returns the
    new status, or None if the playbook is not in this project."""
    with pipeline_scope(conn, project_id):
        return conn.execute(
            "select private.set_playbook_status(%s, %s, %s, %s, %s)",
            (project_id, playbook_id, status, who, note),
        ).fetchone()[0]
