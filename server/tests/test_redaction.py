"""Redaction of secrets and personal data before anything is stored or embedded."""

import pytest

from retrack_server.redaction import redact_text, redact_value

SECRETS = [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "sk-proj-AbCdEfGhIjKlMnOpQrStUvWx",
    "sk_live_51HxAbCdEfGhIjKlMnOpQr",
    "rk_test_51HxAbCdEfGhIjKlMnOpQr",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
    "xoxb-123456789012-abcdefghijkl",
    "AIzaSyA-1234567890abcdefghijklmnopqrstu",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "rtk_live_" + "ab12" * 12,
    "Zx9Qw3Er7Ty1Ui5Op2As8Df4Gh6Jk0Lm",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secrets_are_redacted(secret):
    text, counts = redact_text(f"call the api with {secret} please")
    assert secret not in text
    assert "<SECRET>" in text
    assert counts["secret"] >= 1


def test_private_key_block_is_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n-----END RSA PRIVATE KEY-----"
    text, _ = redact_text(f"key: {pem}")
    assert "MIIEow" not in text and "<SECRET>" in text


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("password=hunter22 and more", "password="),
        ("api_key: 'abcd1234efgh'", "api_key:"),
        ("Authorization: Bearer abcdefghijklmnop1234", "Bearer"),
        ("postgres://admin:s3cretPass@db.example.com/app", "@db.example.com"),
    ],
)
def test_secret_assignments_keep_context(raw, kept):
    text, counts = redact_text(raw)
    assert kept in text
    assert counts["secret"] == 1
    assert "hunter22" not in text and "s3cretPass" not in text


@pytest.mark.parametrize(
    ("raw", "placeholder"),
    [
        ("mail me at priya.sharma@example.co.in", "<EMAIL>"),
        ("call +91 98765 43210 today", "<PHONE>"),
        ("call 9876543210 today", "<PHONE>"),
        ("call (415) 555-0132 today", "<PHONE>"),
        ("card 4111 1111 1111 1111 exp 12/29", "<CARD>"),
        ("card 5500-0000-0000-0004", "<CARD>"),
        ("aadhaar 2345 6789 0124", "<AADHAAR>"),
        ("PAN ABCDE1234F on file", "<PAN>"),
        ("ssn 123-45-6789", "<SSN>"),
    ],
)
def test_personal_data_is_redacted(raw, placeholder):
    text, _ = redact_text(raw)
    assert placeholder in text


@pytest.mark.parametrize(
    "safe",
    [
        "Refund order #123 that arrived damaged",
        "run 2382483d-cdc8-41bd-986d-afa286dabfaf finished",
        "commit 3f786850e387550fdab836ed7e6dc881de23001b",
        "card 4111 1111 1111 1112 fails the checksum",
        "aadhaar-like 2345 6789 0123 fails the checksum",
        "orders_api v3 returned 429 above 5 req/s",
        "price is 1299 rupees, quantity 12",
        "the meeting is on 2026-10-18 at 14:30",
    ],
)
def test_ordinary_text_is_left_alone(safe):
    text, counts = redact_text(safe)
    assert text == safe
    assert sum(counts.values()) == 0


def test_nested_values_and_sensitive_keys():
    value = {
        "order_id": "123",
        "customer": {"email": "a@b.co", "note": "token=abcd1234efgh"},
        "headers": {"Authorization": "anything at all", "cookie": "session=xyz"},
        "client_secret": "short",
        "items": ["call 9876543210", 42, None, True],
    }
    redacted, counts = redact_value(value)
    assert redacted == {
        "order_id": "123",
        "customer": {"email": "<EMAIL>", "note": "token=<SECRET>"},
        "headers": {"Authorization": "<SECRET>", "cookie": "<SECRET>"},
        "client_secret": "<SECRET>",
        "items": ["call <PHONE>", 42, None, True],
    }
    assert counts["secret"] == 4
    assert counts["email"] == 1
    assert counts["phone"] == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Guess-based checks are skipped for identifier fields...
        ({"order_id": "9876543210"}, {"order_id": "9876543210"}),
        ({"invoice_no": "(415) 555-0132"}, {"invoice_no": "(415) 555-0132"}),
        (
            {"file_id": "Zx9Qw3Er7Ty1Ui5Op2As8Df4Gh6Jk0Lm"},
            {"file_id": "Zx9Qw3Er7Ty1Ui5Op2As8Df4Gh6Jk0Lm"},
        ),
        ({"sha": "Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56"}, {"sha": "Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56"}),
        ({"items": [{"sku": "9123456780"}]}, {"items": [{"sku": "9123456780"}]}),
        # ...but certain checks still apply to them.
        ({"order_id": "sk_live_51HxAbCdEfGhIjKlMnOpQr"}, {"order_id": "<SECRET>"}),
        ({"ref": "priya@example.com"}, {"ref": "<EMAIL>"}),
        ({"order_id": "4111 1111 1111 1111"}, {"order_id": "<CARD>"}),
        ({"url": "https://u:p4ssword@host/x"}, {"url": "https://<SECRET>@host/x"}),
        # Other fields and free text stay strict.
        ({"note": "9876543210"}, {"note": "<PHONE>"}),
        ({"contact": "9876543210"}, {"contact": "<PHONE>"}),
    ],
)
def test_identifier_fields_skip_only_the_guess_based_checks(value, expected):
    assert redact_value(value)[0] == expected


def test_free_text_stays_strict():
    assert redact_text("order 9876543210")[0] == "order <PHONE>"
