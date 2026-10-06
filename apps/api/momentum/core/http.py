"""HTTP plumbing: request ids, CSRF guard, NUL-free input and problem+json error rendering."""

from __future__ import annotations

import contextlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from momentum.core.errors import CsrfFailed, DomainError
from momentum.core.ids import new_id
from momentum.core.text import NUL, strip_nul

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


class StripNulMiddleware:
    """Removes NUL characters from API query strings and JSON bodies before anything reads them
    (``core/text.py`` says why). Pure ASGI, and a no-op unless a NUL is actually present, so normal
    requests pay one substring check."""

    def __init__(self, app: Any, *, api_prefix: str) -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.api_prefix):
            await self.app(scope, receive, send)
            return
        qs: bytes = scope.get("query_string", b"")
        if b"%00" in qs or NUL.encode() in qs:
            pairs = parse_qsl(qs.decode("latin-1"), keep_blank_values=True)
            scope = {**scope, "query_string": urlencode(strip_nul(pairs)).encode("latin-1")}
        headers = dict(scope.get("headers") or [])
        if b"application/json" not in headers.get(b"content-type", b""):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                await self.app(scope, _replay([message], receive), send)
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        if rb"\u0000" in body or NUL.encode() in body:  # JSON-escaped or raw NUL
            with contextlib.suppress(ValueError):  # not valid JSON: validation will say so
                body = json.dumps(strip_nul(json.loads(body)), ensure_ascii=False).encode()
            scope = {
                **scope,
                "headers": [
                    (k, str(len(body)).encode() if k == b"content-length" else v)
                    for k, v in scope["headers"]
                ],
            }
        await self.app(
            scope,
            _replay([{"type": "http.request", "body": body, "more_body": False}], receive),
            send,
        )


class SecurityHeadersMiddleware:
    """S7.5.2 (OWASP ASVS L1 V14.4): security headers on every response.

    Pages get a Content Security Policy that only runs Momentum's own scripts (no inline
    script, no eval), allows inline *styles* (the UI sets style attributes), images from
    anywhere over HTTPS (avatars), fonts and connections to this origin only (including its
    websocket), and says who may frame the app. API responses can't be rendered at all
    (``default-src 'none'``). A response that set its own CSP (a file download's sandbox)
    keeps it. HSTS only in production (behind TLS)."""

    def __init__(self, app: Any, *, api_prefix: str, settings: Any) -> None:
        self.app = app
        self.api_prefix = api_prefix
        self.hsts = settings.env == "production"
        self.frame_ancestors = settings.frame_ancestors or "'self'"
        self.page_csp: str = settings.content_security_policy

    def _csp(self, scope: Any) -> str:
        if scope["path"].startswith(self.api_prefix):
            return "default-src 'none'; frame-ancestors 'none'"
        if self.page_csp:
            return self.page_csp
        host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
        sockets = f" ws://{host} wss://{host}" if host else ""
        return (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; font-src 'self' data:; "
            f"connect-src 'self'{sockets}; object-src 'none'; base-uri 'self'; "
            f"form-action 'self'; frame-ancestors {self.frame_ancestors}"
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        csp = self._csp(scope).encode("latin-1")
        frame = {"'none'": b"DENY", "'self'": b"SAMEORIGIN"}.get(self.frame_ancestors)

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                have = {k.lower() for k, _ in headers}
                extra = [
                    (b"content-security-policy", csp),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (
                        b"permissions-policy",
                        b"camera=(), microphone=(), geolocation=(), payment=()",
                    ),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if frame:
                    extra.append((b"x-frame-options", frame))
                if self.hsts:
                    extra.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                headers += [(k, v) for k, v in extra if k not in have]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _replay(messages: list[dict[str, Any]], downstream: Any) -> Any:
    """The body we already read, then the real channel: a streaming response (SSE) waits on it
    for the client's disconnect, so answering "disconnected" here would end every stream at once."""
    queue = list(messages)

    async def receive() -> dict[str, Any]:
        if queue:
            return queue.pop(0)
        return await downstream()  # type: ignore[no-any-return]

    return receive


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
