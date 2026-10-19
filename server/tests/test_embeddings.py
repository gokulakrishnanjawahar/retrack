"""Embedding layer. No test reaches Google or spends anything."""

import math
from types import SimpleNamespace

import pytest

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


def test_vertex_request_shape(monkeypatch):
    embedder = VertexEmbedder(project="retrack", location="asia-south1", client=SimpleNamespace())
    calls = []

    def embed_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * DIMENSIONS) for _ in kwargs["contents"]]
        )

    embedder._client.models = SimpleNamespace(embed_content=embed_content)
    vectors = embedder.embed(["refund order 42", "cancel subscription"])

    assert len(vectors) == 2 and len(vectors[0]) == DIMENSIONS
    request = calls[0]
    assert request["model"] == "gemini-embedding-001"
    assert request["contents"] == ["refund order 42", "cancel subscription"]
    config = request["config"]
    assert (config.task_type, config.output_dimensionality) == ("SEMANTIC_SIMILARITY", DIMENSIONS)


def test_embeddings_are_off_unless_explicitly_enabled():
    assert embedder_from_settings(settings(google_cloud_project="retrack")) is None
    assert embedder_from_settings(settings(embeddings_enabled=True)) is None


def test_fake_embedder_matches_tasks_that_differ_only_in_numbers():
    fake = FakeEmbedder()
    a, b, c = fake.embed(["Refund order 42, damaged", "refund order 77 damaged", "Book a room"])
    assert cosine(a, b) == pytest.approx(1.0)
    assert cosine(a, c) < 0.5
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)


def test_vector_literal():
    assert to_vector_literal([0.5, -1.0, 0.0]) == "[0.5,-1.0,0.0]"
