"""Background worker: drains the `runs` queue and runs the pipelines on each job
(firewall, then scoring, then distillation).

Called by POST /internal/drain, which Supabase Cron triggers every minute.
"""

import logging
import time
from dataclasses import dataclass, field
from uuid import UUID

import psycopg

from retrack_server.db import worker_scope
from retrack_server.distiller import distill_run
from retrack_server.embeddings import Embedder
from retrack_server.firewall import process_run
from retrack_server.llm import LLMClient
from retrack_server.scoring import score_run

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
VISIBILITY_SECONDS = 120
BATCH = 10
TIME_BUDGET_SECONDS = 45


@dataclass(frozen=True)
class Job:
    msg_id: int
    read_count: int
    project_id: UUID
    run_id: UUID


@dataclass
class DrainResult:
    processed: int = 0
    retrying: int = 0
    dead_lettered: int = 0
    # Firewall done, but scoring or distillation failed on every attempt: run kept as is.
    scoring_gave_up: int = 0
    errors: list[str] = field(default_factory=list)


def read_jobs(conn: psycopg.Connection, *, batch: int, visibility_seconds: int) -> list[Job]:
    """Take up to `batch` ready jobs; each stays hidden from other readers for a while."""
    with worker_scope(conn):
        rows = conn.execute(
            "select msg_id, read_ct, project_id, run_id from private.read_run_jobs(%s, %s)",
            (batch, visibility_seconds),
        ).fetchall()
    return [Job(*row) for row in rows]


def complete_job(conn: psycopg.Connection, msg_id: int) -> None:
    with worker_scope(conn):
        conn.execute("select private.complete_run_job(%s)", (msg_id,))


def dead_letter_job(conn: psycopg.Connection, msg_id: int, error: str) -> None:
    with worker_scope(conn):
        conn.execute("select private.dead_letter_run_job(%s, %s)", (msg_id, error))


def drain(
    conn: psycopg.Connection,
    *,
    batch: int = BATCH,
    visibility_seconds: int = VISIBILITY_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
    time_budget_seconds: float = TIME_BUDGET_SECONDS,
    llm: LLMClient | None = None,
    embedder: Embedder | None = None,
) -> DrainResult:
    """Process ready jobs until the queue is empty or the time budget is used up."""
    result = DrainResult()
    deadline = time.monotonic() + time_budget_seconds
    while time.monotonic() < deadline:
        jobs = read_jobs(conn, batch=batch, visibility_seconds=visibility_seconds)
        if not jobs:
            break
        for job in jobs:
            # Checked before every job: a slow batch must not outlive the visibility
            # timeout, or another worker would pick the same jobs (and pay the judge twice).
            # Jobs not reached here reappear once their visibility timeout ends.
            if time.monotonic() >= deadline:
                break
            stage = "firewall"
            try:
                # The firewall result is committed on its own, so a judge outage cannot
                # undo it; on retry the firewall simply runs again (it is idempotent).
                with conn.transaction():
                    process_run(conn, job.project_id, job.run_id)
                stage = "scoring"
                with conn.transaction():
                    score_run(conn, job.project_id, job.run_id, llm)
                stage = "distillation"
                with conn.transaction():
                    distill_run(conn, job.project_id, job.run_id, llm=llm, embedder=embedder)
                    complete_job(conn, job.msg_id)
                result.processed += 1
            except Exception as exc:
                error = f"{stage}: {type(exc).__name__}: {exc}"
                logger.warning("job %s for run %s failed: %s", job.msg_id, job.run_id, error)
                result.errors.append(error)
                if job.read_count < max_attempts:
                    result.retrying += 1
                elif stage in ("scoring", "distillation"):
                    complete_job(conn, job.msg_id)
                    result.scoring_gave_up += 1
                else:
                    dead_letter_job(conn, job.msg_id, error)
                    result.dead_lettered += 1
    return result
