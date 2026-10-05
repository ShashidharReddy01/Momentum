"""Realtime delivery under load (Phase 7 E7.1, budget: p95 < 1 s from a change to the other tabs).

Run while locustfile.py is loading the server: one scale person edits a task in a project every
two seconds; a few others (and the editor's own second tab) are subscribed to that project's
channel over the websocket. For every edit it records the time from sending the PATCH to each
listener receiving the event, and prints p50/p95/max.

    uvx --with httpx --with websockets python tools/load/realtime_probe.py \
        [--host http://localhost:8150] [--edits 60]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx
import websockets

H = {"X-Requested-With": "momentum"}


async def login(host: str, user_id: str) -> httpx.AsyncClient:
    c = httpx.AsyncClient(base_url=host, timeout=30)
    r = await c.post("/api/v1/dev/login", json={"user_id": user_id}, headers=H)
    r.raise_for_status()
    return c


async def listen(
    host: str, c: httpx.AsyncClient, channel: str, seen: dict[str, list[float]], ready: asyncio.Event
) -> None:
    url = host.replace("http", "ws", 1) + "/ws"
    cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    async with websockets.connect(url, additional_headers={"Cookie": cookie}) as ws:
        await ws.send(json.dumps({"op": "subscribe", "channel": channel}))
        ready.set()
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"op": "pong"}))
            elif msg.get("type") == "denied":
                raise SystemExit(f"denied {channel}: {msg}")
            elif msg.get("type") == "event" and msg.get("request_id"):
                seen.setdefault(msg["request_id"], []).append(time.perf_counter())
            elif msg.get("type") not in ("hello", "event", "subscribed"):
                print("listener got", msg)
        print(f"listener closed: {ws.close_code} {ws.close_reason}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:8150")
    ap.add_argument("--edits", type=int, default=60)
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.host, timeout=30) as anon:
        people = [
            u for u in (await anon.get("/api/v1/dev/users")).json() if u["email"].startswith("scale-")
        ]
    writer = await login(a.host, people[8]["id"])
    projects = (await writer.get("/api/v1/projects")).json()["data"]
    project = next(p for p in projects if p.get("privacy") != "private")
    tasks = (await writer.get(f"/api/v1/projects/{project['id']}/tasks")).json()["data"]
    channel = f"project:{project['id']}"
    # the editor's own second tab, plus teammates who can see the project
    listeners = [await login(a.host, people[8]["id"])]
    for p in people[16:]:
        if len(listeners) == 5:
            break
        c = await login(a.host, p["id"])
        if (await c.get(f"/api/v1/projects/{project['id']}")).status_code == 200:
            listeners.append(c)
    seen: dict[str, list[float]] = {}
    readies = [asyncio.Event() for _ in listeners]
    runs = [
        asyncio.create_task(listen(a.host, c, channel, seen, r))
        for c, r in zip(listeners, readies, strict=True)
    ]
    await asyncio.gather(*(r.wait() for r in readies))
    await asyncio.sleep(1)
    sent: dict[str, float] = {}
    for i in range(a.edits):
        t = tasks[i % len(tasks)]
        rid = f"rt-probe-{i}-{time.time_ns()}"
        sent[rid] = time.perf_counter()
        r = await writer.patch(
            f"/api/v1/tasks/{t['id']}",
            json={"estimate_minutes": 30 + (time.time_ns() // 1_000_000) % 9000},  # a change: an event
            headers={**H, "X-Request-ID": rid},
        )
        if r.status_code != 200:
            print("edit failed", r.status_code, r.text[:200])
        await asyncio.sleep(2)
    await asyncio.sleep(3)
    for run in runs:
        run.cancel()
    delays = [(t - sent[rid]) * 1000 for rid, ts in seen.items() if rid in sent for t in ts]
    expected = len(sent) * len(listeners)
    print(f"{len(listeners)} listeners, {len(sent)} edits: {len(delays)}/{expected} deliveries")
    if delays:
        q = statistics.quantiles(delays, n=20)
        print(
            f"change -> other tab: p50 {statistics.median(delays):.0f} ms, "
            f"p95 {q[18]:.0f} ms, max {max(delays):.0f} ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
