"""Daily usage counters, always written to the caller's own project."""

from retrack_server.db import increment_usage, project_scope


def usage(conn, project_id):
    return conn.execute(
        "select runs_captured, recalls_served, distillations, tokens_processed"
        " from public.usage_daily where project_id = %s and day = (now() at time zone 'utc')::date",
        (project_id,),
    ).fetchone()


def test_increments_accumulate_for_the_day(conn, tenants):
    a, _ = tenants
    with project_scope(conn, a.project_id):
        increment_usage(conn, runs_captured=1, tokens_processed=100)
        increment_usage(conn, runs_captured=1, recalls_served=3, tokens_processed=50)
    assert usage(conn, a.project_id) == (2, 3, 0, 150)


def test_increments_never_touch_other_projects(conn, tenants):
    a, b = tenants
    with project_scope(conn, a.project_id):
        increment_usage(conn, runs_captured=1)
    assert usage(conn, b.project_id) is None


def test_project_sees_only_its_own_usage(conn, tenants):
    a, b = tenants
    with project_scope(conn, b.project_id):
        increment_usage(conn, runs_captured=5)
    with project_scope(conn, a.project_id):
        increment_usage(conn, runs_captured=1)
        rows = conn.execute("select project_id from public.usage_daily").fetchall()
    assert rows == [(a.project_id,)]
