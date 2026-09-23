"""Azure App Service Authentication ("Easy Auth").

App Service authenticates the user and injects ``X-MS-CLIENT-PRINCIPAL*`` headers; it strips
client-supplied copies, so the headers are trustworthy only when running behind App Service.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from starlette.requests import Request

from momentum.auth.base import Principal
from momentum.core.settings import Settings

HEADER = "x-ms-client-principal"
CLAIM_OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"
CLAIM_TID = "http://schemas.microsoft.com/identity/claims/tenantid"
CLAIM_ROLE = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"


class EasyAuthError(ValueError):
    pass


def decode_principal(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise EasyAuthError("malformed X-MS-CLIENT-PRINCIPAL") from exc
    if not isinstance(data, dict):
        raise EasyAuthError("principal is not an object")
    return data


def _claims(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for c in data.get("claims") or []:
        if isinstance(c, dict) and "typ" in c and "val" in c:
            out.append((str(c["typ"]), str(c["val"])))
    return out


def principal_from_payload(
    data: Mapping[str, Any],
    *,
    email_claims: list[str],
    header_id: str | None = None,
    header_name: str | None = None,
    idp: str | None = None,
) -> Principal:
    claims = _claims(data)
    first: dict[str, str] = {}
    for typ, val in claims:
        first.setdefault(typ, val)
    role_typ = str(data.get("role_typ") or CLAIM_ROLE)
    name_typ = str(data.get("name_typ") or "name")
    roles = tuple(val for typ, val in claims if typ in (role_typ, "roles", CLAIM_ROLE))
    oid = first.get(CLAIM_OID) or first.get("oid") or header_id
    if not oid:
        raise EasyAuthError("principal has no object id")
    tid = first.get(CLAIM_TID) or first.get("tid")
    email = next((first[c] for c in email_claims if first.get(c) and "@" in first[c]), None)
    if email is None and header_name and "@" in header_name:
        email = header_name
    name = first.get("name") or first.get(name_typ) or header_name or email
    return Principal(
        provider=f"easyauth-{idp or data.get('auth_typ') or 'aad'}",
        subject=oid,
        tenant_id=tid,
        email=email.lower() if email else None,
        name=name,
        roles=roles,
        raw_claims=first,
    )


def running_on_app_service() -> bool:
    return bool(os.environ.get("WEBSITE_SITE_NAME"))


class EasyAuthProvider:
    name = "easyauth"

    def __init__(self, settings: Settings, *, require_app_service: bool = True) -> None:
        if require_app_service and not (
            running_on_app_service() or settings.easyauth_trust_headers
        ):
            raise RuntimeError(
                "AUTH_MODE=easyauth trusts X-MS-* headers and must run behind Azure App Service "
                "(WEBSITE_SITE_NAME not set). Set MOMENTUM_EASYAUTH_TRUST_HEADERS=true only behind "
                "a trusted proxy."
            )
        self.settings = settings

    async def authenticate(self, request: Request) -> Principal | None:
        raw = request.headers.get(HEADER)
        if not raw:
            return None
        return principal_from_payload(
            decode_principal(raw),
            email_claims=self.settings.email_claims,
            header_id=request.headers.get("x-ms-client-principal-id"),
            header_name=request.headers.get("x-ms-client-principal-name"),
            idp=request.headers.get("x-ms-client-principal-idp"),
        )

    def login_url(self, return_to: str) -> str:
        return f"/.auth/login/aad?post_login_redirect_uri={quote(return_to)}"

    def logout_url(self, return_to: str) -> str:
        return f"/.auth/logout?post_logout_redirect_uri={quote(return_to)}"
