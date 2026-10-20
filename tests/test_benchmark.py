"""The support-desk benchmark runs end to end in fake mode ($0) and shows memory's effect."""

import os

import psycopg
import pytest

from benchmarks.support_desk.harness import run_benchmark, to_markdown

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (os.getenv("DATABASE_URL") and os.getenv("SERVER_DATABASE_URL")),
        reason="needs the dev database",
    ),
]


def test_fake_benchmark_end_to_end():
    report = run_benchmark(mode="fake", learn=8, evaluate=4, seed=11)

    assert report["memory_used_on_tasks"] == 4
    assert report["by_family"]["refund"]["cold"]["success_rate"] == 0.0
    assert report["memory"]["success_rate"] == 1.0
    assert report["memory"]["tool_calls"] < report["cold"]["tool_calls"]
    assert {p["status"] for p in report["playbooks"]} == {"active"}
    assert "Without memory" in to_markdown(report)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        active = conn.execute(
            "select active from cron.job where jobname = 'retrack-drain-runs'"
        ).fetchone()[0]
        leftover = conn.execute(
            "select count(*) from public.organizations where name like 'benchmark-%'"
        ).fetchone()[0]
    assert active is True  # live worker re-enabled
    assert leftover == 0  # throwaway project removed


def test_real_mode_refuses_without_approval():
    with pytest.raises(SystemExit):
        run_benchmark(mode="real")
