"""Recall: gated hybrid search, holdout, warnings, learning loop, latency (Block E)."""

import statistics
import uuid

import pytest
from psycopg.types.json import Jsonb

from retrack_server.db import enqueue_run, project_scope
from retrack_server.embeddings import FakeEmbedder, to_vector_literal
from retrack_server.recall import CANDIDATES_SQL, apply_learning, recall
from retrack_server.schemas import RecallIn

EMBEDDER = FakeEmbedder()


def add_playbook(conn, tenant, task, title="Refund a damaged order", status="active", **extra):
    vector = to_vector_literal(EMBEDDER.embed([task])[0])
    fields = {
        "validated_models": ["m"],
        "tool_versions": Jsonb({"refunds_api": "v3"}),
        "support_count": 3,
        "trusted_support": 3,
        "confidence": 1.0,
    } | extra
    columns = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    return conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, task_pattern,"
        " preconditions, steps, pitfalls, embedding, embedding_model, content_hash,"
        " last_success_at, approved_at, " + columns + ")"
        " values (%s, %s, %s, %s, %s, 'order exists', '[]', 'watch rate limits',"
        " %s::extensions.halfvec, %s, md5(random()::text), now(), now(), " + placeholders + ")"
        " returning id",
        (
            tenant.project_id,
            tenant.agent_id,
            status,
            title,
            task,
            vector,
            EMBEDDER.model,
            *fields.values(),
        ),
    ).fetchone()[0]


def ask(conn, tenant, task="Refund order 42, it arrived damaged", embedder=EMBEDDER, **kw):
    request = RecallIn(agent="support-agent", task=task, model_id="m", **kw)
    return recall(conn, tenant.project_id, request, embedder)


def no_holdout(conn, *tenants):
    for t in tenants:
        conn.execute("update public.projects set holdout_rate = 0 where id = %s", (t.project_id,))


# Gating -----------------------------------------------------------------------------


def test_similar_active_playbook_is_returned_with_its_score(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    pb = add_playbook(conn, a, "Refund order 7, it arrived damaged")
    result = ask(conn, a)
    assert [p["id"] for p in result.playbooks] == [str(pb)]
    assert result.playbooks[0]["score"] >= 0.72
    assert result.mode == "hybrid" and result.holdout is False


def test_candidates_are_never_returned(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    add_playbook(conn, a, "Refund order 7, it arrived damaged", status="candidate")
    assert ask(conn, a).playbooks == []


def test_unrelated_playbooks_stay_below_the_gate(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    add_playbook(conn, a, "Book meeting room B for the Friday review", title="Book a room")
    assert ask(conn, a).playbooks == []


def test_breaking_tool_version_blocks_a_playbook(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    add_playbook(conn, a, "Refund order 7, it arrived damaged")
    assert ask(conn, a, tool_versions={"refunds_api": "v4"}).playbooks == []
    assert len(ask(conn, a, tool_versions={"refunds_api": "v3.1"}).playbooks) == 1


def test_max_playbooks_and_order(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    stale = add_playbook(conn, a, "Refund order 1, it arrived damaged", confidence=0.8)
    best = add_playbook(conn, a, "Refund order 2, it arrived damaged", confidence=1.0)
    result = ask(conn, a, max_playbooks=1)
    assert [p["id"] for p in result.playbooks] == [str(best)]
    assert str(stale) not in [p["id"] for p in result.playbooks]


def test_other_projects_memory_is_invisible(conn, tenants):
    a, b = tenants
    no_holdout(conn, a, b)
    add_playbook(conn, b, "Refund order 7, it arrived damaged")
    assert ask(conn, a).playbooks == []


def test_keyword_fallback_when_embeddings_are_off(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    add_playbook(conn, a, "Refund order 7, it arrived damaged")
    result = ask(conn, a, embedder=None)
    assert result.mode == "keyword"
    assert all(p["score"] >= 0.72 for p in result.playbooks)


def test_unknown_agent_gets_no_memory(conn, tenants):
    a, _ = tenants
    request = RecallIn(agent="never-seen", task="anything", model_id="m")
    result = recall(conn, a.project_id, request, EMBEDDER)
    assert (result.playbooks, result.mode) == ([], "no_agent")


# Holdout and warnings ---------------------------------------------------------------


def test_holdout_runs_get_no_memory_and_are_logged(conn, tenants):
    a, _ = tenants
    conn.execute("update public.projects set holdout_rate = 1 where id = %s", (a.project_id,))
    add_playbook(conn, a, "Refund order 7, it arrived damaged")
    run_id = uuid.uuid4()
    result = ask(conn, a, run_id=run_id)
    assert (result.playbooks, result.warnings, result.holdout) == ([], [], True)
    logged = conn.execute(
        "select holdout, mode from public.recalls where run_id = %s", (run_id,)
    ).fetchone()
    assert logged == (True, "holdout")


def test_warnings_for_repeated_failures_of_the_agents_tools(conn, tenants):
    a, _ = tenants
    no_holdout(conn, a)
    for tool, occurrences in (("refunds_api", 7), ("refunds_api", 1), ("email_api", 9)):
        conn.execute(
            "insert into public.failure_signatures (project_id, agent_id, tool_name,"
            " error_class, input_shape, fingerprint, occurrences)"
            " values (%s, %s, %s, 'TimeoutError', 'order_id:str', md5(random()::text), %s)",
            (a.project_id, a.agent_id, tool, occurrences),
        )
    result = ask(conn, a, tool_versions={"refunds_api": "v3"})
    assert [(w["tool"], w["occurrences"]) for w in result.warnings] == [("refunds_api", 7)]
    assert "TimeoutError" in result.warnings[0]["message"]


# Linking and the learning loop ------------------------------------------------------


def test_ingested_run_is_linked_to_its_recall(conn, tenants):
    from retrack_server.ingest import store_run
    from retrack_server.schemas import RunIn

    a, _ = tenants
    no_holdout(conn, a)
    pb = add_playbook(conn, a, "Refund order 7, it arrived damaged")
    run_id = uuid.uuid4()
    ask(conn, a, run_id=run_id)
    store_run(
        conn,
        a.project_id,
        RunIn(id=run_id, agent="support-agent", task="Refund order 42", model_id="m"),
    )
    row = conn.execute(
        "select recalled_playbook_ids, holdout from public.runs where id = %s", (run_id,)
    ).fetchone()
    assert row == ([pb], False)


def recalled_run(conn, tenant, playbook_id, outcome):
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id, outcome,"
        " recalled_playbook_ids) values (%s, %s, %s, 't', 'm', %s, %s)",
        (run_id, tenant.project_id, tenant.agent_id, outcome, [playbook_id]),
    )
    return run_id


def stats(conn, playbook_id):
    return conn.execute(
        "select uses, successes, round(success_rate::numeric, 3)::float, status"
        " from public.playbooks where id = %s",
        (playbook_id,),
    ).fetchone()


def test_learning_loop_counts_each_run_once_and_follows_corrections(conn, tenants):
    a, _ = tenants
    pb = add_playbook(conn, a, "Refund order 7", support_count=2)
    run_id = recalled_run(conn, a, pb, "success")
    apply_learning(conn, a.project_id, run_id)
    apply_learning(conn, a.project_id, run_id)
    assert stats(conn, pb)[:2] == (1, 1)
    conn.execute("update public.runs set outcome = 'failure' where id = %s", (run_id,))
    apply_learning(conn, a.project_id, run_id)
    assert stats(conn, pb)[:3] == (1, 0, pytest.approx(2 / 3, abs=1e-3))


def test_failing_playbooks_are_retired_after_ten_uses(conn, tenants):
    a, _ = tenants
    pb = add_playbook(conn, a, "Refund order 7", support_count=1)
    for i in range(10):
        apply_learning(
            conn, a.project_id, recalled_run(conn, a, pb, "failure" if i < 6 else "success")
        )
    assert stats(conn, pb)[0] == 10
    assert stats(conn, pb)[3] == "retired"


def test_drain_applies_the_learning_loop(conn, tenants):
    from retrack_server.worker import drain

    a, _ = tenants
    pb = add_playbook(conn, a, "Refund order 7", support_count=1)
    run_id = recalled_run(conn, a, pb, "unknown")
    conn.execute(
        "insert into public.steps (project_id, run_id, idx, type) values (%s, %s, 0, 'llm')",
        (a.project_id, run_id),
    )
    conn.execute(
        "insert into public.outcome_signals (project_id, run_id, source, outcome, confidence)"
        " values (%s, %s, 'test', 'success', 1)",
        (a.project_id, run_id),
    )
    with project_scope(conn, a.project_id):
        enqueue_run(conn, run_id)
    drain(conn, time_budget_seconds=20)
    assert stats(conn, pb)[:2] == (1, 1)


# Latency target ---------------------------------------------------------------------


@pytest.mark.slow
def test_candidate_search_meets_latency_on_ten_thousand_playbooks(conn, tenants):
    a, _ = tenants
    conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, task_pattern,"
        " embedding, embedding_model, content_hash, approved_at, last_success_at)"
        " select %s, %s, 'active', 'Playbook ' || g, 'task pattern number ' || g,"
        "  (select array_agg(random() - 0.5) from generate_series(1, 1536) where g > 0)"
        "    ::extensions.vector::extensions.halfvec,"
        "  %s, md5(g::text), now(), now()"
        " from generate_series(1, 10000) g",
        (a.project_id, a.agent_id, EMBEDDER.model),
    )
    conn.execute("analyze public.playbooks")  # autovacuum does this in production
    vector = to_vector_literal(EMBEDDER.embed(["Refund order 42, damaged"])[0])
    params = {
        "project_id": a.project_id,
        "agent_id": a.agent_id,
        "model": EMBEDDER.model,
        "vector": vector,
        "query": "refund | order | damaged",
    }
    times = []
    with project_scope(conn, a.project_id):
        conn.execute("set local hnsw.iterative_scan = relaxed_order")
        for _ in range(7):
            plan = conn.execute("explain (analyze, format json) " + CANDIDATES_SQL, params)
            times.append(plan.fetchone()[0][0]["Execution Time"])
    assert statistics.median(times) < 120, times
