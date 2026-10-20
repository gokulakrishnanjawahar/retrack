"""Known-fix recovery, unrecoverable failures and plan replay (Block J)."""

import uuid

import pytest
from psycopg.types.json import Jsonb

from retrack_server.distiller import distill_run
from retrack_server.embeddings import FakeEmbedder, to_vector_literal
from retrack_server.ingest import store_run
from retrack_server.llm import FakeLLM
from retrack_server.recall import apply_learning, recall
from retrack_server.schemas import RecallIn, RunIn

EMBEDDER = FakeEmbedder()
REFUND_ARGS = {"order_id": "42", "amount_paise": 129900}


def run_with_steps(conn, tenant, outcome, steps, task="Refund order 42", taint="trusted"):
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id, outcome,"
        " outcome_source, confidence, taint_level, processed_at)"
        " values (%s, %s, %s, %s, 'm', %s, 'test', 1, %s, now())",
        (run_id, tenant.project_id, tenant.agent_id, task, outcome, taint),
    )
    for idx, (tool, result, error) in enumerate(steps):
        conn.execute(
            "insert into public.steps (project_id, run_id, idx, type, tool_name, args_redacted,"
            " result_class, error_class) values (%s, %s, %s, 'tool', %s, %s, %s, %s)",
            (tenant.project_id, run_id, idx, tool, Jsonb(REFUND_ARGS), result, error),
        )
    return run_id


RECOVERED = [
    ("orders_api", "ok", None),
    ("refunds_api", "error", "ReportedError"),
    ("check_delivery", "ok", None),
    ("refunds_api", "ok", None),
]
FAILED = [("orders_api", "ok", None), ("refunds_api", "error", "ReportedError")]


def signature(conn, project_id):
    return conn.execute(
        "select occurrences, recoveries, recovery_steps, unrecoverable"
        " from public.failure_signatures where project_id = %s and tool_name = 'refunds_api'",
        (project_id,),
    ).fetchone()


def distill(conn, tenant, run_id, embedder=None):
    return distill_run(conn, tenant.project_id, run_id, llm=FakeLLM([]), embedder=embedder)


def test_successful_run_that_recovered_teaches_the_fix_even_without_embeddings(conn, tenants):
    a, _ = tenants
    distill(conn, a, run_with_steps(conn, a, "success", RECOVERED))
    occurrences, recoveries, steps, unrecoverable = signature(conn, a.project_id)
    assert (occurrences, recoveries, unrecoverable) == (0, 1, False)
    assert steps == [{"tool": "check_delivery"}, {"tool": "refunds_api", "retry": True}]


def test_recovery_is_learned_once_per_run(conn, tenants):
    a, _ = tenants
    run_id = run_with_steps(conn, a, "success", RECOVERED)
    distill(conn, a, run_id)
    distill(conn, a, run_id)
    assert signature(conn, a.project_id)[1] == 1


def test_repeated_failures_without_any_recovery_become_unrecoverable(conn, tenants):
    a, _ = tenants
    for _ in range(4):
        distill(conn, a, run_with_steps(conn, a, "failure", FAILED))
    assert signature(conn, a.project_id)[3] is False
    distill(conn, a, run_with_steps(conn, a, "failure", FAILED))
    assert signature(conn, a.project_id)[:2] == (5, 0)
    assert signature(conn, a.project_id)[3] is True
    distill(conn, a, run_with_steps(conn, a, "success", RECOVERED))
    assert signature(conn, a.project_id)[3] is False  # a fix exists after all


def test_admin_override_wins_over_the_automatic_rule(conn, tenants):
    from retrack_server.admin import set_unrecoverable

    a, _ = tenants
    distill(conn, a, run_with_steps(conn, a, "failure", FAILED))
    signature_id = conn.execute(
        "select id from public.failure_signatures where project_id = %s", (a.project_id,)
    ).fetchone()[0]
    set_unrecoverable(conn, signature_id, True)
    assert signature(conn, a.project_id)[3] is True
    distill(conn, a, run_with_steps(conn, a, "success", RECOVERED))
    assert signature(conn, a.project_id)[3] is True
    set_unrecoverable(conn, signature_id, None)  # back to automatic
    assert signature(conn, a.project_id)[3] is False


def test_recall_warnings_carry_the_fix_and_the_flag(conn, tenants):
    a, _ = tenants
    conn.execute("update public.projects set holdout_rate = 0 where id = %s", (a.project_id,))
    distill(conn, a, run_with_steps(conn, a, "success", RECOVERED))
    result = recall(
        conn,
        a.project_id,
        RecallIn(agent="support-agent", task="Refund order 7", tool_versions={"refunds_api": "v2"}),
        None,
    )
    [warning] = result.warnings
    assert warning["recovery"] == "call check_delivery, then retry refunds_api"
    assert warning["recovery_steps"][0] == {"tool": "check_delivery"}
    assert warning["unrecoverable"] is False
    assert warning["fingerprint"]


# Plan replay ----------------------------------------------------------------------------

TOOLS = {"orders_api": "v3", "refunds_api": "v2"}


def proven_playbook(conn, tenant, uses=20, successes=19, models=("m",), tools=TOOLS):
    vector = to_vector_literal(EMBEDDER.embed(["Refund order 1, damaged"])[0])
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, steps, embedding,"
        " embedding_model, content_hash, approved_at, uses, successes, support_count,"
        " validated_models, tool_versions, last_success_at)"
        " values (%s, %s, 'candidate', 'Refund', %s, %s::extensions.halfvec, %s, 'h', now(),"
        " %s, %s, 3, %s, %s, now()) returning id",
        (
            tenant.project_id,
            tenant.agent_id,
            Jsonb(
                [
                    {"action": "Look up", "tool": "orders_api"},
                    {"action": "Refund", "tool": "refunds_api"},
                ]
            ),
            vector,
            EMBEDDER.model,
            uses,
            successes,
            list(models),
            Jsonb(tools),
        ),
    ).fetchone()[0]
    conn.execute("update public.playbooks set status = 'active' where id = %s", (playbook_id,))
    conn.execute("update public.projects set holdout_rate = 0 where id = %s", (tenant.project_id,))
    return playbook_id


def ask(conn, tenant, model="m", tools=TOOLS, embedder=EMBEDDER):
    return recall(
        conn,
        tenant.project_id,
        RecallIn(
            agent="support-agent",
            task="Refund order 9, damaged",
            model_id=model,
            tool_versions=tools,
        ),
        embedder,
    )


def test_well_proven_exact_match_is_replay_eligible(conn, tenants):
    a, _ = tenants
    playbook_id = proven_playbook(conn, a)
    result = ask(conn, a)
    assert result.replay_eligible is True
    assert result.replay_plan["playbook_id"] == str(playbook_id)
    assert [s["tool"] for s in result.replay_plan["steps"]] == ["orders_api", "refunds_api"]


@pytest.mark.parametrize(
    ("setup", "request_overrides"),
    [
        ({"uses": 19, "successes": 19}, {}),  # fewer than 20 uses
        ({"uses": 20, "successes": 17}, {}),  # below 90% success
        ({}, {"model": "other"}),  # different model
        ({}, {"tools": {"orders_api": "v3", "refunds_api": "v2.1"}}),  # not the exact version
        ({}, {"embedder": None}),  # keyword mode: similarity unknown
    ],
)
def test_replay_needs_every_condition(conn, tenants, setup, request_overrides):
    a, _ = tenants
    proven_playbook(conn, a, **setup)
    assert ask(conn, a, **request_overrides).replay_eligible is False


def test_failed_replay_demotes_the_playbook_and_asks_for_review(conn, tenants):
    a, _ = tenants
    playbook_id = proven_playbook(conn, a)
    run_id = uuid.uuid4()
    store_run(
        conn,
        a.project_id,
        RunIn(id=run_id, agent="support-agent", task="Refund", model_id="m", replay_of=playbook_id),
    )
    conn.execute("update public.runs set outcome = 'failure' where id = %s", (run_id,))
    apply_learning(conn, a.project_id, run_id)
    status, reviews = conn.execute(
        "select p.status, (select count(*) from public.review_queue r where r.object_id = p.id)"
        " from public.playbooks p where p.id = %s",
        (playbook_id,),
    ).fetchone()
    assert (status, reviews) == ("candidate", 1)


def test_successful_replay_keeps_the_playbook_active(conn, tenants):
    a, _ = tenants
    playbook_id = proven_playbook(conn, a)
    run_id = uuid.uuid4()
    store_run(
        conn,
        a.project_id,
        RunIn(id=run_id, agent="support-agent", task="Refund", model_id="m", replay_of=playbook_id),
    )
    conn.execute("update public.runs set outcome = 'success' where id = %s", (run_id,))
    apply_learning(conn, a.project_id, run_id)
    assert (
        conn.execute(
            "select status from public.playbooks where id = %s", (playbook_id,)
        ).fetchone()[0]
        == "active"
    )
