"""Super-admin analytics per project (Phase 12, docs/features.md block L): usage, runs,
recalls, success rates and costs across every organization; nobody else can read them."""

import uuid

import psycopg
import pytest


def add_run(conn, tenant, *, outcome, holdout=None, tokens=100, cost=0.01, playbooks=0):
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (project_id, id, agent_id, task_text, model_id, outcome,"
        " tokens_in, cost_usd, holdout) values (%s, %s, %s, 't', 'm', %s, %s, %s, %s)",
        (tenant.project_id, run_id, tenant.agent_id, outcome, tokens, cost, bool(holdout)),
    )
    if holdout is not None:
        conn.execute(
            "insert into public.recalls (project_id, agent_id, run_id, holdout, mode,"
            " playbook_ids) values (%s, %s, %s, %s, %s, %s)",
            (
                tenant.project_id,
                tenant.agent_id,
                run_id,
                holdout,
                "holdout" if holdout else "hybrid",
                [uuid.uuid4()] * playbooks,
            ),
        )


def stats(conn, users, user_id, days=30):
    with users.acting(user_id):
        return conn.execute("select public.dashboard_admin_project_stats(%s)", (days,)).fetchone()[
            0
        ]


def test_super_admin_gets_success_rates_and_costs_per_project(conn, tenants, users):
    a, b = tenants
    for outcome in ["success", "success", "success", "failure"]:
        add_run(conn, a, outcome=outcome, holdout=False, tokens=80, cost=0.5, playbooks=1)
    for outcome in ["success", "failure"]:
        add_run(conn, a, outcome=outcome, holdout=True, tokens=100, cost=1.0)
    conn.execute(
        "insert into public.usage_daily (project_id, day, llm_input_tokens, llm_output_tokens)"
        " values (%s, current_date, 1000, 200)",
        (a.project_id,),
    )
    gokul = users.make("gokul@example.com")
    conn.execute("insert into public.super_admins (user_id) values (%s)", (gokul,))
    rows = {row["project_id"]: row for row in stats(conn, users, gokul)}
    row = rows[str(a.project_id)]
    assert row["project"] == "project-a" and row["organization"] == "test-org"
    assert row["runs"] == 7  # the fixture's own run (unknown outcome) counts
    assert (row["known"], row["successes"]) == (6, 4)
    assert row["success_rate"] == pytest.approx(4 / 6)
    assert row["lift_points"] == pytest.approx((3 / 4 - 1 / 2) * 100)
    assert row["recalls"] == 6 and row["recall_hit_rate"] == pytest.approx(1.0)
    assert row["agent_tokens"] == 4 * 80 + 2 * 100
    assert row["agent_cost_usd"] == pytest.approx(4 * 0.5 + 2 * 1.0)
    assert (row["llm_input_tokens"], row["llm_output_tokens"]) == (1000, 200)
    assert row["last_run_at"] is not None
    assert rows[str(b.project_id)]["runs"] == 1
    assert rows[str(b.project_id)]["success_rate"] is None


def test_project_stats_are_super_admin_only(conn, tenants, users):
    a, _ = tenants
    owner = users.make()
    users.add(a.project_id, owner)
    for who in (owner, users.make()):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            stats(conn, users, who)


def test_overview_reports_platform_success_rate_and_agent_cost(conn, tenants, users):
    a, _ = tenants
    add_run(conn, a, outcome="success", cost=2.0)
    add_run(conn, a, outcome="failure", cost=1.0)
    gokul = users.make()
    conn.execute("insert into public.super_admins (user_id) values (%s)", (gokul,))
    with users.acting(gokul):
        overview = conn.execute("select public.dashboard_admin_overview()").fetchone()[0]
    assert overview["success_rate_30d"] is not None
    assert overview["agent_cost_30d"] >= 3.0
