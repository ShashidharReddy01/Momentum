"""S2.6.2 Global search: tasks (tsvector + trigram), projects, people, comments, filters, and
the visibility AC (permission-filtered in SQL, not in Python)."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _users(c) -> dict:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get("/api/v1/users")).json()["data"]
    }


async def _task(c, pid: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Untitled", **kw})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_finds_a_task_by_title_keyword(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    await _task(ravi, pid, title="Redesign the onboarding flow")

    r = await ravi.get("/api/v1/search", params={"q": "onboarding"})
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()["tasks"]]
    assert "Redesign the onboarding flow" in titles


async def test_finds_a_task_by_trigram_fuzzy_match(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    await _task(ravi, pid, title="Quarterly roadmap review")

    # A near-miss on "roadmap" (not a full-text stem match) should still hit via trigram.
    r = await ravi.get("/api/v1/search", params={"q": "roadmap"})
    titles = [t["title"] for t in r.json()["tasks"]]
    assert "Quarterly roadmap review" in titles


async def test_finds_a_project_by_name(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/search", params={"q": "Website Revamp"})
    names = [p["name"] for p in r.json()["projects"]]
    assert "Website Revamp" in names


async def test_finds_a_person_by_name(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/search", params={"q": "Mei"})
    names = [p["name"] for p in r.json()["people"]]
    assert any("Mei" in n for n in names)


async def test_finds_a_comment_by_body_text(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid, title="Ship the release")
    await ravi.post(
        f"/api/v1/tasks/{t['id']}/comments",
        json={
            "body": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "blocked on the vendor invoice"}],
                    }
                ],
            }
        },
    )
    r = await ravi.get("/api/v1/search", params={"q": "invoice"})
    snippets = [c["snippet"] for c in r.json()["comments"]]
    assert any("invoice" in s for s in snippets)


async def test_private_project_tasks_are_never_returned_to_a_non_member(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    private = await _project(ravi, "Mobile App v2")
    await _task(ravi, private, title="Confidential launch checklist")

    mei = await as_user("mei")  # not a member of Mobile App v2
    r = await mei.get("/api/v1/search", params={"q": "Confidential launch checklist"})
    assert r.json()["tasks"] == []

    # ...but Ravi, who has access, finds it.
    r2 = await ravi.get("/api/v1/search", params={"q": "Confidential launch checklist"})
    assert any(t["title"] == "Confidential launch checklist" for t in r2.json()["tasks"])


async def test_type_filter_restricts_categories(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/search", params={"q": "Website Revamp", "type": "project"})
    body = r.json()
    assert body["projects"]
    assert body["tasks"] == []
    assert body["people"] == []
    assert body["comments"] == []


async def test_project_and_assignee_and_completed_filters(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    users = await _users(ravi)
    a = await _task(ravi, pid, title="Filter target alpha")
    b = await _task(ravi, other, title="Filter target alpha")
    await ravi.patch(f"/api/v1/tasks/{a['id']}", json={"assignee_id": users["ravi"]})
    await ravi.post(f"/api/v1/tasks/{b['id']}/complete")

    by_project = (
        await ravi.get("/api/v1/search", params={"q": "Filter target alpha", "project_id": pid})
    ).json()["tasks"]
    assert {t["id"] for t in by_project} == {a["id"]}

    by_assignee = (
        await ravi.get(
            "/api/v1/search", params={"q": "Filter target alpha", "assignee_id": users["ravi"]}
        )
    ).json()["tasks"]
    assert {t["id"] for t in by_assignee} == {a["id"]}

    completed = (
        await ravi.get("/api/v1/search", params={"q": "Filter target alpha", "completed": "true"})
    ).json()["tasks"]
    assert {t["id"] for t in completed} == {b["id"]}


async def test_blank_query_returns_nothing(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/search", params={"q": "   "})
    body = r.json()
    assert body == {"tasks": [], "projects": [], "people": [], "comments": []}
