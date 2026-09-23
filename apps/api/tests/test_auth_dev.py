from __future__ import annotations

import httpx

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from tests.conftest import seed_users


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, object]:
    users = (await client.get("/api/v1/dev/users")).json()
    user = next(u for u in users if u["email"] == email)
    r = await client.post("/api/v1/dev/login", json={"user_id": user["id"]})
    assert r.status_code == 200, r.text
    return user


async def test_dev_login_then_me(
    client: httpx.AsyncClient, uow: UnitOfWork, settings: Settings
) -> None:
    await seed_users(uow, settings)
    user = await _login(client, "ravi@acme-demo.test")
    r = await client.get("/api/v1/me")
    assert r.status_code == 200
    me = r.json()
    assert me["user"]["id"] == user["id"]
    assert me["user"]["role"] == "member"
    assert me["workspace"]["name"] == "Acme Demo"


async def test_logout_clears_session(
    client: httpx.AsyncClient, uow: UnitOfWork, settings: Settings
) -> None:
    await seed_users(uow, settings)
    await _login(client, "ana@acme-demo.test")
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert r.json()["redirect_url"].startswith("/dev/login")
    client.cookies.clear()
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_mutation_without_csrf_header_is_rejected(
    client: httpx.AsyncClient, uow: UnitOfWork, settings: Settings
) -> None:
    await seed_users(uow, settings)
    users = (await client.get("/api/v1/dev/users")).json()
    r = await client.post(
        "/api/v1/dev/login",
        json={"user_id": users[0]["id"]},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"


async def test_tampered_cookie_is_unauthenticated(client: httpx.AsyncClient) -> None:
    client.cookies.set("momentum_dev_session", "garbage")
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_client_supplied_easyauth_headers_ignored_in_dev(client: httpx.AsyncClient) -> None:
    from momentum.auth.easyauth_sim import simulated_principal_header

    header = simulated_principal_header(email="admin@acme-demo.test", name="Evil", tenant_id="t")
    r = await client.get("/api/v1/me", headers={"X-MS-CLIENT-PRINCIPAL": header})
    assert r.status_code == 401


def test_dev_auth_refuses_production() -> None:
    import pytest

    from momentum.auth.dev import DevAuthProvider
    from tests.conftest import make_settings

    s = make_settings()
    object.__setattr__(s, "env", "production")
    with pytest.raises(RuntimeError):
        DevAuthProvider(s)
