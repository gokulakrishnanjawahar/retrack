"""Keyless Google sign-in from Vercel (Workload Identity Federation, docs/architecture.md).

Vercel gives every request a short-lived OIDC token (`x-vercel-oidc-token` header) proving
"project retrack-api of Gokul's team". Google's Security Token Service trades it for a
Google token, which then acts as the `retrack-embeddings` service account (Vertex AI User
only). No key or password exists anywhere. Locally, `vercel env pull` writes a development
token to `.env.local` as VERCEL_OIDC_TOKEN.
"""

import os
import threading

from google.auth import exceptions, identity_pool

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Vercel says not to cache the token: it changes in production. Requests that may embed
# remember the newest one; Google asks for it only when its own access token expires.
_latest_token: str | None = None
_lock = threading.Lock()


def remember_vercel_oidc_token(token: str | None) -> None:
    """Keep the token Vercel sent with the current request (ignored when missing)."""
    global _latest_token
    if token:
        with _lock:
            _latest_token = token


class VercelTokenSupplier(identity_pool.SubjectTokenSupplier):
    """The newest Vercel OIDC token: from a request on Vercel, else VERCEL_OIDC_TOKEN."""

    def get_subject_token(self, context, request) -> str:
        with _lock:
            token = _latest_token
        token = token or os.environ.get("VERCEL_OIDC_TOKEN")
        if not token:
            raise exceptions.RefreshError(
                "no Vercel OIDC token: on Vercel it comes with each request; locally run"
                " `vercel env pull .env.local` and load VERCEL_OIDC_TOKEN"
            )
        return token


def google_credentials(
    provider: str | None, service_account_email: str | None
) -> identity_pool.Credentials | None:
    """Keyless credentials, or None (Google's default credentials) when neither is set.

    `provider` is the workload identity provider's resource name:
    projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>.
    """
    if not provider and not service_account_email:
        return None
    if not (provider and service_account_email):
        raise ValueError(
            "set both GOOGLE_WORKLOAD_IDENTITY_PROVIDER and GOOGLE_SERVICE_ACCOUNT_EMAIL,"
            " or neither"
        )
    return identity_pool.Credentials(
        audience=f"//iam.googleapis.com/{provider}",
        subject_token_type="urn:ietf:params:oauth:token-type:jwt",
        token_url="https://sts.googleapis.com/v1/token",
        subject_token_supplier=VercelTokenSupplier(),
        service_account_impersonation_url=(
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
            f"{service_account_email}:generateAccessToken"
        ),
        scopes=_SCOPES,
    )
