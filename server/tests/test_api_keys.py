import re

import pytest

from retrack_server.api_keys import InvalidKeyFormat, generate_key, hash_key, key_prefix

PEPPER = "test-pepper"


def test_generated_key_has_expected_format():
    key = generate_key()
    assert re.fullmatch(r"rtk_live_[0-9a-f]{48}", key.secret)


def test_prefix_is_shown_part_of_secret():
    key = generate_key()
    assert key.prefix == key.secret[: len("rtk_live_") + 8]
    assert key_prefix(key.secret) == key.prefix


def test_test_environment_keys():
    assert generate_key(env="test").secret.startswith("rtk_test_")


def test_unknown_environment_rejected():
    with pytest.raises(ValueError):
        generate_key(env="prod")


def test_keys_are_unique():
    assert generate_key().secret != generate_key().secret


def test_hash_is_deterministic_and_pepper_dependent():
    secret = generate_key().secret
    assert hash_key(secret, PEPPER) == hash_key(secret, PEPPER)
    assert hash_key(secret, PEPPER) != hash_key(secret, "other-pepper")
    assert secret not in hash_key(secret, PEPPER)


def test_hash_requires_pepper():
    with pytest.raises(ValueError):
        hash_key(generate_key().secret, "")


@pytest.mark.parametrize(
    "bad",
    ["", "rtk_live_", "rtk_live_xyz", "sk_live_" + "a" * 48, "rtk_live_" + "A" * 48],
)
def test_malformed_keys_rejected(bad):
    with pytest.raises(InvalidKeyFormat):
        key_prefix(bad)
