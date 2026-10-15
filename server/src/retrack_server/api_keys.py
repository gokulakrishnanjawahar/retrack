"""Per-project API keys.

A key looks like `rtk_live_<48 hex chars>`. The full secret is shown once at
creation. The database stores only an HMAC-SHA256 of the secret, keyed with a
server-side pepper, plus a short prefix used to find the key.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from uuid import UUID

import psycopg

from retrack_server.db import project_scope

ENVIRONMENTS = ("live", "test")
_KEY_RE = re.compile(r"rtk_(live|test)_[0-9a-f]{48}")
_PREFIX_RANDOM_CHARS = 8


class InvalidKeyFormat(ValueError):
    pass


@dataclass(frozen=True)
class GeneratedKey:
    secret: str
    prefix: str


@dataclass(frozen=True)
class NewApiKey:
    id: UUID
    secret: str
    prefix: str


def generate_key(env: str = "live") -> GeneratedKey:
    if env not in ENVIRONMENTS:
        raise ValueError(f"env must be one of {ENVIRONMENTS}")
    secret = f"rtk_{env}_{secrets.token_hex(24)}"
    return GeneratedKey(secret=secret, prefix=key_prefix(secret))


def key_prefix(secret: str) -> str:
    if not _KEY_RE.fullmatch(secret):
        raise InvalidKeyFormat("not a Retrack API key")
    return secret[: len("rtk_live_") + _PREFIX_RANDOM_CHARS]


def hash_key(secret: str, pepper: str) -> str:
    if not pepper:
        raise ValueError("pepper must not be empty")
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def create_api_key(
    conn: psycopg.Connection, project_id: UUID, name: str, pepper: str, env: str = "live"
) -> NewApiKey:
    """Admin operation: store a new key for a project and return its secret (shown once)."""
    key = generate_key(env)
    key_id = conn.execute(
        "insert into public.api_keys (project_id, prefix, key_hash, name)"
        " values (%s, %s, %s, %s) returning id",
        (project_id, key.prefix, hash_key(key.secret, pepper), name),
    ).fetchone()[0]
    return NewApiKey(id=key_id, secret=key.secret, prefix=key.prefix)


def verify_api_key(conn: psycopg.Connection, secret: str, pepper: str) -> UUID | None:
    """Return the key's project id, or None if the key is malformed, unknown or revoked."""
    try:
        prefix = key_prefix(secret)
    except InvalidKeyFormat:
        return None
    with project_scope(conn, None):
        row = conn.execute(
            "select private.verify_api_key(%s, %s)", (prefix, hash_key(secret, pepper))
        ).fetchone()
    return row[0]


def revoke_api_key(conn: psycopg.Connection, key_id: UUID) -> None:
    """Admin operation."""
    conn.execute(
        "update public.api_keys set revoked_at = now() where id = %s and revoked_at is null",
        (key_id,),
    )


def rotate_api_key(conn: psycopg.Connection, key_id: UUID, pepper: str) -> NewApiKey:
    """Admin operation: revoke a key and issue a replacement with the same name and project."""
    with conn.transaction():
        project_id, name, prefix = conn.execute(
            "select project_id, name, prefix from public.api_keys where id = %s", (key_id,)
        ).fetchone()
        env = prefix.split("_")[1]
        revoke_api_key(conn, key_id)
        return create_api_key(conn, project_id, name, pepper, env)
