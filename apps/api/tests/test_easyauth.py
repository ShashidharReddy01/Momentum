from __future__ import annotations

import base64
import json

import httpx
import pytest

from momentum.auth.easyauth import (
    CLAIM_OID,
    CLAIM_ROLE,
    CLAIM_TID,
    EasyAuthError,
    EasyAuthProvider,
    decode_principal,
    principal_from_payload,
)
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from tests.conftest import AppFactory, make_settings, seed_users

EMAIL_CLAIMS = make_settings().email_claims


def encode(payload: dict[str, object]) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_parses_standard_entra_principal() -> None:
    payload = {
        "auth_typ": "aad",
        "name_typ": "name",
        "role_typ": CLAIM_ROLE,
        "claims": [
            {"typ": CLAIM_OID, "val": "oid-1"},
            {"typ": CLAIM_TID, "val": "tenant-1"},
            {"typ": "preferred_username", "val": "Ravi@Acme-Demo.test"},
            {"typ": "name", "val": "Ravi Kumar"},
            {"typ": CLAIM_ROLE, "val": "Momentum.Admin"},
        ],
    }
    p = principal_from_payload(decode_principal(encode(payload)), email_claims=EMAIL_CLAIMS)
    assert p.provider == "easyauth-aad"
    assert (p.subject, p.tenant_id, p.email, p.name) == (
        "oid-1",
        "tenant-1",
        "ravi@acme-demo.test",
        "Ravi Kumar",
    )
    assert p.roles == ("Momentum.Admin",)


def test_email_falls_back_to_other_claims_and_header() -> None:
    payload = {"claims": [{"typ": "oid", "val": "x"}, {"typ": "upn", "val": "a@b.test"}]}
    assert principal_from_payload(payload, email_claims=EMAIL_CLAIMS).email == "a@b.test"
    payload2 = {"claims": [{"typ": "oid", "val": "x"}]}
    p2 = principal_from_payload(payload2, email_claims=EMAIL_CLAIMS, header_name="z@b.test")
    assert p2.email == "z@b.test"


def test_short_role_claim_and_missing_oid() -> None:
    payload = {"claims": [{"typ": "oid", "val": "x"}, {"typ": "roles", "val": "R1"}]}
    assert principal_from_payload(payload, email_claims=EMAIL_CLAIMS).roles == ("R1",)
    with pytest.raises(EasyAuthError):
        principal_from_payload({"claims": []}, email_claims=EMAIL_CLAIMS)


def test_malformed_header() -> None:
    with pytest.raises(EasyAuthError):
        decode_principal("%%%not-base64")


def test_easyauth_refuses_to_run_outside_app_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    with pytest.raises(RuntimeError, match="App Service"):
        EasyAuthProvider(make_settings(auth_mode="easyauth"))
    monkeypatch.setenv("WEBSITE_SITE_NAME", "momentum-prod")
    EasyAuthProvider(make_settings(auth_mode="easyauth"))


async def test_easyauth_request_flow(
    app_factory: AppFactory, uow: UnitOfWork, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEBSITE_SITE_NAME", "momentum-test")
    await seed_users(uow, settings)
    app = app_factory(auth_mode="easyauth")
    header = encode(
        {
            "claims": [
                {"typ": CLAIM_OID, "val": "oid-ravi"},
                {"typ": CLAIM_TID, "val": "tenant-A"},
                {"typ": "preferred_username", "val": "ravi@acme-demo.test"},
                {"typ": "name", "val": "Ravi Kumar"},
            ]
        }
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        r = await c.get("/api/v1/me", headers={"X-MS-CLIENT-PRINCIPAL": header})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["email"] == "ravi@acme-demo.test"
        anon = await c.get("/api/v1/me")
        assert anon.status_code == 401
        assert anon.json()["login_url"].startswith("/.auth/login/aad")


async def test_easyauth_sim_flow(
    app_factory: AppFactory, uow: UnitOfWork, settings: Settings
) -> None:
    await seed_users(uow, settings)
    app = app_factory(auth_mode="easyauth-sim")
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"X-Requested-With": "momentum"},
        ) as c,
    ):
        users = (await c.get("/api/v1/dev/users")).json()
        ana = next(u for u in users if u["email"] == "ana@acme-demo.test")
        await c.post("/api/v1/dev/login", json={"user_id": ana["id"]})
        me = (await c.get("/api/v1/me")).json()
        assert me["user"]["id"] == ana["id"]
