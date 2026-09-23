"""S2.1.1 realtime end to end: two separate app instances (like two API processes) sharing
one Postgres, wired together only by LISTEN/NOTIFY — the same mechanism used in production.

Uses starlette.testclient.TestClient (sync, its own thread) for the websocket side, run off
the main test coroutine via asyncio.to_thread so it never touches the pytest-asyncio loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient, WebSocketTestSession

from tests.conftest import AppFactory
from tests.helpers import Clients

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


async def in_thread[T](fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


def _login(client: TestClient, user_id: str) -> None:
    client.headers["X-Requested-With"] = "momentum"
    r = client.post("/api/v1/dev/login", json={"user_id": user_id})
    assert r.status_code == 200, r.text


def _user_id(client: TestClient, local: str) -> str:
    users = client.get("/api/v1/dev/users").json()
    return next(u["id"] for u in users if u["email"] == f"{local}@acme-demo.test")


def _drain(
    ws: WebSocketTestSession, *, until: Callable[[dict[str, Any]], bool], timeout: float = 5
) -> dict[str, Any]:
    """Read messages until one satisfies `until` (fails the test if it never arrives)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = ws.receive_json()
        if until(msg):
            return msg
    raise AssertionError("timed out waiting for a matching websocket message")


async def _realtime_app(app_factory: AppFactory) -> FastAPI:
    return app_factory(realtime_enabled=True)


async def test_two_processes_see_a_task_update_within_a_second(
    app_factory: AppFactory, as_user: Clients
) -> None:
    """S2.1.1 AC: two browsers see task title/section/complete changes within 1s."""
    ravi = await as_user("ravi")
    pid = (await ravi.get("/api/v1/projects")).json()["data"][0]["id"]
    task = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Realtime me"})).json()[
        "data"
    ]

    # "browser B": a second, independent app instance (its own Hub, its own LISTEN
    # connection) — this is the multi-process case, not a same-process shortcut.
    watcher_app = await _realtime_app(app_factory)
    subscribed = threading.Event()

    def watch() -> dict[str, Any]:
        with TestClient(watcher_app) as client:
            _login(client, _user_id(client, "ravi"))
            with client.websocket_connect("/ws") as ws:
                hello = ws.receive_json()
                assert hello["type"] == "hello"
                ws.send_json({"op": "subscribe", "channel": f"project:{pid}"})
                sub = _drain(ws, until=lambda m: m["type"] in ("subscribed", "denied"))
                assert sub["type"] == "subscribed"
                subscribed.set()
                return _drain(ws, until=lambda m: m["type"] == "event")

    watch_future = asyncio.ensure_future(in_thread(watch))
    await asyncio.to_thread(subscribed.wait, 5)
    assert subscribed.is_set(), "watcher never finished subscribing"

    t0 = time.monotonic()
    r = await ravi.patch(f"/api/v1/tasks/{task['id']}", json={"title": "Realtime me, updated"})
    assert r.status_code == 200

    event = await asyncio.wait_for(watch_future, timeout=5)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"took {elapsed:.2f}s"
    assert event["event"] == "task.updated"
    assert event["entity_id"] == task["id"]
    assert event["data"]["changes"]["title"] == ["Realtime me", "Realtime me, updated"]


async def test_subscribe_is_permission_checked(app_factory: AppFactory, as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = (await ravi.get("/api/v1/projects")).json()["data"][0]["id"]
    # a private project Tom isn't a member of
    private = (
        await ravi.post(
            "/api/v1/projects",
            json={
                "team_id": (await ravi.get(f"/api/v1/projects/{pid}")).json()["team_id"],
                "name": "Secret",
                "privacy": "private",
            },
        )
    ).json()["data"]
    app = await _realtime_app(app_factory)

    def run() -> list[dict[str, Any]]:
        with TestClient(app) as client:
            _login(client, _user_id(client, "tom"))
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()  # hello
                ws.send_json({"op": "subscribe", "channel": f"project:{private['id']}"})
                denied = _drain(ws, until=lambda m: m["type"] == "denied")
                ws.send_json({"op": "subscribe", "channel": "user:not-my-id"})
                denied2 = _drain(ws, until=lambda m: m["type"] == "denied")
                own = _user_id(client, "tom")
                ws.send_json({"op": "subscribe", "channel": f"user:{own}"})
                ok = _drain(ws, until=lambda m: m["type"] in ("subscribed", "denied"))
                return [denied, denied2, ok]

    denied, denied2, ok = await in_thread(run)
    assert denied["reason"] in ("not_found", "forbidden")
    assert denied2["reason"] == "invalid_channel"
    assert ok["type"] == "subscribed"


async def test_unauthenticated_connection_is_closed(app_factory: AppFactory) -> None:
    app = await _realtime_app(app_factory)

    def run() -> int:
        with (
            TestClient(app) as client,
            pytest.raises(Exception) as exc_info,
            client.websocket_connect("/ws"),
        ):
            pass
        _ = client
        return getattr(exc_info.value, "code", 0)

    code = await in_thread(run)
    assert code == 4401


async def test_replay_delivers_backlog_in_order_on_reconnect(
    app_factory: AppFactory, as_user: Clients
) -> None:
    ravi = await as_user("ravi")
    pid = (await ravi.get("/api/v1/projects")).json()["data"][0]["id"]
    t1 = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "One"})).json()["data"]
    t2 = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Two"})).json()["data"]
    app = await _realtime_app(app_factory)

    def first_subscribe() -> None:
        with TestClient(app) as client:
            _login(client, _user_id(client, "ravi"))
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                ws.send_json({"op": "subscribe", "channel": f"project:{pid}"})
                sub = _drain(ws, until=lambda m: m["type"] == "subscribed")
                assert sub["channel"] == f"project:{pid}"

    await in_thread(first_subscribe)

    # more happens while "disconnected" — no TestClient/lifespan is running for `app` right
    # now, so nothing is live-dispatching; this is only ever recoverable via replay
    r = await ravi.patch(f"/api/v1/tasks/{t1['id']}", json={"title": "One (renamed)"})
    assert r.status_code == 200
    r2 = await ravi.post(f"/api/v1/tasks/{t2['id']}/complete")
    assert r2.status_code == 200

    def reconnect_from_zero() -> list[dict[str, Any]]:
        with TestClient(app) as client:
            _login(client, _user_id(client, "ravi"))
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                ws.send_json({"op": "subscribe", "channel": f"project:{pid}", "since": 0})
                events: list[dict[str, Any]] = []
                while True:
                    msg = ws.receive_json()
                    if msg["type"] == "event":
                        events.append(msg)
                    elif msg["type"] == "subscribed":
                        break
                    elif msg["type"] == "resync":
                        pytest.fail("backlog unexpectedly too large to replay")
                return events

    events = await in_thread(reconnect_from_zero)
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)  # oldest first
    renamed = [e for e in events if e["entity_id"] == t1["id"] and e["event"] == "task.updated"]
    assert renamed and renamed[-1]["data"]["changes"]["title"][1] == "One (renamed)"
    completed = [e for e in events if e["entity_id"] == t2["id"] and e["event"] == "task.completed"]
    assert completed
