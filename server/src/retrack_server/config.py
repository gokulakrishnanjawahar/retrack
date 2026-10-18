"""Server settings, read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    key_pepper: str
    # Shared secret for /internal/* worker routes; those routes are disabled without it.
    worker_secret: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [n for n in ("SERVER_DATABASE_URL", "RETRACK_KEY_PEPPER") if not os.getenv(n)]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
        return cls(
            database_url=os.environ["SERVER_DATABASE_URL"],
            key_pepper=os.environ["RETRACK_KEY_PEPPER"],
            worker_secret=os.environ.get("RETRACK_WORKER_SECRET") or None,
        )
