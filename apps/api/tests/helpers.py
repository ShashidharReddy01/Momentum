"""Shared test helpers: logged-in clients per seeded user, contexts, and API shortcuts."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace


async def user_by_local(uow: UnitOfWork, local: str) -> User:
    async with uow.transaction() as s:
        return (
            await s.execute(select(User).where(User.email == f"{local}@acme-demo.test"))
        ).scalar_one()


async def ctx_for(uow: UnitOfWork, settings: Settings, local: str) -> Ctx:
    u = await user_by_local(uow, local)
    async with uow.transaction() as s:
        ws = await ensure_default_workspace(s, settings)
    return Ctx(
        actor=Actor(id=u.id, workspace_id=ws.id, role=u.role, email=u.email, name=u.name),
        settings=settings,
    )


class Clients:
    """Lazily creates one authenticated httpx client per seeded user (dev login)."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._users: list[dict[str, Any]] | None = None

    async def __call__(self, local: str) -> httpx.AsyncClient:
        if local in self._clients:
            return self._clients[local]
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
            headers={"X-Requested-With": "momentum"},
        )
        if self._users is None:
            self._users = (await c.get("/api/v1/dev/users")).json()
        user = next(u for u in self._users if u["email"] == f"{local}@acme-demo.test")
        r = await c.post("/api/v1/dev/login", json={"user_id": user["id"]})
        assert r.status_code == 200, r.text
        self._clients[local] = c
        return c

    async def close(self) -> None:
        for c in self._clients.values():
            await c.aclose()


def uid(value: Any) -> uuid.UUID:
    return uuid.UUID(str(value))
