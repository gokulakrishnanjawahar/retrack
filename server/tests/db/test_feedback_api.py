"""POST /v1/feedback: late outcome signals from tests, business events or users."""

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
def auth(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "sdk", PEPPER)
    return {"Authorization": f"Bearer {key.secret}"}


def feedback(client, auth, **body):
    return client.post("/v1/feedback", json=body, headers=auth)


def test_requires_api_key(client, tenants):
    a, _ = tenants
    response = client.post(
        "/v1/feedback", json={"run_id": str(a.run_id), "outcome": "success", "source": "test"}
    )
    assert response.status_code == 401


def test_feedback_sets_the_outcome(client, conn, auth, tenants):
    a, _ = tenants
    response = feedback(client, auth, run_id=str(a.run_id), outcome="success", source="feedback")
    assert response.status_code == 202
    assert response.json() == {
        "run_id": str(a.run_id),
        "outcome": "success",
        "outcome_source": "feedback",
        "confidence": pytest.approx(0.8),
    }


def test_stronger_signal_wins(client, auth, tenants):
    a, _ = tenants
    feedback(client, auth, run_id=str(a.run_id), outcome="failure", source="feedback")
    response = feedback(client, auth, run_id=str(a.run_id), outcome="success", source="test")
    assert response.json()["outcome"] == "success"
    weaker = feedback(client, auth, run_id=str(a.run_id), outcome="failure", source="feedback")
    assert weaker.json()["outcome_source"] == "test"


def test_unknown_run_is_404(client, auth):
    response = feedback(client, auth, run_id=str(uuid.uuid4()), outcome="success", source="test")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_another_projects_run_is_404(client, auth, tenants):
    _, b = tenants
    response = feedback(client, auth, run_id=str(b.run_id), outcome="success", source="test")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"outcome": "success", "source": "judge"},
        {"outcome": "great", "source": "test"},
        {"outcome": "success"},
    ],
)
def test_invalid_feedback_is_422(client, auth, tenants, body):
    a, _ = tenants
    assert feedback(client, auth, run_id=str(a.run_id), **body).status_code == 422


def test_detail_is_redacted_before_storage(client, conn, auth, tenants):
    a, _ = tenants
    feedback(
        client,
        auth,
        run_id=str(a.run_id),
        outcome="failure",
        source="feedback",
        detail={"comment": "email me at x@y.co", "rating": 1},
    )
    detail = conn.execute(
        "select detail from public.outcome_signals where run_id = %s", (a.run_id,)
    ).fetchone()[0]
    assert detail == {"comment": "email me at <EMAIL>", "rating": 1}


def test_feedback_that_changes_the_outcome_requeues_the_run(client, conn, auth, tenants):
    a, _ = tenants

    def queued():
        return conn.execute(
            "select count(*) from pgmq.q_runs where message->>'run_id' = %s", (str(a.run_id),)
        ).fetchone()[0]

    before = queued()
    feedback(client, auth, run_id=str(a.run_id), outcome="success", source="test")
    assert queued() == before + 1
    feedback(client, auth, run_id=str(a.run_id), outcome="success", source="feedback")
    assert queued() == before + 1  # outcome unchanged: nothing new to distil
