"""Server settings, read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    key_pepper: str
    # Shared secret for /internal/* worker routes; those routes are disabled without it.
    worker_secret: str | None = None
    # Retrack's own LLM. Off unless RETRACK_LLM_ENABLED=true AND a key is set, so a key
    # sitting in .env never spends credits by accident.
    anthropic_api_key: str | None = None
    llm_enabled: bool = False
    llm_model: str = "claude-haiku-5-5"
    llm_effort: str = "low"
    # Embeddings (Vertex AI). Off unless RETRACK_EMBEDDINGS_ENABLED=true AND a project is set.
    embeddings_enabled: bool = False
    google_cloud_project: str | None = None
    google_cloud_location: str = "asia-south1"

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [n for n in ("SERVER_DATABASE_URL", "RETRACK_KEY_PEPPER") if not os.getenv(n)]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
        return cls(
            database_url=os.environ["SERVER_DATABASE_URL"],
            key_pepper=os.environ["RETRACK_KEY_PEPPER"],
            worker_secret=os.environ.get("RETRACK_WORKER_SECRET") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            llm_enabled=os.environ.get("RETRACK_LLM_ENABLED", "").lower() == "true",
            llm_model=os.environ.get("RETRACK_LLM_MODEL") or "claude-haiku-5-5",
            llm_effort=os.environ.get("RETRACK_LLM_EFFORT") or "low",
            embeddings_enabled=os.environ.get("RETRACK_EMBEDDINGS_ENABLED", "").lower() == "true",
            google_cloud_project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
            google_cloud_location=os.environ.get("GOOGLE_CLOUD_LOCATION") or "asia-south1",
        )
