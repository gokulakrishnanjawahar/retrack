"""Embedding layer. No test reaches Google or spends anything."""

import math
from types import SimpleNamespace

import pytest
from google.auth import identity_pool

from retrack_server.config import Settings
from retrack_server.embeddings import (
    DIMENSIONS,
    FakeEmbedder,
    VertexEmbedder,
    cosine,
    embedder_from_settings,
    to_vector_literal,
)


def settings(**overrides) -> Settings:
    return Settings(**({"database_url": "unused", "key_pepper": "p"} | overrides))


def fake_vertex(embedder: VertexEmbedder, returned: int | None = None) -> list[dict]:
    calls = []

    def embed_content(**kwargs):
        calls.append(kwargs)
        count = len(kwargs["contents"]) if returned is None else returned
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * DIMENSIONS) for _ in range(count)]
        )

    embedder._client.models = SimpleNamespace(embed_content=embed_content)
    return calls


def test_vertex_request_shape():
    embedder = VertexEmbedder(project="retrack", location="asia-south1", client=SimpleNamespace())
    calls = fake_vertex(embedder)
    vectors = embedder.embed(["refund order 42", "cancel subscription"])

    assert len(vectors) == 2 and len(vectors[0]) == DIMENSIONS
    request = calls[0]
    assert request["model"] == "gemini-embedding-2"
    # Gemini Embedding 2 takes the task inside the text; task_type is not allowed.
    assert request["contents"] == [
        "task: sentence similarity | query: refund order 42",
        "task: sentence similarity | query: cancel subscription",
    ]
    config = request["config"]
    assert (config.task_type, config.output_dimensionality) == (None, DIMENSIONS)


def test_vertex_must_return_one_vector_per_text():
    embedder = VertexEmbedder(project="retrack", location="asia-south1", client=SimpleNamespace())
    fake_vertex(embedder, returned=1)
    with pytest.raises(ValueError, match="1 vectors for 2 texts"):
        embedder.embed(["refund order 42", "cancel subscription"])


def test_embeddings_are_off_unless_explicitly_enabled():
    assert embedder_from_settings(settings(google_cloud_project="retrack")) is None
    assert embedder_from_settings(settings(embeddings_enabled=True)) is None


def test_enabled_embedder_signs_in_without_a_key(monkeypatch):
    clients = []
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: clients.append(kwargs) or "client")
    embedder = embedder_from_settings(
        settings(
            embeddings_enabled=True,
            google_cloud_project="retrack",
            google_workload_identity_provider="projects/1/locations/global/"
            "workloadIdentityPools/vercel/providers/vercel",
            google_service_account_email="sa@retrack.iam.gserviceaccount.com",
        )
    )
    assert isinstance(embedder, VertexEmbedder)
    kwargs = clients[0]
    assert (kwargs["vertexai"], kwargs["project"], kwargs["location"]) == (
        True,
        "retrack",
        "global",
    )
    assert isinstance(kwargs["credentials"], identity_pool.Credentials)


def test_enabled_embedder_without_keyless_settings_uses_default_credentials(monkeypatch):
    clients = []
    monkeypatch.setattr("google.genai.Client", lambda **kwargs: clients.append(kwargs) or "client")
    embedder_from_settings(settings(embeddings_enabled=True, google_cloud_project="retrack"))
    assert clients[0]["credentials"] is None


def test_fake_embedder_matches_tasks_that_differ_only_in_numbers():
    fake = FakeEmbedder()
    a, b, c = fake.embed(["Refund order 42, damaged", "refund order 77 damaged", "Book a room"])
    assert cosine(a, b) == pytest.approx(1.0)
    assert cosine(a, c) < 0.5
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)


def test_vector_literal():
    assert to_vector_literal([0.5, -1.0, 0.0]) == "[0.5,-1.0,0.0]"
