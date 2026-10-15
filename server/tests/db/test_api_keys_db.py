"""API key lifecycle against the database: create, verify, revoke, rotate."""

from retrack_server.api_keys import create_api_key, revoke_api_key, rotate_api_key, verify_api_key

PEPPER = "test-pepper"


def test_created_key_verifies_to_its_project(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    assert verify_api_key(conn, key.secret, PEPPER) == a.project_id


def test_only_hash_and_prefix_are_stored(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    stored = conn.execute(
        "select prefix, key_hash from public.api_keys where id = %s", (key.id,)
    ).fetchone()
    assert stored[0] == key.prefix
    assert key.secret not in stored[1]


def test_wrong_secret_with_valid_prefix_fails(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    forged = key.prefix + "0" * (len(key.secret) - len(key.prefix))
    assert verify_api_key(conn, forged, PEPPER) is None


def test_wrong_pepper_fails(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    assert verify_api_key(conn, key.secret, "other-pepper") is None


def test_malformed_key_fails_without_error(conn, tenants):
    assert verify_api_key(conn, "not-a-key", PEPPER) is None


def test_revoked_key_fails(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    revoke_api_key(conn, key.id)
    assert verify_api_key(conn, key.secret, PEPPER) is None


def test_verify_records_last_used(conn, tenants):
    a, _ = tenants
    key = create_api_key(conn, a.project_id, "ci", PEPPER)
    verify_api_key(conn, key.secret, PEPPER)
    last_used = conn.execute(
        "select last_used_at from public.api_keys where id = %s", (key.id,)
    ).fetchone()[0]
    assert last_used is not None


def test_rotate_revokes_old_and_issues_new(conn, tenants):
    a, _ = tenants
    old = create_api_key(conn, a.project_id, "ci", PEPPER)
    new = rotate_api_key(conn, old.id, PEPPER)
    assert verify_api_key(conn, old.secret, PEPPER) is None
    assert verify_api_key(conn, new.secret, PEPPER) == a.project_id
    name = conn.execute("select name from public.api_keys where id = %s", (new.id,)).fetchone()[0]
    assert name == "ci"
