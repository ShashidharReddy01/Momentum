"""HTTP plumbing: request ids, CSRF guard and problem+json error rendering."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from momentum.core.errors import CsrfFailed, DomainError
from momentum.core.ids import new_id

PROBLEM = "application/problem+json"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "momentum"


def problem(
    request: Request, status: int, code: str, title: str, detail: str, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://momentum/errors/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
    }
    body.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or str(new_id())
        request.state.request_id = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    """Cookie-authenticated mutations must carry ``X-Requested-With: momentum``.

    Bearer-token requests and explicitly exempt prefixes (webhooks, public forms) are skipped.
    """

    def __init__(self, app: Any, *, api_prefix: str, exempt_prefixes: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self.api_prefix = api_prefix
        self.exempt = exempt_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            request.method not in SAFE_METHODS
            and path.startswith(self.api_prefix)
            and not path.startswith(self.exempt)
            and not request.headers.get("authorization", "").lower().startswith("bearer ")
            and request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE
        ):
            err = CsrfFailed()
            return problem(request, err.status, err.code, err.title, err.detail)
        return await call_next(request)


def install_error_handlers(app: FastAPI) -> None:
    log = structlog.get_logger("momentum.http")

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return problem(request, exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return problem(
            request, 422, "validation_failed", "Validation failed", "Invalid request", errors=errors
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error")
        return problem(request, 500, "internal_error", "Internal error", "Something went wrong")
