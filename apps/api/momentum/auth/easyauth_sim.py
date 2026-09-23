"""Local Easy Auth simulator: builds realistic principal headers from the dev session, so the
real Easy Auth parser runs on every local request (AUTH_MODE=easyauth-sim)."""

from __future__ import annotations

import base64
import json
import uuid

from starlette.requests import Request

from momentum.auth.base import Principal
from momentum.auth.dev import DevSession
from momentum.auth.easyauth import (
    CLAIM_OID,
    CLAIM_ROLE,
    CLAIM_TID,
    EasyAuthProvider,
)
from momentum.core.settings import Settings

SIM_NAMESPACE = uuid.UUID("6f1c9f53-3c43-4c0e-9a7e-0d1a7f5e2b11")


def simulated_principal_header(
    *, email: str, name: str, tenant_id: str, roles: list[str] | None = None
) -> str:
    oid = str(uuid.uuid5(SIM_NAMESPACE, email.lower()))
    claims = [
        {"typ": CLAIM_OID, "val": oid},
        {"typ": CLAIM_TID, "val": tenant_id},
        {"typ": "preferred_username", "val": email},
        {"typ": "name", "val": name},
    ] + [{"typ": CLAIM_ROLE, "val": r} for r in roles or []]
    payload = {"auth_typ": "aad", "name_typ": "name", "role_typ": CLAIM_ROLE, "claims": claims}
    return base64.b64encode(json.dumps(payload).encode()).decode()


class EasyAuthSimProvider:
    name = "easyauth-sim"

    def __init__(self, settings: Settings) -> None:
        if settings.env == "production":
            raise RuntimeError("easyauth-sim is not allowed in production")
        self.settings = settings
        self.session = DevSession(settings)
        self._real = EasyAuthProvider(settings, require_app_service=False)

    async def authenticate(self, request: Request) -> Principal | None:
        data = self.session.read(request)
        if not data:
            return None
        header = simulated_principal_header(
            email=data["email"], name=data["name"], tenant_id=self.settings.easyauth_sim_tenant_id
        )
        # Feed the simulated header through the real parser (client-sent X-MS-* are ignored).
        scope = dict(request.scope)
        headers = [
            (k, v) for k, v in request.scope["headers"] if not k.decode().startswith("x-ms-")
        ]
        headers.append((b"x-ms-client-principal", header.encode()))
        scope["headers"] = headers
        return await self._real.authenticate(Request(scope))

    def login_url(self, return_to: str) -> str:
        from urllib.parse import quote

        return f"{self.settings.base_path}/dev/login?return_to={quote(return_to)}"

    def logout_url(self, return_to: str) -> str:
        return self.login_url(return_to)
