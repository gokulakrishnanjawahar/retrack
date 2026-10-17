import uuid

import pytest


def _run_payload(**overrides) -> dict:
    payload = {
        "id": str(uuid.uuid4()),
        "agent": "support-agent",
        "task": "Refund order #123 that arrived damaged",
        "model_id": "claude-haiku-5-5",
        "tool_versions": {"stripe": "2026-09", "orders_api": "v3"},
        "tokens_in": 1200,
        "tokens_out": 300,
        "cost_usd": 0.004,
        "latency_ms": 5400,
        "steps": [
            {
                "idx": 0,
                "type": "llm",
                "tokens_in": 1000,
                "tokens_out": 200,
                "latency_ms": 900,
            },
            {
                "idx": 1,
                "type": "tool",
                "tool_name": "orders_api",
                "args": {"order_id": "123", "api_key": "sk_live_secret"},
                "result_class": "ok",
                "latency_ms": 120,
                "input_trust": "untrusted",
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def run_payload():
    """Factory for a valid run ingest payload; keyword arguments override fields."""
    return _run_payload
