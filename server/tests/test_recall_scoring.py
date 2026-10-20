"""Gate-score building blocks (docs/recall-gating.md, defaults approved 2026-10-20)."""

import datetime as dt
import uuid

import pytest

from retrack_server.recall import (
    freshness,
    gate_score,
    in_holdout,
    major_version,
    prior_success_rate,
    version_match,
)

NOW = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("version", "major"),
    [("v3", "3"), ("3.2.1", "3"), ("2026-09", "2026"), ("2026-10-01", "2026"), ("latest", None)],
)
def test_major_version(version, major):
    assert major_version(version) == major


def test_version_match_rules():
    tools = {"stripe": "2026-09", "orders_api": "v3"}
    assert version_match(["m1"], tools, "m1", {"stripe": "2026-11", "orders_api": "v3.4"}) == 1.0
    assert version_match(["m1"], tools, "m2", tools) == 0.6  # only tool versions match
    assert version_match(["m1"], tools, "m1", {"orders_api": "v4"}) == 0.0  # breaking change
    assert version_match(["m1"], tools, "m1", {"stripe": "2027-01"}) == 0.0
    assert version_match(["m1"], tools, None, tools) == 1.0  # model not given: no penalty
    assert version_match(["m1"], tools, "m1", {}) == 1.0  # tools not given: no penalty
    assert version_match(["m1"], tools, "m1", {"unrelated": "v9"}) == 1.0


def test_freshness_halves_every_thirty_days():
    assert freshness(NOW, NOW) == pytest.approx(1.0)
    assert freshness(NOW - dt.timedelta(days=30), NOW) == pytest.approx(0.5)
    assert freshness(NOW - dt.timedelta(days=60), NOW) == pytest.approx(0.25)
    assert freshness(None, NOW) == pytest.approx(1.0)


def test_new_playbooks_start_at_full_success_and_adjust_with_use():
    assert prior_success_rate(successes=0, uses=0, support=2) == 1.0
    assert prior_success_rate(successes=0, uses=2, support=2) == 0.5
    assert prior_success_rate(successes=8, uses=10, support=2) == pytest.approx(10 / 12)


def test_gate_score_multiplies_all_factors():
    assert gate_score(0.9, 0.95, 1.0, 1.0, 1.0) == pytest.approx(0.855)
    assert gate_score(0.9, 1.0, 1.0, 1.0, 0.6) < 0.72


def test_holdout_is_deterministic_and_close_to_the_rate():
    project = uuid.uuid4()
    run = uuid.uuid4()
    assert in_holdout(project, run, 0.1) == in_holdout(project, run, 0.1)
    share = sum(in_holdout(project, uuid.uuid4(), 0.1) for _ in range(5000)) / 5000
    assert 0.08 < share < 0.12
    assert not in_holdout(project, run, 0.0)
    assert in_holdout(project, run, 1.0)
