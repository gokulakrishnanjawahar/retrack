"""Fleet sharing (Phase 13, docs/features.md block K): a playbook from one agent can be proposed
to another, becomes active there only after an owner or admin approves it, and any playbook
can be rolled back to a prior version (with that version's embedding)."""

import json
import uuid

import psycopg
import pytest

SOURCE_STEPS = [
    {"action": "Look up the order", "tool": "orders_api"},
    {"action": "Refund to the original card", "tool": "billing_api"},
]
TARGET_STEPS = [{"action": "Ask a human to refund", "tool": "tickets_api"}]


def vector(value: float) -> str:
    return "[" + ",".join([str(value)] * 1536) + "]"


def add_playbook(conn, project_id, agent_id, *, title, steps, status="active", value=0.01):
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, steps, content_hash,"
        " trusted_support, support_count, confidence, embedding, embedding_model)"
        " values (%s, %s, %s, %s, %s, 'h', 3, 3, 0.9, %s::extensions.halfvec, 'test-model')"
        " returning id",
        (project_id, agent_id, status, title, json.dumps(steps), vector(value)),
    ).fetchone()[0]
    conn.execute(
        "insert into public.playbook_versions (project_id, playbook_id, version, snapshot,"
        " change_reason, embedding, embedding_model)"
        " values (%s, %s, 1, %s, 'created from run', %s::extensions.halfvec, 'test-model')",
        (project_id, playbook_id, json.dumps({"title": title, "steps": steps}), vector(value)),
    )
    return playbook_id


@pytest.fixture
def fleet(conn, tenants, users):
    """Project A with a source playbook on `support-agent` and a second agent
    `billing-agent` that has only ever used orders_api. Alice owns the organization."""
    a, b = tenants
    target_agent = conn.execute(
        "insert into public.agents (project_id, name) values (%s, 'billing-agent') returning id",
        (a.project_id,),
    ).fetchone()[0]
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
        " values (%s, %s, %s, 'check order', 'm')",
        (run_id, a.project_id, target_agent),
    )
    conn.execute(
        "insert into public.steps (project_id, run_id, idx, type, tool_name)"
        " values (%s, %s, 0, 'tool', 'orders_api')",
        (a.project_id, run_id),
    )
    source = add_playbook(
        conn, a.project_id, a.agent_id, title="Refund damaged items", steps=SOURCE_STEPS
    )
    conn.execute(
        "insert into public.provenance (project_id, object_type, object_id, source_run_ids,"
        " trust_level) values (%s, 'playbook', %s, %s, 'trusted')",
        (a.project_id, source, [a.run_id]),
    )
    alice = users.make("alice@example.com")
    users.add(a.project_id, alice)
    return {"a": a, "b": b, "target_agent": target_agent, "source": source, "alice": alice}


def propose(conn, source, target_agent, target_playbook=None):
    return conn.execute(
        "select public.dashboard_propose_playbook(%s, %s, %s, 'useful for billing')",
        (source, target_agent, target_playbook),
    ).fetchone()[0]


def resolve(conn, proposal_id, approve):
    conn.execute(
        "select public.dashboard_resolve_proposal(%s, %s, 'checked')", (proposal_id, approve)
    )


# Proposing ------------------------------------------------------------------------------


def test_owner_proposes_and_nothing_changes_until_approval(conn, fleet, users):
    with users.acting(fleet["alice"], "alice@example.com"):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"])
    status, snapshot, checks, proposed_by = conn.execute(
        "select status, snapshot, checks, proposed_by from public.playbook_proposals where id = %s",
        (proposal_id,),
    ).fetchone()
    assert (status, snapshot["title"], proposed_by) == (
        "open",
        "Refund damaged items",
        "alice@example.com",
    )
    assert any("billing_api" in c["detail"] for c in checks if c["check"] == "new_tools")
    assert (
        conn.execute(
            "select count(*) from public.playbooks where agent_id = %s", (fleet["target_agent"],)
        ).fetchone()[0]
        == 0
    )


def test_only_active_playbooks_can_be_shared_with_a_different_agent(conn, fleet, users):
    a = fleet["a"]
    candidate = add_playbook(
        conn, a.project_id, a.agent_id, title="Unproven", steps=[], status="candidate"
    )
    other = add_playbook(conn, a.project_id, a.agent_id, title="Same agent", steps=[])
    cases = [
        (candidate, fleet["target_agent"], None),  # not active
        (fleet["source"], a.agent_id, None),  # same agent
        (fleet["source"], fleet["target_agent"], other),  # target playbook of another agent
    ]
    for source, target_agent, target_playbook in cases:
        with pytest.raises(psycopg.errors.InvalidParameterValue), users.acting(fleet["alice"]):
            propose(conn, source, target_agent, target_playbook)


def test_one_open_proposal_per_playbook_and_agent(conn, fleet, users):
    with users.acting(fleet["alice"]):
        propose(conn, fleet["source"], fleet["target_agent"])
    with pytest.raises(psycopg.errors.InvalidParameterValue), users.acting(fleet["alice"]):
        propose(conn, fleet["source"], fleet["target_agent"])


def test_outsiders_and_members_cannot_propose_resolve_or_roll_back(conn, fleet, users):
    with users.acting(fleet["alice"]):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"])
    viewer = users.make()
    users.add(fleet["a"].project_id, viewer, "member")
    stranger = users.make()
    for who in (viewer, stranger):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), users.acting(who):
            propose(conn, fleet["source"], fleet["target_agent"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege), users.acting(who):
            resolve(conn, proposal_id, True)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), users.acting(who):
            conn.execute("select public.dashboard_rollback_playbook(%s, 1, '')", (fleet["source"],))


def test_members_can_read_proposals_of_their_projects_only(conn, fleet, users):
    with users.acting(fleet["alice"]):
        propose(conn, fleet["source"], fleet["target_agent"])
    viewer = users.make()
    users.add(fleet["a"].project_id, viewer, "member")
    with users.acting(viewer):
        assert conn.execute("select count(*) from public.playbook_proposals").fetchone()[0] == 1
    with users.acting(users.make()):
        assert conn.execute("select count(*) from public.playbook_proposals").fetchone()[0] == 0


# Approving ------------------------------------------------------------------------------


def test_approving_creates_an_active_copy_for_the_target_agent(conn, fleet, users):
    with users.acting(fleet["alice"], "alice@example.com"):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"])
        resolve(conn, proposal_id, True)
    status, result_id = conn.execute(
        "select status, result_playbook_id from public.playbook_proposals where id = %s",
        (proposal_id,),
    ).fetchone()
    assert status == "approved"
    row = conn.execute(
        "select agent_id, status, title, steps, approved_by, origin_playbook_id, version,"
        " validated_models, embedding::text = %s::extensions.halfvec::text"
        " from public.playbooks where id = %s",
        (vector(0.01), result_id),
    ).fetchone()
    assert row == (
        fleet["target_agent"],
        "active",
        "Refund damaged items",
        SOURCE_STEPS,
        "alice@example.com",
        fleet["source"],
        1,
        [],
        True,
    )
    assert conn.execute(
        "select trust_level, reviewer_id, source_run_ids from public.provenance"
        " where object_id = %s",
        (result_id,),
    ).fetchone() == ("trusted", "alice@example.com", [fleet["a"].run_id])
    assert conn.execute(
        "select embedding is not null from public.playbook_versions"
        " where playbook_id = %s and version = 1",
        (result_id,),
    ).fetchone() == (True,)
    assert conn.execute(
        "select agent_id, status from public.eval_cases where source_id = %s", (result_id,)
    ).fetchone() == (fleet["target_agent"], "active")
    assert conn.execute(
        "select version, status from public.playbooks where id = %s", (fleet["source"],)
    ).fetchone() == (1, "active")


def test_approving_an_update_makes_a_new_version_of_the_target_playbook(conn, fleet, users):
    a = fleet["a"]
    target = add_playbook(
        conn, a.project_id, fleet["target_agent"], title="Refunds", steps=TARGET_STEPS, value=0.02
    )
    with users.acting(fleet["alice"]):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"], target)
        resolve(conn, proposal_id, True)
    assert conn.execute(
        "select version, steps, origin_playbook_id from public.playbooks where id = %s", (target,)
    ).fetchone() == (2, SOURCE_STEPS, fleet["source"])
    reason = conn.execute(
        "select change_reason from public.playbook_versions where playbook_id = %s and version = 2",
        (target,),
    ).fetchone()[0]
    assert reason.startswith("shared from support-agent")
    version, assertions = conn.execute(
        "select source_version, expected_assertions from public.eval_cases where source_id = %s",
        (target,),
    ).fetchone()
    assert version == 2
    assert {"type": "tool_sequence", "tools": ["orders_api", "billing_api"]} in assertions


def test_update_is_refused_when_the_target_changed_after_the_proposal(conn, fleet, users):
    a = fleet["a"]
    target = add_playbook(
        conn, a.project_id, fleet["target_agent"], title="Refunds", steps=TARGET_STEPS
    )
    with users.acting(fleet["alice"]):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"], target)
    conn.execute("update public.playbooks set version = 5 where id = %s", (target,))
    with pytest.raises(psycopg.errors.InvalidParameterValue), users.acting(fleet["alice"]):
        resolve(conn, proposal_id, True)


def test_rejecting_changes_nothing_and_closes_the_proposal(conn, fleet, users):
    with users.acting(fleet["alice"]):
        proposal_id = propose(conn, fleet["source"], fleet["target_agent"])
        resolve(conn, proposal_id, False)
    assert (
        conn.execute(
            "select status, reviewer from public.playbook_proposals where id = %s", (proposal_id,)
        ).fetchone()[0]
        == "rejected"
    )
    assert (
        conn.execute(
            "select count(*) from public.playbooks where agent_id = %s", (fleet["target_agent"],)
        ).fetchone()[0]
        == 0
    )
    with pytest.raises(psycopg.errors.InvalidParameterValue), users.acting(fleet["alice"]):
        resolve(conn, proposal_id, True)


# Rollback -------------------------------------------------------------------------------


def test_rollback_restores_a_prior_version_with_its_embedding(conn, fleet, users):
    a = fleet["a"]
    target = add_playbook(
        conn, a.project_id, fleet["target_agent"], title="Refunds", steps=TARGET_STEPS, value=0.02
    )
    with users.acting(fleet["alice"], "alice@example.com"):
        resolve(conn, propose(conn, fleet["source"], fleet["target_agent"], target), True)
        new_version = conn.execute(
            "select public.dashboard_rollback_playbook(%s, 1, 'bad merge')", (target,)
        ).fetchone()[0]
    assert new_version == 3
    row = conn.execute(
        "select version, title, steps, embedding::text = %s::extensions.halfvec::text"
        " from public.playbooks where id = %s",
        (vector(0.02), target),
    ).fetchone()
    assert row == (3, "Refunds", TARGET_STEPS, True)
    assert (
        "rolled back to v1"
        in conn.execute(
            "select change_reason from public.playbook_versions"
            " where playbook_id = %s and version = 3",
            (target,),
        ).fetchone()[0]
    )


def test_rollback_refuses_the_current_or_a_missing_version(conn, fleet, users):
    with pytest.raises(psycopg.errors.InvalidParameterValue), users.acting(fleet["alice"]):
        conn.execute("select public.dashboard_rollback_playbook(%s, 1, '')", (fleet["source"],))
    with pytest.raises(psycopg.errors.NoDataFound), users.acting(fleet["alice"]):
        conn.execute("select public.dashboard_rollback_playbook(%s, 9, '')", (fleet["source"],))


# Shared status rule ---------------------------------------------------------------------


def test_pipeline_role_can_quarantine_through_the_shared_rule(conn, fleet):
    from retrack_server.db import pipeline_scope

    with pipeline_scope(conn, fleet["a"].project_id):
        status = conn.execute(
            "select private.set_playbook_status(%s, %s, 'quarantined', 'api key rtk_live_x',"
            " 'odd')",
            (fleet["a"].project_id, fleet["source"]),
        ).fetchone()[0]
    assert status == "quarantined"
    assert conn.execute(
        "select reason from public.review_queue where object_id = %s", (fleet["source"],)
    ).fetchone() == ("quarantined by api key rtk_live_x: odd",)
    with pipeline_scope(conn, fleet["b"].project_id):
        assert conn.execute(
            "select private.set_playbook_status(%s, %s, 'retired', 'x', '')",
            (fleet["b"].project_id, fleet["source"]),
        ).fetchone() == (None,)
