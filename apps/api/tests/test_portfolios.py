"""S6.2.2 Portfolios: create/rename/delete with undo, add/remove projects (only ones you can see),
rows computed as the viewer (invisible projects only counted), owner/admin editing, portfolio
status updates (post, undo, code-built draft), the ✦ one-liners and Mo's get_portfolio."""

from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import Clients


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _portfolio(c: httpx.AsyncClient, name: str = "Launch programme") -> dict[str, Any]:
    r = await c.post("/api/v1/portfolios", json={"name": name, "description": "Q4 launches"})
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _add(c: httpx.AsyncClient, pf: str, project: str) -> httpx.Response:
    return await c.post(f"/api/v1/portfolios/{pf}/projects", json={"project_id": project})


async def test_create_add_remove_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    web = await _project(ravi)
    pf = await _portfolio(ravi)
    assert pf["can_edit"] and pf["projects"] == []

    r = await _add(ravi, pf["id"], web)
    assert r.status_code == 201, r.text
    (row,) = r.json()["data"]["projects"]
    assert row["name"] == "Website Revamp" and "total_tasks" in row
    assert (await _add(ravi, pf["id"], web)).status_code == 409

    undo = await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).json()["projects"] == []

    await _add(ravi, pf["id"], web)
    r = await ravi.delete(f"/api/v1/portfolios/{pf['id']}/projects/{web}")
    assert r.status_code == 200 and r.json()["data"]["projects"] == []
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert len((await ravi.get(f"/api/v1/portfolios/{pf['id']}")).json()["projects"]) == 1

    r = await ravi.patch(f"/api/v1/portfolios/{pf['id']}", json={"name": "Launches"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "Launches"
    r = await ravi.delete(f"/api/v1/portfolios/{pf['id']}")
    assert r.status_code == 200
    assert (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).status_code == 404
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).status_code == 200


async def test_rows_are_computed_as_the_viewer(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    web = await _project(ravi)
    private = await _project(ravi, "Mobile App v2")  # mei isn't a member
    pf = await _portfolio(ravi)
    await _add(ravi, pf["id"], web)
    await _add(ravi, pf["id"], private)

    mine = (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).json()
    assert {p["name"] for p in mine["projects"]} == {"Website Revamp", "Mobile App v2"}

    hers = (await mei.get(f"/api/v1/portfolios/{pf['id']}")).json()
    assert [p["name"] for p in hers["projects"]] == ["Website Revamp"]
    assert hers["hidden_projects"] == 1 and not hers["can_edit"]
    assert "Mobile App v2" not in str(hers)
    listed = next(
        p for p in (await mei.get("/api/v1/portfolios")).json()["data"] if p["id"] == pf["id"]
    )
    assert listed["project_count"] == 1


async def test_only_the_owner_or_an_admin_edits(as_user: Clients) -> None:
    ravi, mei, admin = await as_user("ravi"), await as_user("mei"), await as_user("admin")
    pf = await _portfolio(ravi)
    web = await _project(ravi)
    assert (
        await mei.patch(f"/api/v1/portfolios/{pf['id']}", json={"name": "Mine now"})
    ).status_code == 403
    assert (await _add(mei, pf["id"], web)).status_code == 403
    assert (
        await admin.patch(f"/api/v1/portfolios/{pf['id']}", json={"name": "Admin fix"})
    ).status_code == 200
    # you can only add a project you can see
    private = await _project(ravi, "Mobile App v2")
    mei_pf = await _portfolio(mei, "Mei's")
    assert (await _add(mei, mei_pf["id"], private)).status_code == 404


async def test_status_updates_and_the_code_built_draft(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    web = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    pf = await _portfolio(ravi)
    await _add(ravi, pf["id"], web)
    await _add(ravi, pf["id"], other)
    r = await ravi.post(
        f"/api/v1/projects/{web}/status-updates",
        json={"status": "at_risk", "title": "Vendor contract is late"},
    )
    assert r.status_code == 201, r.text

    draft = (await ravi.get(f"/api/v1/portfolios/{pf['id']}/status-draft")).json()["draft"]
    assert draft["status"] == "at_risk"  # the least healthy project's
    assert draft["title"] == "1 at risk, 1 with no status yet"
    assert draft["sections"]["slipped"] == [
        {"text": "Website Revamp is at risk: Vendor contract is late"}
    ]

    posted = await ravi.post(f"/api/v1/portfolios/{pf['id']}/status-updates", json=draft)
    assert posted.status_code == 201, posted.text
    assert (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).json()["status"] == "at_risk"
    history = (await ravi.get(f"/api/v1/portfolios/{pf['id']}/status-updates")).json()["data"]
    assert [u["title"] for u in history] == [draft["title"]]
    await ravi.post("/api/v1/undo", json={"activity_id": posted.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/portfolios/{pf['id']}")).json()["status"] is None
    mei = await as_user("mei")
    assert (
        await mei.post(f"/api/v1/portfolios/{pf['id']}/status-updates", json=draft)
    ).status_code == 403


async def test_one_liners_keep_only_grounded_text(as_user: Clients) -> None:
    """Mock mode: the fixture's lines carry no numbers, so they're kept and marked AI; every
    visible project gets a line, in table order."""
    ravi = await as_user("ravi")
    pf = await _portfolio(ravi)
    for name in ("Website Revamp", "Mobile App v2"):
        await _add(ravi, pf["id"], await _project(ravi, name))
    r = await ravi.post(f"/api/v1/ai/portfolios/{pf['id']}/lines")
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert len(lines) == 2 and all(line["ai"] for line in lines)


def test_a_line_with_an_invented_number_falls_back_to_the_facts() -> None:
    import uuid
    from datetime import date

    from momentum.ai.portfolio_lines import ProjectFacts, _grounded

    p = ProjectFacts(uuid.uuid4(), "Web", "at_risk", 20, 8, 2, date(2026, 12, 15), None)
    facts = p.facts(date(2026, 10, 1))
    assert _grounded("40% done; 2 overdue", facts)
    assert not _grounded("90% done, ships in 3 days", facts)
    assert (
        p.sentence(date(2026, 10, 1))
        == "40% done (8 of 20); 2 overdue; due 2026-12-15, 75 days left"
    )
