"""S5.1.6 (ADR-0009): API-token authentication, as an ``AuthProvider``.

``ApiTokenProvider`` wraps whichever provider the deployment uses (dev, Easy Auth, host): a
request with ``Authorization: Bearer mtm_…`` is authenticated by its token and nothing else (a
bad token is a 401, never a fall-back to a cookie); every other request goes to the wrapped
provider unchanged. A token principal maps straight to its user (``resolve``) — no identity
linking, no provisioning — acts with ``via="api"``, and may only use what its scopes allow
(``required_scope``), on top of the user's own permissions.

Secrets never reach logs: only the token id and prefix are ever recorded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from momentum.auth.base import AuthProvider, Principal
from momentum.core.errors import Forbidden, NotInvited
from momentum.core.settings import Settings
from momentum.domain.users.models import User
from momentum.domain.users.tokens import authenticate_token
from momentum.domain.workspace.models import Workspace

PROVIDER = "api_token"
READ_METHODS = ("GET", "HEAD", "OPTIONS")
TASK_WRITE_PREFIXES = (
    "/tasks",
    "/projects",
    "/sections",
    "/comments",
    "/fields",
    "/tags",
    "/forms",
    "/rules",
    "/templates",
    "/status-updates",
    "/undo",
    "/me/tasks",
    "/me/prefs",
    "/notifications",
    "/favorites",
    "/mentions",
)


class ApiTokenProvider:
    """Bearer tokens first, then the deployment's own provider."""

    name = PROVIDER

    def __init__(self, inner: AuthProvider, session_factory: async_sessionmaker[AsyncSession]):
        self.inner = inner
        self._sf = session_factory

    async def authenticate(self, request: Request) -> Principal | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return await self.inner.authenticate(request)
        raw = header[7:].strip()
        async with self._sf() as session, session.begin():
            found = await authenticate_token(session, raw)
        if found is None:
            return None
        token, user = found
        return Principal(
            provider=PROVIDER,
            subject=str(token.id),
            email=user.email,
            name=user.name,
            raw_claims={"user_id": str(user.id), "scopes": tuple(token.scopes)},
        )

    def login_url(self, return_to: str) -> str:
        return self.inner.login_url(return_to)

    def logout_url(self, return_to: str) -> str:
        return self.inner.logout_url(return_to)


def with_api_tokens(
    inner: AuthProvider, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AuthProvider:
    return ApiTokenProvider(inner, session_factory) if settings.api_tokens_enabled else inner


@dataclass(frozen=True)
class Resolved:
    user: User
    workspace: Workspace
    scopes: tuple[str, ...] | None  # None: a signed-in session, not a token


async def resolve(session: AsyncSession, settings: Settings, principal: Principal) -> Resolved:
    """The user behind a principal: a token's own user, or the identity-provider flow."""
    if principal.provider != PROVIDER:
        from momentum.auth.identity import resolve_user

        user, workspace = await resolve_user(session, settings, principal)
        return Resolved(user, workspace, None)
    owner = await session.get(User, uuid.UUID(str(principal.raw_claims["user_id"])))
    ws = await session.get(Workspace, owner.workspace_id) if owner is not None else None
    if owner is None or ws is None or owner.status != "active":
        raise NotInvited()
    return Resolved(owner, ws, tuple(principal.raw_claims.get("scopes") or ()))


def required_scope(method: str, path: str) -> str:
    """The scope a token needs for this request (``path`` relative to ``/api/v1``)."""
    if method.upper() in READ_METHODS:
        return "read"
    if "/attachments" in path:
        return "attachments:write"
    if path.startswith("/ai/") and not path.startswith("/ai/admin"):
        return "ai"
    if path.startswith("/agents/") and path.endswith("/run"):
        return "ai"
    if path.startswith(TASK_WRITE_PREFIXES):
        return "tasks:write"
    return "admin"


def check_scope(scopes: tuple[str, ...], method: str, full_path: str) -> None:
    """Refuse a token request its scopes don't cover. Any scope includes reading; ``admin``
    covers everything (still within the user's own role)."""
    marker = "/api/v1"
    path = full_path[full_path.index(marker) + len(marker) :] if marker in full_path else full_path
    needed = required_scope(method, path)
    if "admin" in scopes or needed in scopes or (needed == "read" and scopes):
        return
    raise Forbidden(f"This token doesn't have the {needed} scope", code="token_scope")
