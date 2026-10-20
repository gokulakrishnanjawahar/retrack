"""Retrack HTTP API (FastAPI). Public routes live under /v1."""

import hmac
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from retrack_server.api_keys import verify_api_key
from retrack_server.config import Settings
from retrack_server.db import enqueue_run, project_scope
from retrack_server.embeddings import Embedder, embedder_from_settings
from retrack_server.ingest import store_run
from retrack_server.llm import LLMClient, llm_from_settings
from retrack_server.recall import recall
from retrack_server.redaction import redact_value
from retrack_server.schemas import (
    MAX_BODY_BYTES,
    MAX_FEEDBACK_BYTES,
    FeedbackIn,
    RecallIn,
    RunIn,
)
from retrack_server.scoring import add_signal
from retrack_server.worker import drain

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


app = FastAPI(title="Retrack", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "invalid_request", str(exc.errors()))


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return error_response(exc.status_code, "http_error", str(exc.detail))


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_llm(settings: Settings) -> LLMClient | None:
    """Retrack's own LLM, or None unless RETRACK_LLM_ENABLED=true and a key is set."""
    return llm_from_settings(settings)


@lru_cache
def get_embedder(settings: Settings) -> Embedder | None:
    """Vertex AI embeddings, or None unless RETRACK_EMBEDDINGS_ENABLED=true and a project is set."""
    return embedder_from_settings(settings)


def llm_dependency(settings: Annotated[Settings, Depends(get_settings)]) -> LLMClient | None:
    return get_llm(settings)


def embedder_dependency(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Embedder | None:
    return get_embedder(settings)


def get_pool(settings: Settings) -> ConnectionPool:
    """One connection pool per server instance, opened on first use and reused by requests."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings.database_url,
                # Supabase's transaction pooler does not support prepared statements.
                kwargs={"prepare_threshold": None},
                min_size=1,
                max_size=5,
                # Serverless instances sleep between requests; replace dead connections on checkout.
                check=ConnectionPool.check_connection,
                max_idle=300,
                open=True,
            )
        return _pool


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[psycopg.Connection]:
    with get_pool(settings).connection() as conn:
        yield conn


def authenticated_project(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> UUID:
    scheme, _, token = (authorization or "").partition(" ")
    project_id = None
    if scheme.lower() == "bearer" and token:
        project_id = verify_api_key(conn, token.strip(), settings.key_pepper)
    if project_id is None:
        raise ApiError(401, "unauthorized", "missing, invalid or revoked API key")
    return project_id


@app.post("/v1/runs", status_code=202)
async def ingest_run(
    request: Request,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    project_id: Annotated[UUID, Depends(authenticated_project)],
) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes")
    try:
        run = RunIn.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(422, "invalid_request", str(exc.errors(include_url=False))) from exc

    duplicate = await run_in_threadpool(store_run, conn, project_id, run)
    return JSONResponse({"id": str(run.id), "duplicate": duplicate}, status_code=202)


@app.post("/internal/drain")
async def internal_drain(
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[LLMClient | None, Depends(llm_dependency)],
    embedder: Annotated[Embedder | None, Depends(embedder_dependency)],
    x_retrack_worker_secret: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Worker entry point, called by Supabase Cron. Never accepts customer API keys."""
    if not settings.worker_secret:
        raise ApiError(503, "not_configured", "worker routes are not configured")
    if not x_retrack_worker_secret or not hmac.compare_digest(
        x_retrack_worker_secret.encode(), settings.worker_secret.encode()
    ):
        raise ApiError(401, "unauthorized", "missing or invalid worker secret")
    result = await run_in_threadpool(drain, conn, llm=llm, embedder=embedder)
    return JSONResponse(
        {
            "processed": result.processed,
            "retrying": result.retrying,
            "dead_lettered": result.dead_lettered,
            "scoring_gave_up": result.scoring_gave_up,
        }
    )


@app.post("/v1/feedback", status_code=202)
async def record_feedback(
    request: Request,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    project_id: Annotated[UUID, Depends(authenticated_project)],
) -> JSONResponse:
    """Attach a late outcome signal (test result, business event, user feedback) to a run."""
    body = await request.body()
    if len(body) > MAX_FEEDBACK_BYTES:
        raise ApiError(413, "payload_too_large", f"request body exceeds {MAX_FEEDBACK_BYTES} bytes")
    try:
        feedback = FeedbackIn.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(422, "invalid_request", str(exc.errors(include_url=False))) from exc

    def store() -> tuple | None:
        detail, _ = redact_value(feedback.detail)
        with project_scope(conn, project_id):
            exists = conn.execute(
                "select 1 from public.runs where project_id = %s and id = %s",
                (project_id, feedback.run_id),
            ).fetchone()
            if exists is None:
                return None
            before = conn.execute(
                "select outcome from public.runs where project_id = %s and id = %s",
                (project_id, feedback.run_id),
            ).fetchone()[0]
            add_signal(
                conn, project_id, feedback.run_id, feedback.source, feedback.outcome, None, detail
            )
            row = conn.execute(
                "select outcome, outcome_source, confidence from public.runs"
                " where project_id = %s and id = %s",
                (project_id, feedback.run_id),
            ).fetchone()
            if row[0] != before:  # the outcome changed: distil the run again
                enqueue_run(conn, feedback.run_id)
            return row

    row = await run_in_threadpool(store)
    if row is None:
        raise ApiError(404, "run_not_found", "no run with this id in this project")
    return JSONResponse(
        {
            "run_id": str(feedback.run_id),
            "outcome": row[0],
            "outcome_source": row[1],
            "confidence": row[2],
        },
        status_code=202,
    )


@app.post("/v1/recall")
async def recall_memory(
    request: Request,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    project_id: Annotated[UUID, Depends(authenticated_project)],
    embedder: Annotated[Embedder | None, Depends(embedder_dependency)],
) -> JSONResponse:
    """Gated playbooks and failure warnings for the task an agent is about to do."""
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes")
    try:
        recall_request = RecallIn.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(422, "invalid_request", str(exc.errors(include_url=False))) from exc
    result = await run_in_threadpool(recall, conn, project_id, recall_request, embedder)
    return JSONResponse(
        {
            "recall_id": result.recall_id,
            "playbooks": result.playbooks,
            "warnings": result.warnings,
            "holdout": result.holdout,
            "replay_eligible": False,
            "mode": result.mode,
        }
    )
