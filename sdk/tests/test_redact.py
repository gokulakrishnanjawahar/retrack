"""Client-side stripping of obvious secrets before a run leaves the customer's process."""

import pytest

from retrack.redact import redact_secrets


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "sk_live_51HxAbCdEfGhIjKlMnOpQr",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "rtk_live_" + "ab12" * 12,
    ],
)
def test_known_token_formats_are_stripped(secret):
    assert redact_secrets(f"use {secret} now") == "use <SECRET> now"


def test_bearer_url_credentials_and_assignments():
    assert redact_secrets("Bearer abcdefghijklmnop1234") == "Bearer <SECRET>"
    assert redact_secrets("https://u:p4ss@host/x") == "https://<SECRET>@host/x"
    assert redact_secrets("password=hunter22") == "password=<SECRET>"


def test_nested_values_and_sensitive_keys():
    value = {"order_id": "123", "api_key": "abc", "items": ["token=abcd1234", 3], "n": None}
    assert redact_secrets(value) == {
        "order_id": "123",
        "api_key": "<SECRET>",
        "items": ["token=<SECRET>", 3],
        "n": None,
    }


def test_ordinary_text_untouched():
    text = "Refund order #123 for priya@example.com"
    assert redact_secrets(text) == text
