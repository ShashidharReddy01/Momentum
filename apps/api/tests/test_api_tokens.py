"""S5.1.6 (ADR-0009): API tokens for scripts: created in the app, shown once, hashed at rest,
scoped, expiring, revocable, never logged; admins can issue one that acts as an agent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import ApiToken
from momentum.domain.users.tokens import hash_token
from tests.helpers import Clients

BASE = "/api/v1"


def bearer(clients: Clients, secret: str) -> httpx.AsyncClient:
    """A script: no session cookie, no CSRF header, just the token."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=clients.app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {secret}"},
    )


async def _token(c: httpx.AsyncClient, scopes: list[str], **body: Any) -> dict[str, Any]:
    r = await c.post(f"{BASE}/me/tokens", json={"name": "script", "scopes": scopes, **body})
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == name
    )


async def test_a_token_is_shown_once_and_stored_hashed(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    created = await _token(ravi, ["read"])
    secret = created["secret"]
    assert secret.startswith("mtm_") and len(secret) > 40
    assert created["data"]["prefix"] == secret[:10]
    listed = (await ravi.get(f"{BASE}/me/tokens")).json()["data"]
    assert [t["name"] for t in listed] == ["script"] and "secret" not in listed[0]
    async with uow.transaction() as s:
        row = (await s.execute(select(ApiToken))).scalar_one()
    assert row.token_hash == hash_token(secret) and secret not in str(row.__dict__)
    assert row.expires_at is not None and row.expires_at - datetime.now(UTC) > timedelta(days=89)
    async with bearer(as_user, secret) as script:
        me = (await script.get(f"{BASE}/me")).json()
    assert me["user"]["email"] == "ravi@acme-demo.test"


async def test_scopes_narrow_what_a_token_can_do(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    read_only = (await _token(ravi, ["read"]))["secret"]
    writer = (await _token(ravi, ["tasks:write"]))["secret"]
    async with bearer(as_user, read_only) as script:
        r = await script.post(f"{BASE}/projects/{pid}/tasks", json={"title": "From a script"})
        assert r.status_code == 403 and r.json()["code"] == "token_scope"
        assert (await script.get(f"{BASE}/projects/{pid}")).status_code == 200
    async with bearer(as_user, writer) as script:  # no CSRF header needed with a bearer token
        r = await script.post(f"{BASE}/projects/{pid}/tasks", json={"title": "From a script"})
        assert r.status_code == 201, r.text
        # tokens don't make tokens, and a tasks:write token can't do admin things
        r = await script.post(f"{BASE}/me/tokens", json={"name": "x", "scopes": ["read"]})
        assert r.status_code == 403
    async with uow.transaction() as s:
        task = (await s.execute(select(Task).where(Task.title == "From a script"))).scalar_one()
    assert task.created_via == "api"


async def test_revoked_expired_or_bad_tokens_are_refused(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    t = await _token(ravi, ["read"])
    async with bearer(as_user, t["secret"]) as script:
        assert (await script.get(f"{BASE}/me")).status_code == 200
        r = await ravi.delete(f"{BASE}/me/tokens/{t['data']['id']}")
        assert r.status_code == 200
        assert (await script.get(f"{BASE}/me")).status_code == 401
    t2 = await _token(ravi, ["read"], expires_in_days=1)
    async with uow.transaction() as s:
        row = await s.get(ApiToken, t2["data"]["id"])
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    async with bearer(as_user, t2["secret"]) as script:
        assert (await script.get(f"{BASE}/me")).status_code == 401
    async with bearer(as_user, "mtm_not-a-real-token") as script:
        assert (await script.get(f"{BASE}/me")).status_code == 401
    # a bad bearer token never falls back to the session cookie
    ravi.headers["Authorization"] = "Bearer mtm_wrong"
    try:
        assert (await ravi.get(f"{BASE}/me")).status_code == 401
    finally:
        del ravi.headers["Authorization"]
    # validation
    for body in (
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["root"]},
        {"name": "x", "scopes": ["read"], "expires_in_days": 400},
        {"name": "x", "scopes": ["admin"]},  # ravi isn't an admin
    ):
        assert (await ravi.post(f"{BASE}/me/tokens", json=body)).status_code == 422, body


async def test_an_admin_can_issue_a_token_that_acts_as_an_agent(
    as_user: Clients, uow: UnitOfWork
) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    await admin.post(f"{BASE}/agents/install", json={"keys": ["teammate"]})
    teammate = next(
        a for a in (await admin.get(f"{BASE}/agents")).json()["data"] if a["key"] == "teammate"
    )
    body = {"name": "ERP sync", "scopes": ["read", "tasks:write"]}
    assert (await ravi.post(f"{BASE}/agents/{teammate['id']}/tokens", json=body)).status_code == 403
    r = await admin.post(f"{BASE}/agents/{teammate['id']}/tokens", json=body)
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    listed = (await admin.get(f"{BASE}/agents/{teammate['id']}/tokens")).json()["data"]
    assert [t["name"] for t in listed] == ["ERP sync"]
    pid = await _project(ravi)
    async with bearer(as_user, secret) as script:
        # the agent sees only projects it was given
        assert (await script.get(f"{BASE}/projects/{pid}")).status_code == 404
        await ravi.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": pid})
        r = await script.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Synced from ERP"})
        assert r.status_code == 201, r.text
        # an agent's token still can't delete (the service guard, not just the scope)
        r = await script.delete(f"{BASE}/tasks/{r.json()['data']['id']}")
        assert r.status_code == 403
    async with uow.transaction() as s:
        task = (await s.execute(select(Task).where(Task.title == "Synced from ERP"))).scalar_one()
        act = (
            (await s.execute(select(Activity).where(Activity.entity_id == task.id)))
            .scalars()
            .first()
        )
    assert str(task.created_by) == teammate["user_id"]  # authored by the agent's account
    assert act is not None and act.actor_kind == "agent"
    # the admin can revoke it
    token_id = listed[0]["id"]
    assert (await admin.delete(f"{BASE}/me/tokens/{token_id}")).status_code == 200
    async with bearer(as_user, secret) as script:
        assert (await script.get(f"{BASE}/me")).status_code == 401


async def test_secrets_never_reach_the_logs(
    as_user: Clients, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    ravi = await as_user("ravi")
    secret = (await _token(ravi, ["read"]))["secret"]
    async with bearer(as_user, secret) as script:
        await script.get(f"{BASE}/me")
        await script.get(f"{BASE}/projects")
    captured = capsys.readouterr()
    logged = captured.out + captured.err + caplog.text
    assert secret not in logged and secret[10:] not in logged
