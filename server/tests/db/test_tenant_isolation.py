"""Row-level security: one project can never see or change another project's rows."""

import uuid

import psycopg
import pytest

from retrack_server.db import project_scope

TENANT_TABLES = ["projects", "agents", "runs", "steps"]


def count(conn, table: str) -> int:
    return conn.execute(f"select count(*) from public.{table}").fetchone()[0]


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_project_sees_only_its_own_rows(conn, tenants, table):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        rows = conn.execute(
            f"select {'id' if table == 'projects' else 'project_id'} from public.{table}"
        ).fetchall()
    assert rows == [(a.project_id,)]


def test_no_project_set_sees_nothing(conn, tenants):
    with project_scope(conn, None):
        for table in TENANT_TABLES:
            assert count(conn, table) == 0


def test_cannot_insert_run_into_another_project(conn, tenants):
    a, b = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege), project_scope(conn, a.project_id):
        conn.execute(
            "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
            " values (%s, %s, %s, 'x', 'm')",
            (uuid.uuid4(), b.project_id, b.agent_id),
        )


def test_cannot_update_another_projects_run(conn, tenants):
    a, b = tenants
    with project_scope(conn, a.project_id):
        updated = conn.execute(
            "update public.runs set outcome = 'success' where id = %s", (b.run_id,)
        ).rowcount
    assert updated == 0
    outcome = conn.execute("select outcome from public.runs where id = %s", (b.run_id,))
    assert outcome.fetchone()[0] == "unknown"


def test_run_cannot_point_at_another_projects_agent(conn, tenants):
    a, b = tenants
    with pytest.raises(psycopg.errors.ForeignKeyViolation), project_scope(conn, a.project_id):
        conn.execute(
            "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
            " values (%s, %s, %s, 'x', 'm')",
            (uuid.uuid4(), a.project_id, b.agent_id),
        )


@pytest.mark.parametrize("table", ["organizations", "members", "api_keys"])
def test_api_role_has_no_direct_access_to_admin_tables(conn, tenants, table):
    a, _ = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege), project_scope(conn, a.project_id):
        conn.execute(f"select * from public.{table}")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize(
    "table", ["organizations", "projects", "agents", "members", "api_keys", "runs", "steps"]
)
def test_supabase_public_roles_have_no_access(conn, tenants, role, table):
    with conn.transaction(force_rollback=True):
        conn.execute(f"set local role {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"select * from public.{table}")
