"""Storing an ingested run: run, steps, queue message and usage, in one transaction."""

import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from retrack_server.db import enqueue_run, increment_usage, project_scope
from retrack_server.redaction import redact_text, redact_value
from retrack_server.schemas import RunIn
from retrack_server.scoring import add_signal


def args_hash(args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _agent_id(conn: psycopg.Connection, project_id: UUID, name: str) -> UUID:
    row = conn.execute(
        "insert into public.agents (project_id, name) values (%s, %s)"
        " on conflict (project_id, name) do nothing returning id",
        (project_id, name),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "select id from public.agents where project_id = %s and name = %s",
            (project_id, name),
        ).fetchone()
    return row[0]


def store_run(conn: psycopg.Connection, project_id: UUID, run: RunIn) -> bool:
    """Store a run for a project. Returns True if this run id was already stored."""
    hint = run.outcome_hint
    # Redact before anything is stored: raw secrets and personal data never reach the database.
    task_text, _ = redact_text(run.task)
    redacted_args = [redact_value(step.args)[0] for step in run.steps]
    with project_scope(conn, project_id):
        agent_id = _agent_id(conn, project_id, run.agent)
        inserted = conn.execute(
            "insert into public.runs (project_id, id, agent_id, task_text, model_id,"
            " tool_versions, tokens_in, tokens_out, cost_usd, latency_ms)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " on conflict (project_id, id) do nothing returning id",
            (
                project_id,
                run.id,
                agent_id,
                task_text,
                run.model_id,
                Jsonb(run.tool_versions),
                run.tokens_in,
                run.tokens_out,
                run.cost_usd,
                run.latency_ms,
            ),
        ).fetchone()
        if inserted is None:
            return True

        with conn.cursor() as cur:
            cur.executemany(
                "insert into public.steps (project_id, run_id, idx, type, tool_name, args_hash,"
                " args_redacted, result_class, error_class, latency_ms, tokens_in, tokens_out,"
                " input_trust)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        project_id,
                        run.id,
                        step.idx,
                        step.type,
                        step.tool_name,
                        args_hash(args),
                        Jsonb(args),
                        step.result_class,
                        step.error_class,
                        step.latency_ms,
                        step.tokens_in,
                        step.tokens_out,
                        step.input_trust,
                    )
                    for step, args in zip(run.steps, redacted_args, strict=True)
                ],
            )
        if hint:
            add_signal(conn, project_id, run.id, hint.source, hint.outcome)
        enqueue_run(conn, run.id)
        increment_usage(conn, runs_captured=1, tokens_processed=run.tokens_in + run.tokens_out)
    return False
