"""Momentum must mount inside a host app and live in any schema (ADR-0006)."""

from __future__ import annotations

import httpx
import sqlalchemy as sa
from fastapi import FastAPI, Request

from momentum.app import momentum_lifespan, mount_momentum
from momentum.auth.base import Principal
from momentum.migrations_runner import upgrade_head
from tests.conftest import make_settings


async def test_mount_under_base_path_with_host_auth() -> None:
    host = FastAPI()

    @host.get("/host-ping")
    async def ping() -> dict[str, str]:
        return {"host": "ok"}

    async def resolve(request: Request) -> Principal | None:
        email = request.headers.get("x-host-user")
        return (
            Principal(provider="host", subject=email, email=email, name="Host User")
            if email
            else None
        )

    sub = mount_momentum(
        host,
        settings=make_settings(base_path="/momentum", auth_mode="host"),
        resolve_principal=resolve,
    )
    async with (
        momentum_lifespan(sub),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url="http://h") as c,
    ):
        assert (await c.get("/host-ping")).json() == {"host": "ok"}
        cfg = (await c.get("/momentum/api/v1/config")).json()
        assert cfg["api_base"] == "/momentum/api/v1"
        r = await c.get("/momentum/api/v1/me", headers={"x-host-user": "host@acme-demo.test"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["email"] == "host@acme-demo.test"
        assert (await c.get("/momentum/api/v1/me")).status_code == 401


def test_migrations_in_alternate_schema_leave_public_untouched() -> None:
    s = make_settings(db_schema="momentum_portability")
    eng = sa.create_engine(s.database_url)
    with eng.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS momentum_portability CASCADE"))
        before = conn.execute(
            sa.text("select count(*) from pg_tables where schemaname='public'")
        ).scalar()
    upgrade_head(s)
    with eng.begin() as conn:
        n = conn.execute(
            sa.text("select count(*) from pg_tables where schemaname='momentum_portability'")
        ).scalar()
        after = conn.execute(
            sa.text("select count(*) from pg_tables where schemaname='public'")
        ).scalar()
        conn.execute(sa.text("DROP SCHEMA momentum_portability CASCADE"))
    eng.dispose()
    assert n and n >= 10
    assert before == after
