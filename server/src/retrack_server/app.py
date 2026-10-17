"""Retrack HTTP API (FastAPI). Public routes live under /v1."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from retrack_server.api_keys import verify_api_key
from retrack_server.config import Settings
from retrack_server.ingest import store_run
from retrack_server.schemas import MAX_BODY_BYTES, RunIn

app = FastAPI(title="Retrack", docs_url=None, redoc_url=None, openapi_url=None)


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


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[psycopg.Connection]:
    # prepare_threshold=None: Supabase's transaction pooler does not support prepared statements.
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
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
