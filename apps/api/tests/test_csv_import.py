"""S2.7.2 CSV import: preview (headers + sample rows), column mapping, section-from-a-column,
assignee-by-email, due dates, completed flag, and permissions."""

from __future__ import annotations

import json

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _users(c) -> dict:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get("/api/v1/users")).json()["data"]
    }


CSV = (
    "Title,Section,Assignee,Due,Done\n"
    "Write the brief,Planning,ravi@acme-demo.test,2026-03-01,\n"
    "Ship v1,Execution,,2026-04-01,yes\n"
    ",Untitled row,,,\n"  # a missing title is skipped, not created
)


async def _preview(c, pid: str, content: str = CSV):  # type: ignore[no-untyped-def]
    return await c.post(
        f"/api/v1/projects/{pid}/import/csv/preview",
        files={"file": ("tasks.csv", content, "text/csv")},
    )


async def _commit(c, pid: str, mapping: dict, content: str = CSV):  # type: ignore[no-untyped-def, type-arg]
    return await c.post(
        f"/api/v1/projects/{pid}/import/csv",
        files={"file": ("tasks.csv", content, "text/csv")},
        data={"mapping": json.dumps(mapping)},
    )


async def test_preview_returns_headers_and_sample_rows(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await _preview(ravi, pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["headers"] == ["Title", "Section", "Assignee", "Due", "Done"]
    assert body["row_count"] == 3  # including the blank trailing row
    assert body["rows"][0][0] == "Write the brief"


async def test_commit_creates_tasks_with_sections_assignee_and_due_dates(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = await _users(ravi)

    r = await _commit(
        ravi,
        pid,
        {
            "title_col": "Title",
            "section_col": "Section",
            "assignee_email_col": "Assignee",
            "due_on_col": "Due",
            "completed_col": "Done",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["skipped"] == 1  # the blank row

    tasks = (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    brief = next(t for t in tasks if t["title"] == "Write the brief")
    assert brief["assignee_id"] == users["ravi"]
    assert brief["due_on"] == "2026-03-01"
    assert brief["completed_at"] is None
    completed_tasks = (
        await ravi.get(f"/api/v1/projects/{pid}/tasks", params={"completed": "true"})
    ).json()["data"]
    shipped = next(t for t in completed_tasks if t["title"] == "Ship v1")
    assert shipped["completed_at"] is not None

    sections = {
        s["name"] for s in (await ravi.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    }
    assert {"Planning", "Execution"} <= sections


async def test_unknown_email_and_bad_date_are_reported_but_dont_block_the_row(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    content = "Title,Assignee,Due\nDo the thing,nobody@example.com,not-a-date\n"
    r = await _commit(
        ravi,
        pid,
        {"title_col": "Title", "assignee_email_col": "Assignee", "due_on_col": "Due"},
        content,
    )
    body = r.json()
    assert body["created"] == 1
    assert any("nobody@example.com" in e for e in body["errors"])
    assert any("not-a-date" in e for e in body["errors"])
    task = next(
        t
        for t in (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
        if t["title"] == "Do the thing"
    )
    assert task["assignee_id"] is None
    assert task["due_on"] is None


async def test_non_member_cannot_import(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    kim = await as_user("kim")  # not on the Product team
    r = await _commit(kim, pid, {"title_col": "Title"})
    assert r.status_code in (403, 404)
    _ = ravi
