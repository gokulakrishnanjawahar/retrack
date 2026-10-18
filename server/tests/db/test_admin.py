"""Admin helpers used by the `retrack-admin` command (runs with the admin database login)."""

from retrack_server.admin import create_project
from retrack_server.api_keys import verify_api_key

PEPPER = "test-pepper"


def test_create_project_returns_working_key(conn):
    created = create_project(conn, "Acme", "support", PEPPER)
    assert verify_api_key(conn, created.key.secret, PEPPER) == created.project_id
    org = conn.execute(
        "select o.name from public.projects p join public.organizations o on o.id = p.org_id"
        " where p.id = %s",
        (created.project_id,),
    ).fetchone()[0]
    assert org == "Acme"


def test_create_project_reuses_existing_org(conn):
    first = create_project(conn, "Acme", "support", PEPPER)
    second = create_project(conn, "Acme", "billing", PEPPER)
    assert first.org_id == second.org_id
    assert first.project_id != second.project_id
