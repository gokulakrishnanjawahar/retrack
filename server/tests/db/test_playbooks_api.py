"""Playbook and metrics endpoints (Phase 13, docs/api.md). API keys can read memory and take
it out of service (quarantine, retire); approving and rolling back stay in the dashboard."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from retrack_server.api_keys import create_api_key
from retrack_server.app import app, get_conn, get_settings
from retrack_server.config import Settings

PEPPER = "test-pepper"


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="unused", key_pepper=PEPPER
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def key(conn, tenants):
    a, _ = tenants
    return create_api_key(conn, a.project_id, "sdk", PEPPER)


@pytest.fixture
def auth(key):
    return {"Authorization": f"Bearer {key.secret}"}


def playbook(conn, tenant, *, title="Refund damaged items", status="active"):
    playbook_id = conn.execute(
        "insert into public.playbooks (project_id, agent_id, status, title, steps, content_hash,"
        " trusted_support) values (%s, %s, %s, %s, %s, 'h', 3) returning id",
        (tenant.project_id, tenant.agent_id, status, title, json.dumps([{"action": "Refund"}])),
    ).fetchone()[0]
    for version in (1, 2):
        conn.execute(
            "insert into public.playbook_versions (project_id, playbook_id, version, snapshot,"
            " change_reason) values (%s, %s, %s, %s, %s)",
            (tenant.project_id, playbook_id, version, json.dumps({"title": title}), f"v{version}"),
        )
    return playbook_id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/playbooks"),
        ("get", f"/v1/playbooks/{uuid.uuid4()}/versions"),
        ("patch", f"/v1/playbooks/{uuid.uuid4()}"),
        ("get", "/v1/metrics"),
    ],
)
def test_endpoints_need_an_api_key(client, method, path):
    assert client.request(method, path, json={"action": "retire"}).status_code == 401


# Reading --------------------------------------------------------------------------------


def test_lists_active_playbooks_by_default_and_filters(client, conn, auth, tenants):
    a, b = tenants
    active = playbook(conn, a)
    quarantined = playbook(conn, a, title="Odd", status="quarantined")
    playbook(conn, b, title="Other project")
    body = client.get("/v1/playbooks", headers=auth).json()
    assert [p["id"] for p in body["playbooks"]] == [str(active)]
    first = body["playbooks"][0]
    assert first["agent"] == "support-agent" and first["steps"] == [{"action": "Refund"}]
    assert {"version", "success_rate", "validated_models", "origin_playbook_id"} <= first.keys()
    only_q = client.get("/v1/playbooks?status=quarantined", headers=auth).json()["playbooks"]
    assert [p["id"] for p in only_q] == [str(quarantined)]
    everything = client.get("/v1/playbooks?status=all", headers=auth).json()["playbooks"]
    assert len(everything) == 2
    assert client.get("/v1/playbooks?agent=nobody", headers=auth).json() == {"playbooks": []}
    assert client.get("/v1/playbooks?status=bogus", headers=auth).status_code == 422


def test_versions_newest_first_and_never_another_projects(client, conn, auth, tenants):
    a, b = tenants
    mine = playbook(conn, a)
    theirs = playbook(conn, b)
    body = client.get(f"/v1/playbooks/{mine}/versions", headers=auth).json()
    assert [v["version"] for v in body["versions"]] == [2, 1]
    assert body["versions"][0]["change_reason"] == "v2"
    response = client.get(f"/v1/playbooks/{theirs}/versions", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playbook_not_found"


# Changing -------------------------------------------------------------------------------


def test_api_key_quarantines_with_the_key_recorded(client, conn, auth, key, tenants):
    a, _ = tenants
    playbook_id = playbook(conn, a)
    response = client.patch(
        f"/v1/playbooks/{playbook_id}", json={"action": "quarantine", "note": "bad"}, headers=auth
    )
    assert response.status_code == 200
    assert response.json() == {"id": str(playbook_id), "status": "quarantined"}
    assert conn.execute(
        "select reason from public.review_queue where object_id = %s", (playbook_id,)
    ).fetchone() == (f"quarantined by api key {key.prefix}: bad",)


def test_api_key_retires(client, conn, auth, tenants):
    a, _ = tenants
    playbook_id = playbook(conn, a)
    response = client.patch(f"/v1/playbooks/{playbook_id}", json={"action": "retire"}, headers=auth)
    assert response.json()["status"] == "retired"
    assert conn.execute(
        "select status from public.playbooks where id = %s", (playbook_id,)
    ).fetchone() == ("retired",)


@pytest.mark.parametrize("body", [{"action": "approve"}, {"action": "rollback", "version": 1}])
def test_approve_and_rollback_are_dashboard_only(client, conn, auth, tenants, body):
    a, _ = tenants
    playbook_id = playbook(conn, a, status="quarantined")
    response = client.patch(f"/v1/playbooks/{playbook_id}", json=body, headers=auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert conn.execute(
        "select status, version from public.playbooks where id = %s", (playbook_id,)
    ).fetchone() == ("quarantined", 1)


def test_patch_rejects_bad_bodies_and_other_projects(client, conn, auth, tenants):
    a, b = tenants
    mine = playbook(conn, a)
    theirs = playbook(conn, b)
    bad = client.patch(f"/v1/playbooks/{mine}", json={"action": "delete"}, headers=auth)
    assert bad.status_code == 422
    response = client.patch(f"/v1/playbooks/{theirs}", json={"action": "retire"}, headers=auth)
    assert response.status_code == 404
    assert conn.execute(
        "select status from public.playbooks where id = %s", (theirs,)
    ).fetchone() == ("active",)


# Metrics --------------------------------------------------------------------------------


def run(conn, tenant, *, outcome, holdout=None, tokens=100, cost=0.01, playbooks=0):
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (project_id, id, agent_id, task_text, model_id, outcome,"
        " tokens_in, cost_usd, holdout) values (%s, %s, %s, 't', 'm', %s, %s, %s, %s)",
        (tenant.project_id, run_id, tenant.agent_id, outcome, tokens, cost, bool(holdout)),
    )
    if holdout is not None:
        conn.execute(
            "insert into public.recalls (project_id, agent_id, run_id, holdout, mode,"
            " playbook_ids, latency_ms) values (%s, %s, %s, %s, %s, %s, 20)",
            (
                tenant.project_id,
                tenant.agent_id,
                run_id,
                holdout,
                "holdout" if holdout else "hybrid",
                [uuid.uuid4()] * playbooks,
            ),
        )


def test_metrics_compare_memory_with_holdout(client, conn, auth, tenants):
    a, b = tenants
    for outcome in ["success", "success", "success", "failure"]:
        run(conn, a, outcome=outcome, holdout=False, tokens=80, cost=0.008, playbooks=1)
    for outcome in ["success", "failure"]:
        run(conn, a, outcome=outcome, holdout=True, tokens=100, cost=0.01)
    run(conn, a, outcome="success", holdout=False, tokens=80, cost=0.008)  # recall found nothing
    run(conn, b, outcome="failure", holdout=True)  # another project: never counted
    body = client.get("/v1/metrics?days=30", headers=auth).json()
    assert body["days"] == 30
    assert (body["memory"]["known"], body["memory"]["successes"]) == (5, 4)
    assert (body["holdout"]["known"], body["holdout"]["successes"]) == (2, 1)
    assert body["lift_points"] == pytest.approx(30.0)
    assert body["token_change"] == pytest.approx(-0.2)
    assert body["cost_change"] == pytest.approx(-0.2)
    assert body["enough_evidence"] is False
    assert body["recalls"]["total"] == 7 and body["recalls"]["holdout"] == 2
    assert body["recalls"]["hit_rate"] == pytest.approx(4 / 5)


@pytest.mark.parametrize("days", [3, 91, "x"])
def test_metrics_range_is_validated(client, auth, days):
    assert client.get(f"/v1/metrics?days={days}", headers=auth).status_code == 422
