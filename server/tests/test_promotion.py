"""The rule from docs/firewall.md: tainted runs never directly become active memory."""

from retrack_server.firewall import (
    REQUIRED_TRUSTED_SUCCESSES,
    initial_status,
    needs_review,
    promotion_allowed,
)


def test_new_memory_always_starts_as_candidate():
    assert initial_status(["trusted"]) == "candidate"
    assert initial_status(["untrusted"]) == "candidate"


def test_tainted_sources_need_review():
    assert needs_review(["trusted", "untrusted"])
    assert needs_review(["quarantined"])
    assert not needs_review(["trusted", "trusted"])


def test_trusted_sources_promote_after_enough_trusted_successes():
    n = REQUIRED_TRUSTED_SUCCESSES
    assert not promotion_allowed(["trusted"], human_approved=False, trusted_successes=n - 1)
    assert promotion_allowed(["trusted"], human_approved=False, trusted_successes=n)


def test_tainted_sources_need_a_human_until_automatic_checks_pass():
    n = REQUIRED_TRUSTED_SUCCESSES
    for taints in (["untrusted"], ["trusted", "untrusted"]):
        assert not promotion_allowed(taints, human_approved=False, trusted_successes=1000)
        assert promotion_allowed(
            taints, human_approved=False, trusted_successes=n, passed_automatic_checks=True
        )


def test_quarantined_sources_only_promote_with_a_human():
    assert not promotion_allowed(
        ["quarantined"], human_approved=False, trusted_successes=1000, passed_automatic_checks=True
    )
    assert promotion_allowed(["quarantined"], human_approved=True, trusted_successes=0)


def test_human_approval_promotes():
    assert promotion_allowed(["untrusted"], human_approved=True, trusted_successes=0)


def test_no_sources_never_promote():
    assert not promotion_allowed([], human_approved=False, trusted_successes=1000)
