"""Outcome resolution: hard signals beat the judge; the judge runs only when needed."""

import uuid

import pytest

from retrack_server.db import project_scope
from retrack_server.llm import FakeLLM
from retrack_server.scoring import add_signal, score_run

VERDICT = {"outcome": "failure", "confidence": 0.95, "reason": "refund call timed out"}


def outcome(conn, run_id):
    return conn.execute(
        "select outcome, outcome_source, confidence from public.runs where id = %s", (run_id,)
    ).fetchone()


def signals(conn, run_id):
    return conn.execute(
        "select source, outcome from public.outcome_signals where run_id = %s order by created_at",
        (run_id,),
    ).fetchall()


def signal(conn, tenant, source, result):
    with project_scope(conn, tenant.project_id):
        add_signal(conn, tenant.project_id, tenant.run_id, source, result)


def test_no_signal_and_no_llm_stays_unknown(conn, tenants):
    a, _ = tenants
    score_run(conn, a.project_id, a.run_id, llm=None)
    assert outcome(conn, a.run_id) == ("unknown", None, None)


def test_judge_runs_when_no_hard_signal(conn, tenants):
    a, _ = tenants
    llm = FakeLLM([VERDICT])
    score_run(conn, a.project_id, a.run_id, llm=llm)
    assert len(llm.calls) == 1
    result, source, confidence = outcome(conn, a.run_id)
    assert (result, source) == ("failure", "judge")
    assert confidence <= 0.5  # runs are untrusted by default, so the cap is lower


def test_judge_is_skipped_when_a_hard_signal_exists(conn, tenants):
    a, _ = tenants
    signal(conn, a, "test", "success")
    llm = FakeLLM([])
    score_run(conn, a.project_id, a.run_id, llm=llm)
    assert llm.calls == []
    assert outcome(conn, a.run_id)[:2] == ("success", "test")


def test_judge_is_not_called_twice(conn, tenants):
    a, _ = tenants
    llm = FakeLLM([VERDICT])
    score_run(conn, a.project_id, a.run_id, llm=llm)
    score_run(conn, a.project_id, a.run_id, llm=llm)
    assert len(llm.calls) == 1


def test_unknown_verdict_records_nothing(conn, tenants):
    a, _ = tenants
    llm = FakeLLM([{"outcome": "unknown", "confidence": 0.1, "reason": "unclear"}])
    score_run(conn, a.project_id, a.run_id, llm=llm)
    assert signals(conn, a.run_id) == []
    assert outcome(conn, a.run_id)[0] == "unknown"


def test_hard_signals_outrank_the_judge_and_each_other(conn, tenants):
    a, _ = tenants
    score_run(conn, a.project_id, a.run_id, llm=FakeLLM([VERDICT]))
    signal(conn, a, "feedback", "success")
    assert outcome(conn, a.run_id) == ("success", "feedback", 0.8)
    signal(conn, a, "event", "failure")
    assert outcome(conn, a.run_id)[:2] == ("failure", "event")
    signal(conn, a, "test", "success")
    assert outcome(conn, a.run_id) == ("success", "test", 1.0)
    signal(conn, a, "feedback", "failure")
    assert outcome(conn, a.run_id)[:2] == ("success", "test")


def test_latest_signal_wins_within_the_same_source(conn, tenants):
    a, _ = tenants
    signal(conn, a, "feedback", "success")
    signal(conn, a, "feedback", "failure")
    assert outcome(conn, a.run_id)[:2] == ("failure", "feedback")


def test_judge_tokens_are_counted_for_the_project(conn, tenants):
    a, _ = tenants
    score_run(conn, a.project_id, a.run_id, llm=FakeLLM([VERDICT]))
    tokens = conn.execute(
        "select llm_input_tokens, llm_output_tokens from public.usage_daily"
        " where project_id = %s and day = (now() at time zone 'utc')::date",
        (a.project_id,),
    ).fetchone()
    assert tokens == (100, 20)


def test_unknown_run_is_an_error(conn, tenants):
    a, _ = tenants
    with pytest.raises(LookupError):
        score_run(conn, a.project_id, uuid.uuid4(), llm=FakeLLM([VERDICT]))
