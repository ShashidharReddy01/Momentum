"""Phase 7.5 S75-11: "Catch me up" (spec §9.1). Visits are written at most once per 5 minutes;
the catch-up counts what other people changed since the last visit, as the person (private work
never shows), with no model call when nothing changed; the window is capped at 30 days (7 with no
visit); Home's card shows only past 3 changes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from momentum.ai.tools.write_tools import text_doc
from tests.helpers import Clients

B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    people = (await c.get(f"{B}/users", params={"q": local})).json()["data"]
    return str(next(u["id"] for u in people if u["email"].startswith(f"{local}@")))


async def _task(c: httpx.AsyncClient, pid: str, title: str) -> dict[str, Any]:
    r = await c.post(f"{B}/projects/{pid}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return dict(r.json()["data"])


async def _catch_up(c: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await c.post(f"{B}/ai/catch-up", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_visits_are_debounced_and_checked(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    first = await ravi.put(f"{B}/visits", json={"scope": "project", "scope_id": pid})
    assert first.status_code == 200, first.text
    again = await ravi.put(f"{B}/visits", json={"scope": "project", "scope_id": pid})
    assert again.json()["last_seen_at"] == first.json()["last_seen_at"]  # within 5 minutes
    assert (await ravi.put(f"{B}/visits", json={"scope": "home"})).status_code == 200
    bad = await ravi.put(f"{B}/visits", json={"scope": "home", "scope_id": pid})
    assert bad.status_code == 422
    missing = await ravi.put(
        f"{B}/visits", json={"scope": "project", "scope_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 404


async def test_what_others_changed_since_my_visit_with_no_call_when_nothing_did(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "Draft the hero copy")
    b = await _task(ravi, pid, "Audit the footer links")
    c = await _task(ravi, pid, "Pick the launch font")
    await ravi.put(f"{B}/visits", json={"scope": "project", "scope_id": pid})

    quiet = await _catch_up(ravi, scope="project", scope_id=pid)
    assert quiet["nothing_changed"] is True and quiet["ai"] is False and quiet["lines"] == []

    # my own changes are not news
    await ravi.post(f"{B}/tasks/{a['id']}/complete")
    assert (await _catch_up(ravi, scope="project", scope_id=pid))["nothing_changed"] is True

    me = await _user_id(ravi, "ravi")
    assert (await ana.post(f"{B}/tasks/{b['id']}/complete")).status_code == 200
    r = await ana.patch(f"{B}/tasks/{c['id']}", json={"assignee_id": me})
    assert r.status_code == 200, r.text
    doc = text_doc("Can you check this one")
    doc["content"][0]["content"].append(
        {"type": "mention", "attrs": {"kind": "user", "id": me, "label": "Ravi"}}
    )
    assert (await ana.post(f"{B}/tasks/{a['id']}/comments", json={"body": doc})).status_code == 201

    out = await _catch_up(ravi, scope="project", scope_id=pid)
    assert out["ai"] is True and out["nothing_changed"] is False
    assert out["counts"] == {"completed": 1, "reassigned_to_me": 1, "mentions": 1}
    assert out["total"] == 3
    assert len(out["lines"]) == 2  # the invented number and the uncited line were dropped
    assert all(line["cites"] for line in out["lines"])
    assert "987654" not in str(out)
    keys = {k for line in out["lines"] for k in line["cites"]}
    assert keys & {b["key"], c["key"], a["key"]}
    assert any(line["task_ids"] for line in out["lines"])

    # someone who can't see the project can't ask about it
    tom = await as_user("tom")
    assert (
        await tom.post(f"{B}/ai/catch-up", json={"scope": "project", "scope_id": pid})
    ).status_code in (403, 404)


async def test_private_work_never_shows_and_the_window_is_capped(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    priya = await as_user("priya")
    team = next(
        t["id"] for t in (await priya.get(f"{B}/teams")).json()["data"] if t["name"] == "Product"
    )
    secret = await priya.post(
        f"{B}/projects", json={"team_id": team, "name": "Quiet Acquisition", "privacy": "private"}
    )
    assert secret.status_code == 201, secret.text
    await _task(priya, secret.json()["data"]["id"], "Call the Zenith board")
    await ravi.put(f"{B}/visits", json={"scope": "home"})
    home = await _catch_up(ravi, scope="home")
    assert "Zenith" not in str(home) and "Quiet Acquisition" not in str(home)
    assert home["nothing_changed"] is True

    # asking from 60 days back is capped at 30
    long_ago = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    capped = await _catch_up(ravi, scope="home", since=long_ago)
    since = datetime.fromisoformat(capped["since"])
    assert since >= datetime.now(UTC) - timedelta(days=30, minutes=1)

    # with no visit yet, the window is 7 days
    lena = await as_user("lena")
    pending = (await lena.get(f"{B}/ai/catch-up/pending", params={"scope": "home"})).json()
    first = datetime.fromisoformat(pending["since"])
    assert abs((datetime.now(UTC) - first) - timedelta(days=7)) < timedelta(minutes=1)


async def test_home_card_shows_past_three_changes(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    tasks = [await _task(ravi, pid, f"Card check {i}") for i in range(4)]
    await ravi.put(f"{B}/visits", json={"scope": "home"})
    url = f"{B}/ai/catch-up/pending"
    assert (await ravi.get(url, params={"scope": "home"})).json()["show_card"] is False
    for t in tasks:
        await ana.post(f"{B}/tasks/{t['id']}/complete")
    p = (await ravi.get(url, params={"scope": "home"})).json()
    assert p["total"] == 4 and p["counts"] == {"completed": 4} and p["show_card"] is True
