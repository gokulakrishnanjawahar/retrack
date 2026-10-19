"""Embeddings (docs/decisions.md): gemini-embedding-001 on Vertex AI in Mumbai, 1,536 dims.

Calls happen only when RETRACK_EMBEDDINGS_ENABLED=true and a Google Cloud project is set;
tests use FakeEmbedder. Results are cached per project by content hash, so unchanged text
is never embedded twice (docs/constraints.md).
"""

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import psycopg

from retrack_server.config import Settings

DIMENSIONS = 1536
MODEL = "gemini-embedding-001"


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VertexEmbedder:
    def __init__(self, *, project: str, location: str, model: str = MODEL, client: Any = None):
        self.model = model
        if client is None:
            from google import genai  # imported lazily: only production needs it

            client = genai.Client(vertexai=True, project=project, location=location)
        self._client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        response = self._client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY", output_dimensionality=DIMENSIONS
            ),
        )
        return [list(e.values) for e in response.embeddings]


@dataclass
class FakeEmbedder:
    """Deterministic bag-of-words vectors for tests: numbers are ignored, words are hashed."""

    model: str = "fake-embedder"
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for word in re.findall(r"[a-z]+", text.lower()):
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            vectors.append([x / norm for x in vector])
        return vectors


def embedder_from_settings(settings: Settings) -> Embedder | None:
    """The configured embedder, or None unless explicitly enabled with a project."""
    if not (settings.embeddings_enabled and settings.google_cloud_project):
        return None
    return VertexEmbedder(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_cached(conn: psycopg.Connection, embedder: Embedder, project_id: UUID, text: str) -> str:
    """Embedding of `text` as a pgvector literal, from the cache when possible.

    Call inside pipeline_scope for `project_id`.
    """
    digest = content_hash(text)
    row = conn.execute(
        "select embedding::text from public.embedding_cache"
        " where project_id = %s and model = %s and content_hash = %s",
        (project_id, embedder.model, digest),
    ).fetchone()
    if row:
        return row[0]
    literal = to_vector_literal(embedder.embed([text])[0])
    conn.execute(
        "insert into public.embedding_cache (project_id, model, content_hash, embedding)"
        " values (%s, %s, %s, %s::extensions.halfvec) on conflict do nothing",
        (project_id, embedder.model, digest, literal),
    )
    return literal
