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


def test_set_trust_updates_project_settings(conn):
    from retrack_server.admin import set_trust

    created = create_project(conn, "Acme", "support", PEPPER)
    set_trust(conn, created.project_id, ["orders_api", "orders_api", " billing_api "], True)
    assert conn.execute(
        "select trusted_tools, task_trusted from public.projects where id = %s",
        (created.project_id,),
    ).fetchone() == (["billing_api", "orders_api"], True)


# Review queue (Phase 8) ----------------------------------------------------------------


def quarantined_playbook(conn, project_id):
    agent_id = conn.execute(
        "insert into public.agents (project_id, name) values (%s, 'a') returning id", (project_id,)
    ).fetchone()[0]
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, content_hash)"
        " values (%s, %s, 'quarantined', 'Suspicious', 'h') returning id",
        (project_id, agent_id),
    ).fetchone()[0]
    item_id = conn.execute(
        "insert into public.review_queue (project_id, object_type, object_id, reason)"
        " values (%s, 'playbook', %s, 'quarantined; injection_heuristic') returning id",
        (project_id, playbook_id),
    ).fetchone()[0]
    return playbook_id, item_id


def test_review_list_shows_open_items(conn):
    from retrack_server.admin import list_reviews

    created = create_project(conn, "Acme", "support", PEPPER)
    playbook_id, item_id = quarantined_playbook(conn, created.project_id)
    [item] = list_reviews(conn, created.project_id)
    assert (item["id"], item["object_id"], item["title"], item["status"]) == (
        item_id,
        playbook_id,
        "Suspicious",
        "quarantined",
    )


def test_approving_activates_the_playbook_with_reviewer_recorded(conn):
    from retrack_server.admin import list_reviews, resolve_review

    created = create_project(conn, "Acme", "support", PEPPER)
    playbook_id, item_id = quarantined_playbook(conn, created.project_id)
    resolve_review(conn, item_id, approve=True, reviewer="gokul", note="checked by hand")
    row = conn.execute(
        "select status, approved_by, approved_at is not null from public.playbooks where id = %s",
        (playbook_id,),
    ).fetchone()
    assert row == ("active", "gokul", True)
    assert list_reviews(conn, created.project_id) == []


def test_rejecting_retires_the_playbook(conn):
    from retrack_server.admin import resolve_review

    created = create_project(conn, "Acme", "support", PEPPER)
    playbook_id, item_id = quarantined_playbook(conn, created.project_id)
    resolve_review(conn, item_id, approve=False, reviewer="gokul", note="poisoned")
    assert (
        conn.execute(
            "select status from public.playbooks where id = %s", (playbook_id,)
        ).fetchone()[0]
        == "retired"
    )
    assert conn.execute(
        "select status, reviewer, resolution_note from public.review_queue where id = %s",
        (item_id,),
    ).fetchone() == ("rejected", "gokul", "poisoned")


def test_resolving_twice_is_refused(conn):
    import pytest

    from retrack_server.admin import resolve_review

    created = create_project(conn, "Acme", "support", PEPPER)
    _, item_id = quarantined_playbook(conn, created.project_id)
    resolve_review(conn, item_id, approve=False, reviewer="gokul", note="")
    with pytest.raises(ValueError):
        resolve_review(conn, item_id, approve=True, reviewer="gokul", note="")
