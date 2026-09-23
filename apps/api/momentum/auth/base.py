"""Authentication provider contract (docs/architecture/auth-and-permissions.md §2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from starlette.requests import Request


@dataclass(frozen=True)
class Principal:
    provider: str
    subject: str
    tenant_id: str | None = None
    email: str | None = None
    name: str | None = None
    roles: tuple[str, ...] = ()
    raw_claims: Mapping[str, Any] = field(default_factory=dict)


class AuthProvider(Protocol):
    name: str

    async def authenticate(self, request: Request) -> Principal | None: ...

    def login_url(self, return_to: str) -> str: ...

    def logout_url(self, return_to: str) -> str: ...


HostPrincipalResolver = Callable[[Request], Awaitable[Principal | None]]
