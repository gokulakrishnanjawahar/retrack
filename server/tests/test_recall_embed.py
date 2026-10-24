"""Recall's bounded wait for the query embedding. No test reaches Google."""

import logging
import time

from retrack_server.config import Settings
from retrack_server.embeddings import FakeEmbedder
from retrack_server.recall import _embed_with_timeout


class SlowEmbedder(FakeEmbedder):
    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay

    def embed(self, texts):
        time.sleep(self.delay)
        return super().embed(texts)


class BrokenEmbedder(FakeEmbedder):
    def embed(self, texts):
        raise PermissionError("denied")


def test_fast_embedding_is_used():
    assert _embed_with_timeout(FakeEmbedder(), "refund order", timeout=1.0).startswith("[")


def test_slow_embedding_falls_back_to_keywords_and_says_how_long_it_waited(caplog):
    with caplog.at_level(logging.WARNING, logger="retrack_server.recall"):
        assert _embed_with_timeout(SlowEmbedder(0.3), "refund order", timeout=0.05) is None
    assert "keywords after" in caplog.text and "TimeoutError" in caplog.text


def test_a_longer_wait_lets_a_slow_embedding_through():
    assert _embed_with_timeout(SlowEmbedder(0.05), "refund order", timeout=0.5) is not None


def test_embedding_errors_fall_back_and_are_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="retrack_server.recall"):
        assert _embed_with_timeout(BrokenEmbedder(), "refund order", timeout=1.0) is None
    assert "PermissionError" in caplog.text


def test_no_embedder_means_keywords_without_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="retrack_server.recall"):
        assert _embed_with_timeout(None, "refund order", timeout=1.0) is None
    assert caplog.text == ""


def test_settings_read_the_recall_wait_from_environment(monkeypatch):
    monkeypatch.setenv("SERVER_DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("RETRACK_KEY_PEPPER", "p")
    assert Settings.from_env().recall_embed_timeout_ms == Settings.recall_embed_timeout_ms
    monkeypatch.setenv("RETRACK_RECALL_EMBED_TIMEOUT_MS", "900")
    assert Settings.from_env().recall_embed_timeout_ms == 900


def test_default_wait_covers_embedding_2_from_vercel():
    # Measured 2026-10-24 from Vercel bom1: gemini-embedding-2 (global) took 350-505 ms.
    from retrack_server.recall import EMBED_TIMEOUT_SECONDS

    assert Settings.recall_embed_timeout_ms == 800
    assert EMBED_TIMEOUT_SECONDS == 0.8
