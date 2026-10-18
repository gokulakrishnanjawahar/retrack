"""The server's own database login can do nothing until it switches to `retrack_api`."""

import os

import psycopg
import pytest


@pytest.fixture
def server_conn():
    url = os.environ.get("SERVER_DATABASE_URL")
    if not url:
        pytest.skip("SERVER_DATABASE_URL not set")
    with psycopg.connect(url, prepare_threshold=None) as connection:
        yield connection
        connection.rollback()


@pytest.mark.parametrize("table", ["runs", "projects", "api_keys", "organizations"])
def test_server_login_has_no_direct_table_access(server_conn, table):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        server_conn.execute(f"select * from public.{table}")


def test_server_login_can_switch_to_api_role(server_conn):
    server_conn.execute("set local role retrack_api")
    assert server_conn.execute("select current_user").fetchone()[0] == "retrack_api"


def test_server_login_can_switch_to_worker_role(server_conn):
    server_conn.execute("set local role retrack_worker")
    assert server_conn.execute("select current_user").fetchone()[0] == "retrack_worker"


def test_server_login_cannot_switch_to_admin_roles(server_conn):
    for role in ("postgres", "service_role"):
        with (
            server_conn.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            server_conn.execute(f"set local role {role}")
