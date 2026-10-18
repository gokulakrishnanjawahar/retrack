"""Guard: the test suite never has access to a real LLM API key."""

import os


def test_anthropic_key_is_not_available_to_tests():
    assert "ANTHROPIC_API_KEY" not in os.environ
