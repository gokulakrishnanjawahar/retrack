"""Keyless Google sign-in from Vercel. No test reaches Google."""

import pytest
from google.auth import exceptions, identity_pool
from starlette.requests import Request

from retrack_server import gcp_auth
from retrack_server.app import embedder_dependency
from retrack_server.config import Settings
from retrack_server.gcp_auth import (
    VercelTokenSupplier,
    google_credentials,
    remember_vercel_oidc_token,
)

PROVIDER = "projects/518519618849/locations/global/workloadIdentityPools/vercel/providers/vercel"
SERVICE_ACCOUNT = "retrack-embeddings@retrack.iam.gserviceaccount.com"


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    monkeypatch.setattr(gcp_auth, "_latest_token", None)
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)


def settings(**overrides) -> Settings:
    return Settings(**({"database_url": "unused", "key_pepper": "p"} | overrides))


def test_supplier_prefers_the_latest_request_token_over_the_environment(monkeypatch):
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "local-token")
    supplier = VercelTokenSupplier()
    assert supplier.get_subject_token(None, None) == "local-token"
    remember_vercel_oidc_token("request-token")
    assert supplier.get_subject_token(None, None) == "request-token"


def test_missing_or_empty_headers_keep_the_previous_token():
    remember_vercel_oidc_token("request-token")
    remember_vercel_oidc_token(None)
    remember_vercel_oidc_token("")
    assert VercelTokenSupplier().get_subject_token(None, None) == "request-token"


def test_supplier_fails_clearly_without_any_token():
    with pytest.raises(exceptions.RefreshError, match="VERCEL_OIDC_TOKEN"):
        VercelTokenSupplier().get_subject_token(None, None)


def test_credentials_exchange_the_vercel_token_and_act_as_the_service_account():
    creds = google_credentials(PROVIDER, SERVICE_ACCOUNT)
    assert isinstance(creds, identity_pool.Credentials)
    info = creds.info
    assert info["audience"] == f"//iam.googleapis.com/{PROVIDER}"
    assert info["subject_token_type"] == "urn:ietf:params:oauth:token-type:jwt"
    assert info["token_url"] == "https://sts.googleapis.com/v1/token"
    assert info["service_account_impersonation_url"] == (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{SERVICE_ACCOUNT}:generateAccessToken"
    )
    assert creds.service_account_email == SERVICE_ACCOUNT


def test_no_keyless_settings_means_default_google_credentials():
    assert google_credentials(None, None) is None


@pytest.mark.parametrize("provider,account", [(PROVIDER, None), (None, SERVICE_ACCOUNT)])
def test_half_configured_keyless_sign_in_is_an_error(provider, account):
    with pytest.raises(ValueError, match="GOOGLE_WORKLOAD_IDENTITY_PROVIDER"):
        google_credentials(provider, account)


def test_embedding_routes_remember_the_token_vercel_sends():
    request = Request({"type": "http", "headers": [(b"x-vercel-oidc-token", b"request-token")]})
    assert embedder_dependency(request, settings()) is None  # embeddings off: still remembered
    assert VercelTokenSupplier().get_subject_token(None, None) == "request-token"


def test_settings_read_keyless_values_from_environment(monkeypatch):
    monkeypatch.setenv("SERVER_DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("RETRACK_KEY_PEPPER", "p")
    monkeypatch.setenv("GOOGLE_WORKLOAD_IDENTITY_PROVIDER", PROVIDER)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", SERVICE_ACCOUNT)
    s = Settings.from_env()
    assert (s.google_workload_identity_provider, s.google_service_account_email) == (
        PROVIDER,
        SERVICE_ACCOUNT,
    )
