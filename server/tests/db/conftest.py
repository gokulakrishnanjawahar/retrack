"""Fixtures for tests that run against the dev Supabase database.

Every test runs inside one transaction that is rolled back, so the dev
database is left unchanged. Tests are skipped when DATABASE_URL is not set.
"""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip())


_load_dotenv()


@pytest.fixture
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    with psycopg.connect(url) as connection:
        yield connection
        connection.rollback()


@dataclass
class Tenant:
    project_id: uuid.UUID
    agent_id: uuid.UUID
    run_id: uuid.UUID


def _make_tenant(conn, org_id: uuid.UUID, name: str) -> Tenant:
    project_id = conn.execute(
        "insert into public.projects (org_id, name) values (%s, %s) returning id", (org_id, name)
    ).fetchone()[0]
    agent_id = conn.execute(
        "insert into public.agents (project_id, name, framework)"
        " values (%s, 'support-agent', 'langgraph') returning id",
        (project_id,),
    ).fetchone()[0]
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
        " values (%s, %s, %s, %s, 'test-model')",
        (run_id, project_id, agent_id, f"task for {name}"),
    )
    conn.execute(
        "insert into public.steps (project_id, run_id, idx, type, tool_name)"
        " values (%s, %s, 0, 'tool', 'orders_api')",
        (project_id, run_id),
    )
    return Tenant(project_id, agent_id, run_id)


@pytest.fixture
def tenants(conn) -> tuple[Tenant, Tenant]:
    """Two projects in one org, each with an agent, a run and a step. Created as admin."""
    org_id = conn.execute(
        "insert into public.organizations (name) values ('test-org') returning id"
    ).fetchone()[0]
    return _make_tenant(conn, org_id, "project-a"), _make_tenant(conn, org_id, "project-b")
