"""Scoring (docs/architecture.md, "Scorer pipeline"): decide each run's outcome.

Hard signals (tests, business events, user feedback) always beat the AI judge, which
runs only when no hard signal exists and at most once per run. Every signal is kept in
outcome_signals; the run stores the winning one.
"""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from retrack_server.db import project_scope
from retrack_server.judge import judge_run
from retrack_server.llm import LLMClient

SOURCE_RANK = {"test": 3, "event": 2, "feedback": 1, "judge": 0}
SOURCE_CONFIDENCE = {"test": 1.0, "event": 0.9, "feedback": 0.8}


def add_signal(
    conn: psycopg.Connection,
    project_id: UUID,
    run_id: UUID,
    source: str,
    outcome: str,
    confidence: float | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record a signal and re-resolve the run's outcome. Call inside a project_scope."""
    conn.execute(
        "insert into public.outcome_signals"
        " (project_id, run_id, source, outcome, confidence, detail)"
        " values (%s, %s, %s, %s, %s, %s)",
        (
            project_id,
            run_id,
            source,
            outcome,
            SOURCE_CONFIDENCE.get(source, 0.0) if confidence is None else confidence,
            Jsonb(detail or {}),
        ),
    )
    resolve_outcome(conn, project_id, run_id)


def resolve_outcome(conn: psycopg.Connection, project_id: UUID, run_id: UUID) -> None:
    """Store the best signal on the run: highest-ranked source, latest (by seq) within it."""
    rows = conn.execute(
        "select source, outcome, confidence, seq from public.outcome_signals"
        " where project_id = %s and run_id = %s",
        (project_id, run_id),
    ).fetchall()
    if not rows:
        return
    source, outcome, confidence, _ = max(rows, key=lambda r: (SOURCE_RANK[r[0]], r[3]))
    conn.execute(
        "update public.runs set outcome = %s, outcome_source = %s, confidence = %s"
        " where project_id = %s and id = %s",
        (outcome, source, confidence, project_id, run_id),
    )


def score_run(
    conn: psycopg.Connection, project_id: UUID, run_id: UUID, llm: LLMClient | None
) -> str:
    """Resolve a run's outcome, asking the judge only if nothing else is known."""
    with project_scope(conn, project_id):
        run = conn.execute(
            "select task_text, taint_level, output_text from public.runs"
            " where project_id = %s and id = %s",
            (project_id, run_id),
        ).fetchone()
        if run is None:
            raise LookupError(f"run {run_id} not found in project {project_id}")
        has_signal = conn.execute(
            "select exists (select 1 from public.outcome_signals"
            " where project_id = %s and run_id = %s)",
            (project_id, run_id),
        ).fetchone()[0]
        if has_signal or llm is None:
            resolve_outcome(conn, project_id, run_id)
            return "resolved" if has_signal else "unknown"

        steps = conn.execute(
            "select idx, type, tool_name, args_redacted, result_class, error_class,"
            " result_redacted from public.steps where project_id = %s and run_id = %s order by idx",
            (project_id, run_id),
        ).fetchall()
        verdict = judge_run(
            llm,
            run[0],
            [
                dict(
                    zip(
                        (
                            "idx",
                            "type",
                            "tool_name",
                            "args",
                            "result_class",
                            "error_class",
                            "result",
                        ),
                        s,
                        strict=True,
                    )
                )
                for s in steps
            ],
            trusted=run[1] == "trusted",
            output=run[2],
        )
        conn.execute(
            "select private.increment_llm_usage(%s, %s)",
            (verdict.usage.input_tokens, verdict.usage.output_tokens),
        )
        if verdict.outcome is None:
            return "unknown"
        add_signal(
            conn,
            project_id,
            run_id,
            "judge",
            verdict.outcome,
            verdict.confidence,
            {"reason": verdict.reason, "model": verdict.usage.model},
        )
        return "judged"
