"""Database access helpers. Every query on customer data runs inside `project_scope`."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg


@contextmanager
def project_scope(conn: psycopg.Connection, project_id: UUID | None) -> Iterator[None]:
    """Run the enclosed queries as `retrack_api`, limited by RLS to one project.

    Opens a transaction (a savepoint when one is already open). On error the
    savepoint is rolled back, which also undoes the role and project settings.
    """
    with conn.transaction():
        conn.execute("set local role retrack_api")
        conn.execute(
            "select set_config('app.project_id', %s, true)",
            (str(project_id) if project_id else "",),
        )
        yield
        conn.execute("select set_config('app.project_id', '', true)")
        conn.execute("reset role")


def increment_usage(
    conn: psycopg.Connection,
    *,
    runs_captured: int = 0,
    recalls_served: int = 0,
    distillations: int = 0,
    tokens_processed: int = 0,
) -> None:
    """Add to today's usage counters for the project of the current `project_scope`."""
    conn.execute(
        "select private.increment_usage(%s, %s, %s, %s)",
        (runs_captured, recalls_served, distillations, tokens_processed),
    )


def enqueue_run(conn: psycopg.Connection, run_id: UUID) -> int:
    """Queue a stored run of the current project for processing. Returns the message id."""
    return conn.execute("select private.enqueue_run(%s)", (run_id,)).fetchone()[0]
