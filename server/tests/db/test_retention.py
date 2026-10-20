"""Retention (docs/constraints.md, Data rules): old raw data is deleted daily."""

import uuid

from psycopg.types.json import Jsonb


def old_run(conn, tenant, days_ago):
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id, created_at)"
        " values (%s, %s, %s, 't', 'm', now() - make_interval(days => %s))",
        (run_id, tenant.project_id, tenant.agent_id, days_ago),
    )
    conn.execute(
        "insert into public.steps (project_id, run_id, idx, type) values (%s, %s, 0, 'llm')",
        (tenant.project_id, run_id),
    )
    return run_id


def exists(conn, run_id):
    return conn.execute("select count(*) from public.runs where id = %s", (run_id,)).fetchone()[0]


def enforce(conn):
    return conn.execute("select private.enforce_retention()").fetchone()[0]


def test_runs_older_than_retention_are_deleted_with_their_steps(conn, tenants):
    a, _ = tenants
    expired = old_run(conn, a, 120)
    recent = old_run(conn, a, 10)
    enforce(conn)
    assert (exists(conn, expired), exists(conn, recent)) == (0, 1)
    assert (
        conn.execute("select count(*) from public.steps where run_id = %s", (expired,)).fetchone()[
            0
        ]
        == 0
    )


def test_retention_is_per_project(conn, tenants):
    a, b = tenants
    conn.execute("update public.projects set retention_days = 365 where id = %s", (b.project_id,))
    in_a, in_b = old_run(conn, a, 120), old_run(conn, b, 120)
    enforce(conn)
    assert (exists(conn, in_a), exists(conn, in_b)) == (0, 1)


def test_runs_supporting_live_memory_are_kept_until_it_is_retired(conn, tenants):
    a, _ = tenants
    source = old_run(conn, a, 400)
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, title, content_hash, steps)"
        " values (%s, %s, 'P', 'h', %s) returning id",
        (a.project_id, a.agent_id, Jsonb([])),
    ).fetchone()[0]
    conn.execute(
        "insert into public.provenance (project_id, object_type, object_id, source_run_ids,"
        " trust_level) values (%s, 'playbook', %s, %s, 'trusted')",
        (a.project_id, playbook_id, [source]),
    )
    enforce(conn)
    assert exists(conn, source) == 1  # provenance of live memory stays traceable
    conn.execute("update public.playbooks set status = 'retired' where id = %s", (playbook_id,))
    enforce(conn)
    assert exists(conn, source) == 0


def test_old_findings_recalls_and_results_go_too(conn, tenants):
    a, _ = tenants
    expired = old_run(conn, a, 120)
    conn.execute(
        "insert into public.firewall_findings (project_id, object_type, object_id, check_name,"
        " severity, detail) values (%s, 'run', %s, 'injection_heuristic', 'block', 'x')",
        (a.project_id, expired),
    )
    conn.execute(
        "insert into public.recalls (project_id, agent_id, mode, created_at)"
        " values (%s, %s, 'keyword', now() - interval '120 days')",
        (a.project_id, a.agent_id),
    )
    counts = enforce(conn)
    assert counts["recalls"] >= 1
    assert (
        conn.execute(
            "select count(*) from public.firewall_findings where object_id = %s", (expired,)
        ).fetchone()[0]
        == 0
    )


def test_retention_runs_daily_on_supabase_cron(conn):
    schedule = conn.execute(
        "select schedule, command from cron.job where jobname = 'retrack-retention'"
    ).fetchone()
    assert schedule == ("17 3 * * *", "select private.enforce_retention()")
