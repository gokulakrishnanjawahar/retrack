"""Storing an ingested run (POST /v1/runs).

Redaction happens here, before anything leaves the process. Storage is one database
function (private.store_run_payload): run, steps, outcome hint, queue message and usage
in one transaction. The public endpoint calls private.ingest_run, which also checks the
API key and the project's rate limit, and sends it in a single batched round trip.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from retrack_server.api_keys import InvalidKeyFormat, hash_key, key_prefix
from retrack_server.db import project_scope
from retrack_server.redaction import redact_text, redact_value
from retrack_server.schemas import MAX_OUTPUT_CHARS, MAX_RESULT_CHARS, RunIn


def args_hash(args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def redacted_payload(run: RunIn) -> dict[str, Any]:
    """The run as stored: task, arguments, results and answer with secrets and PII removed."""
    steps = []
    for step in run.steps:
        args = redact_value(step.args)[0]
        steps.append(
            {
                "idx": step.idx,
                "type": step.type,
                "tool_name": step.tool_name,
                "args_hash": args_hash(args),
                "args_redacted": args,
                "result_class": step.result_class,
                "error_class": step.error_class,
                "latency_ms": step.latency_ms,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
                "input_trust": step.input_trust,
                "result_redacted": redact_text(step.result)[0][:MAX_RESULT_CHARS]
                if step.result
                else None,
            }
        )
    hint = run.outcome_hint
    return {
        "id": str(run.id),
        "agent": run.agent,
        "task": redact_text(run.task)[0],
        "model_id": run.model_id,
        "tool_versions": run.tool_versions,
        "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out,
        "cost_usd": run.cost_usd,
        "latency_ms": run.latency_ms,
        "output": redact_text(run.output)[0][:MAX_OUTPUT_CHARS] if run.output else None,
        "outcome_hint": {"outcome": hint.outcome, "source": hint.source} if hint else None,
        "steps": steps,
    }


def ingest(conn: psycopg.Connection, secret: str, pepper: str, run: RunIn) -> dict[str, Any]:
    """Authenticate, rate-limit and store a run in one round trip.

    Returns {"status": "stored" | "duplicate" | "unauthorized" | "rate_limited", ...}.
    """
    try:
        prefix = key_prefix(secret)
    except InvalidKeyFormat:
        return {"status": "unauthorized"}
    payload = Jsonb(redacted_payload(run))
    with conn.transaction():
        with conn.pipeline():
            conn.execute("set local role retrack_api")
            cursor = conn.execute(
                "select private.ingest_run(%s, %s, %s)", (prefix, hash_key(secret, pepper), payload)
            )
            conn.execute("select set_config('app.project_id', '', true)")
            conn.execute("reset role")
        return cursor.fetchone()[0]


def store_run(conn: psycopg.Connection, project_id: UUID, run: RunIn) -> bool:
    """Store a run for a project already known to be authorised (trusted server code).

    Returns True if this run id was already stored.
    """
    with project_scope(conn, project_id):
        result = conn.execute(
            "select private.store_run_payload(%s, %s)",
            (project_id, Jsonb(redacted_payload(run))),
        ).fetchone()[0]
    return result["status"] == "duplicate"
