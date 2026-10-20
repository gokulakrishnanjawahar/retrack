"""Dashboard access (Phase 12): logged-in users see only their own organizations' projects,
change things only through role-checked functions, and only super admins see everything."""

import json
import uuid
from contextlib import contextmanager

import psycopg
import pytest

from retrack_server.api_keys import generate_key, hash_key, verify_api_key

PEPPER = "test-pepper"


def make_user(conn, email: str | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, email, aud, role, created_at)"
        " values (%s, %s, 'authenticated', 'authenticated', now())",
        (user_id, email or f"{user_id}@example.com"),
    )
    return user_id


@contextmanager
def as_user(conn, user_id: uuid.UUID | None, email: str = "user@example.com"):
    """Run as Supabase's `authenticated` role with a JWT for `user_id` (None: no subject)."""
    claims = {"role": "authenticated", "email": email}
    if user_id is not None:
        claims["sub"] = str(user_id)
    with conn.transaction():
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
        yield
        conn.execute("select set_config('request.jwt.claims', '', true)")
        conn.execute("reset role")


def add_member(conn, org_id, user_id, role="owner"):
    conn.execute(
        "insert into public.members (org_id, user_id, role) values (%s, %s, %s)",
        (org_id, user_id, role),
    )


def org_of(conn, project_id):
    return conn.execute(
        "select org_id from public.projects where id = %s", (project_id,)
    ).fetchone()[0]


@pytest.fixture
def two_orgs(conn, tenants):
    """Project A in org 1 (owned by `alice`), project B in a separate org 2 (owned by `bob`)."""
    a, b = tenants
    other_org = conn.execute(
        "insert into public.organizations (name) values ('other-org') returning id"
    ).fetchone()[0]
    conn.execute("update public.projects set org_id = %s where id = %s", (other_org, b.project_id))
    alice, bob = make_user(conn, "alice@example.com"), make_user(conn, "bob@example.com")
    add_member(conn, org_of(conn, a.project_id), alice)
    add_member(conn, other_org, bob)
    return a, b, alice, bob


# Reading --------------------------------------------------------------------------------

READ_TABLES = ["projects", "agents", "runs", "steps"]


@pytest.mark.parametrize("table", READ_TABLES)
def test_member_sees_only_their_organizations_projects(conn, two_orgs, table):
    a, _, alice, _ = two_orgs
    column = "id" if table == "projects" else "project_id"
    with as_user(conn, alice):
        rows = conn.execute(f"select distinct {column} from public.{table}").fetchall()
    assert rows == [(a.project_id,)]


@pytest.mark.parametrize("table", READ_TABLES + ["organizations", "members", "playbooks"])
def test_user_without_membership_sees_nothing(conn, two_orgs, table):
    stranger = make_user(conn)
    with as_user(conn, stranger):
        assert conn.execute(f"select count(*) from public.{table}").fetchone()[0] == 0


def test_no_subject_sees_nothing(conn, two_orgs):
    with as_user(conn, None):
        assert conn.execute("select count(*) from public.runs").fetchone()[0] == 0


def test_member_sees_key_prefix_but_never_the_hash(conn, two_orgs):
    a, _, alice, _ = two_orgs
    conn.execute(
        "insert into public.api_keys (project_id, prefix, key_hash, name)"
        " values (%s, 'rtk_live_aaaaaaaa', 'secret-hash', 'ci')",
        (a.project_id,),
    )
    with as_user(conn, alice):
        assert conn.execute("select prefix, name from public.api_keys").fetchall() == [
            ("rtk_live_aaaaaaaa", "ci")
        ]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, alice):
        conn.execute("select key_hash from public.api_keys")


@pytest.mark.parametrize(
    "statement",
    [
        "update public.runs set outcome = 'success'",
        "delete from public.runs",
        "update public.projects set trusted_tools = '{x}'",
        "insert into public.members (org_id, user_id, role)"
        " select id, auth.uid(), 'owner' from public.organizations",
        "update public.playbooks set status = 'active'",
    ],
)
def test_users_cannot_write_tables_directly(conn, two_orgs, statement):
    _, _, alice, _ = two_orgs
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, alice):
        conn.execute(statement)


def test_users_cannot_see_super_admins_or_call_private_functions(conn, two_orgs):
    _, _, alice, _ = two_orgs
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, alice):
        conn.execute("select * from public.super_admins")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, alice):
        conn.execute("select private.verify_api_key('rtk_live_aaaaaaaa', 'x')")


def test_runs_are_published_for_realtime(conn):
    assert conn.execute(
        "select 1 from pg_publication_tables where pubname = 'supabase_realtime'"
        " and schemaname = 'public' and tablename = 'runs'"
    ).fetchone()


# Onboarding -----------------------------------------------------------------------------


def test_create_workspace_makes_the_user_owner(conn):
    user = make_user(conn)
    with as_user(conn, user):
        project_id = conn.execute(
            "select public.dashboard_create_workspace('Acme', 'support')"
        ).fetchone()[0]
        assert conn.execute("select id, name from public.projects").fetchall() == [
            (project_id, "support")
        ]
    assert conn.execute(
        "select m.role from public.members m join public.projects p on p.org_id = m.org_id"
        " where p.id = %s and m.user_id = %s",
        (project_id, user),
    ).fetchone() == ("owner",)


def test_create_workspace_needs_a_signed_in_user_and_names(conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, None):
        conn.execute("select public.dashboard_create_workspace('Acme', 'support')")
    user = make_user(conn)
    with pytest.raises(psycopg.errors.InvalidParameterValue), as_user(conn, user):
        conn.execute("select public.dashboard_create_workspace(' ', 'support')")


def test_anon_cannot_call_dashboard_functions(conn):
    with conn.transaction(force_rollback=True):
        conn.execute("set local role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select public.dashboard_create_workspace('Acme', 'support')")


# API keys -------------------------------------------------------------------------------


def add_key(conn, project_id):
    key = generate_key()
    key_id = conn.execute(
        "select public.dashboard_add_api_key(%s, 'ci', %s, %s)",
        (project_id, key.prefix, hash_key(key.secret, PEPPER)),
    ).fetchone()[0]
    return key_id, key


def test_owner_adds_a_key_that_the_api_accepts(conn, two_orgs):
    a, _, alice, _ = two_orgs
    with as_user(conn, alice):
        _, key = add_key(conn, a.project_id)
    assert verify_api_key(conn, key.secret, PEPPER) == a.project_id


@pytest.mark.parametrize("role", ["member", None])
def test_plain_members_and_outsiders_cannot_add_keys(conn, two_orgs, role):
    a, _, _, bob = two_orgs
    user = make_user(conn)
    if role:
        add_member(conn, org_of(conn, a.project_id), user, role)
    for who in (user, bob):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, who):
            add_key(conn, a.project_id)


def test_malformed_keys_are_refused(conn, two_orgs):
    a, _, alice, _ = two_orgs
    with pytest.raises(psycopg.errors.InvalidParameterValue), as_user(conn, alice):
        conn.execute(
            "select public.dashboard_add_api_key(%s, 'ci', 'rtk_live_aaaaaaaa', 'not-a-hash')",
            (a.project_id,),
        )


def test_owner_revokes_a_key_and_outsiders_cannot(conn, two_orgs):
    a, _, alice, bob = two_orgs
    with as_user(conn, alice):
        key_id, key = add_key(conn, a.project_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, bob):
        conn.execute("select public.dashboard_revoke_api_key(%s)", (key_id,))
    assert verify_api_key(conn, key.secret, PEPPER) == a.project_id
    with as_user(conn, alice):
        conn.execute("select public.dashboard_revoke_api_key(%s)", (key_id,))
    assert verify_api_key(conn, key.secret, PEPPER) is None


# Project settings -----------------------------------------------------------------------


def test_owner_updates_settings_and_null_keeps_a_value(conn, two_orgs):
    a, _, alice, _ = two_orgs
    with as_user(conn, alice):
        conn.execute(
            "select public.dashboard_update_project(%s, %s, true, null, 30, null)",
            (a.project_id, ["orders_api"]),
        )
    assert conn.execute(
        "select trusted_tools, task_trusted, holdout_rate, retention_days, ingest_rate_limit"
        " from public.projects where id = %s",
        (a.project_id,),
    ).fetchone() == (["orders_api"], True, pytest.approx(0.1), 30, 600)


def test_outsider_cannot_update_settings_and_bad_values_are_refused(conn, two_orgs):
    a, _, alice, bob = two_orgs
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, bob):
        conn.execute(
            "select public.dashboard_update_project(%s, '{x}', true, null, null, null)",
            (a.project_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), as_user(conn, alice):
        conn.execute(
            "select public.dashboard_update_project(%s, null, null, 2, null, null)",
            (a.project_id,),
        )


# Review queue ---------------------------------------------------------------------------


def quarantined_playbook(conn, tenant):
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, content_hash)"
        " values (%s, %s, 'quarantined', 'Suspicious', 'h') returning id",
        (tenant.project_id, tenant.agent_id),
    ).fetchone()[0]
    item_id = conn.execute(
        "insert into public.review_queue (project_id, object_type, object_id, reason)"
        " values (%s, 'playbook', %s, 'quarantined') returning id",
        (tenant.project_id, playbook_id),
    ).fetchone()[0]
    return playbook_id, item_id


def test_owner_approves_a_review_with_their_email_recorded(conn, two_orgs):
    a, _, alice, _ = two_orgs
    playbook_id, item_id = quarantined_playbook(conn, a)
    with as_user(conn, alice, email="alice@example.com"):
        conn.execute("select public.dashboard_resolve_review(%s, true, 'checked')", (item_id,))
    assert conn.execute(
        "select status, approved_by from public.playbooks where id = %s", (playbook_id,)
    ).fetchone() == ("active", "alice@example.com")
    assert conn.execute(
        "select status, reviewer, resolution_note from public.review_queue where id = %s",
        (item_id,),
    ).fetchone() == ("approved", "alice@example.com", "checked")


def test_reject_retires_and_resolving_twice_or_as_outsider_is_refused(conn, two_orgs):
    a, _, alice, bob = two_orgs
    playbook_id, item_id = quarantined_playbook(conn, a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, bob):
        conn.execute("select public.dashboard_resolve_review(%s, true, '')", (item_id,))
    with as_user(conn, alice):
        conn.execute("select public.dashboard_resolve_review(%s, false, 'poisoned')", (item_id,))
    assert conn.execute(
        "select status from public.playbooks where id = %s", (playbook_id,)
    ).fetchone() == ("retired",)
    with pytest.raises(psycopg.errors.InvalidParameterValue), as_user(conn, alice):
        conn.execute("select public.dashboard_resolve_review(%s, true, '')", (item_id,))


# Super admin ----------------------------------------------------------------------------


def test_only_super_admins_get_the_cross_project_overview(conn, two_orgs):
    _, _, alice, _ = two_orgs
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, alice):
        conn.execute("select public.dashboard_admin_overview()")
    with as_user(conn, alice):
        assert conn.execute("select public.dashboard_is_super_admin()").fetchone() == (False,)
    gokul = make_user(conn, "gokul@example.com")
    conn.execute("insert into public.super_admins (user_id) values (%s)", (gokul,))
    with as_user(conn, gokul):
        assert conn.execute("select public.dashboard_is_super_admin()").fetchone() == (True,)
        overview = conn.execute("select public.dashboard_admin_overview()").fetchone()[0]
    assert overview["projects"] >= 2
    assert overview["runs_total"] >= 2
    assert {"queue_depth", "dead_letters", "usage_30d", "top_projects"} <= overview.keys()
    assert overview["users"] >= 3 and overview["users_7d"] >= 3  # alice, bob, gokul
    assert len(overview["daily"]) == 30 and sum(d["runs"] for d in overview["daily"]) >= 2
    assert {"retrack-drain-runs", "retrack-retention"} <= {job["job"] for job in overview["cron"]}


# Admin CLI ------------------------------------------------------------------------------


def test_admin_adds_an_existing_user_to_a_projects_organization(conn, tenants):
    from retrack_server.admin import add_member as admin_add_member

    a, b = tenants  # two projects of one organization
    user = make_user(conn, "carol@example.com")
    admin_add_member(conn, "carol@example.com", a.project_id, "admin")
    with as_user(conn, user):
        visible = {row[0] for row in conn.execute("select id from public.projects")}
    assert visible == {a.project_id, b.project_id}
    with pytest.raises(ValueError):
        admin_add_member(conn, "nobody@example.com", a.project_id, "admin")


def test_admin_grants_and_removes_super_admin(conn):
    from retrack_server.admin import set_super_admin

    user = make_user(conn, "gokul@example.com")
    set_super_admin(conn, "gokul@example.com", True)
    with as_user(conn, user):
        assert conn.execute("select access.is_super_admin()").fetchone() == (True,)
    set_super_admin(conn, "gokul@example.com", False)
    with as_user(conn, user):
        assert conn.execute("select access.is_super_admin()").fetchone() == (False,)


# Overview (Phase 12b) -------------------------------------------------------------------


def add_run(conn, tenant, *, outcome, holdout=None, tokens=100, days_ago=0):
    """A run; holdout None means no recall was made, True/False adds a recall for it."""
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (project_id, id, agent_id, task_text, model_id, outcome,"
        " tokens_in, holdout, created_at)"
        " values (%s, %s, %s, 'task', 'm', %s, %s, %s, now() - make_interval(days => %s))",
        (tenant.project_id, run_id, tenant.agent_id, outcome, tokens, bool(holdout), days_ago),
    )
    if holdout is not None:
        mode = "holdout" if holdout else "hybrid"
        conn.execute(
            "insert into public.recalls (project_id, agent_id, run_id, holdout, mode)"
            " values (%s, %s, %s, %s, %s)",
            (tenant.project_id, tenant.agent_id, run_id, holdout, mode),
        )


def test_overview_compares_memory_with_holdout(conn, two_orgs):
    a, _, alice, _ = two_orgs
    for outcome in ["success", "success", "success", "failure"]:
        add_run(conn, a, outcome=outcome, holdout=False, tokens=80)
    for outcome in ["success", "failure"]:
        add_run(conn, a, outcome=outcome, holdout=True, tokens=120)
    add_run(conn, a, outcome="unknown", holdout=False, tokens=80)  # no outcome: not in rates
    add_run(conn, a, outcome="failure", holdout=None)  # no recall: outside the comparison
    add_run(conn, a, outcome="success", days_ago=10)  # previous week
    with as_user(conn, alice):
        overview = conn.execute(
            "select public.dashboard_project_overview(%s, 30)", (a.project_id,)
        ).fetchone()[0]
    roi = overview["roi"]
    assert (roi["treated"]["known"], roi["treated"]["successes"]) == (4, 3)
    assert (roi["holdout"]["known"], roi["holdout"]["successes"]) == (2, 1)
    assert roi["treated"]["avg_tokens"] == pytest.approx(80)
    assert roi["holdout"]["avg_tokens"] == pytest.approx(120)
    kpis = overview["kpis"]
    # The fixture's own run (unknown outcome) is also in this week.
    assert kpis["runs_7d"] == 9 and kpis["runs_prev_7d"] == 1
    assert kpis["success_rate_7d"] == pytest.approx(4 / 7)
    assert len(overview["daily"]) == 30
    assert sum(d["runs"] for d in overview["daily"]) == 10


def test_overview_of_another_orgs_project_is_empty(conn, two_orgs):
    _, b, alice, _ = two_orgs
    with as_user(conn, alice):
        assert conn.execute(
            "select public.dashboard_project_overview(%s, 30)", (b.project_id,)
        ).fetchone() == (None,)


# Memory actions (Phase 12c) -------------------------------------------------------------


def active_playbook(conn, tenant):
    return conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, content_hash,"
        " trusted_support) values (%s, %s, 'active', 'Refund damaged items', 'h', 3) returning id",
        (tenant.project_id, tenant.agent_id),
    ).fetchone()[0]


def test_owner_quarantines_a_playbook_and_it_goes_to_review(conn, two_orgs):
    a, _, alice, _ = two_orgs
    playbook_id = active_playbook(conn, a)
    with as_user(conn, alice, email="alice@example.com"):
        conn.execute(
            "select public.dashboard_set_playbook_status(%s, 'quarantined', 'looks wrong')",
            (playbook_id,),
        )
    assert conn.execute(
        "select status from public.playbooks where id = %s", (playbook_id,)
    ).fetchone() == ("quarantined",)
    assert conn.execute(
        "select status, reason from public.review_queue where object_id = %s", (playbook_id,)
    ).fetchone() == ("open", "quarantined by alice@example.com: looks wrong")


def test_retiring_closes_open_reviews(conn, two_orgs):
    a, _, alice, _ = two_orgs
    playbook_id, item_id = quarantined_playbook(conn, a)
    with as_user(conn, alice):
        conn.execute(
            "select public.dashboard_set_playbook_status(%s, 'retired', '')", (playbook_id,)
        )
    assert conn.execute(
        "select status from public.review_queue where id = %s", (item_id,)
    ).fetchone() == ("rejected",)


@pytest.mark.parametrize("status", ["active", "candidate", "bogus"])
def test_status_actions_cannot_activate_or_invent_states(conn, two_orgs, status):
    a, _, alice, _ = two_orgs
    playbook_id = active_playbook(conn, a)
    with pytest.raises(psycopg.errors.InvalidParameterValue), as_user(conn, alice):
        conn.execute(
            "select public.dashboard_set_playbook_status(%s, %s, '')", (playbook_id, status)
        )


def test_outsiders_and_plain_members_cannot_change_playbooks(conn, two_orgs):
    a, _, _, bob = two_orgs
    playbook_id = active_playbook(conn, a)
    viewer = make_user(conn)
    add_member(conn, org_of(conn, a.project_id), viewer, "member")
    for who in (bob, viewer):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), as_user(conn, who):
            conn.execute(
                "select public.dashboard_set_playbook_status(%s, 'retired', '')", (playbook_id,)
            )
