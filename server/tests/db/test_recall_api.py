"""POST /v1/recall over HTTP."""

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
def auth(conn, tenants):
    a, _ = tenants
    conn.execute("update public.projects set holdout_rate = 0 where id = %s", (a.project_id,))
    return {"Authorization": f"Bearer {create_api_key(conn, a.project_id, 'sdk', PEPPER).secret}"}


def test_requires_api_key(client):
    assert client.post("/v1/recall", json={"agent": "a", "task": "t"}).status_code == 401


def test_recall_response_shape_and_usage(client, conn, auth, tenants):
    a, _ = tenants
    response = client.post(
        "/v1/recall", json={"agent": "support-agent", "task": "Refund order 42"}, headers=auth
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"recall_id", "playbooks", "warnings", "holdout", "replay_eligible", "mode"}
    assert body["replay_eligible"] is False
    served = conn.execute(
        "select recalls_served from public.usage_daily where project_id = %s", (a.project_id,)
    ).fetchone()[0]
    assert served == 1


@pytest.mark.parametrize(
    "body", [{"task": "t"}, {"agent": "a"}, {"agent": "a", "task": "t", "max_playbooks": 50}]
)
def test_invalid_requests_are_422(client, auth, body):
    assert client.post("/v1/recall", json=body, headers=auth).status_code == 422
