"""Phase 7.5 S75-01: a project's Files (spec §3): uploads straight to a project, the inventory
across project, tasks at any depth and comments, versions (add, undo, delete promotes the previous
one), permissions (viewer, editor, guest, outsider) and the files group in search."""

from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import Clients

B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _task(c: httpx.AsyncClient, pid: str, title: str = "T") -> dict[str, Any]:
    sec = (await c.get(f"{B}/projects/{pid}/sections")).json()["data"][0]["id"]
    r = await c.post(f"{B}/projects/{pid}/tasks", json={"title": title, "section_id": sec})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _upload(
    c: httpx.AsyncClient, url: str, name: str = "notes.txt", content: bytes = b"hello", **form: str
) -> httpx.Response:
    return await c.post(f"{B}{url}", files={"file": (name, content, "text/plain")}, data=form)


async def _files(c: httpx.AsyncClient, pid: str, **params: str) -> dict[str, Any]:
    r = await c.get(f"{B}/projects/{pid}/files", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _comment_body(text: str) -> dict[str, Any]:
    return {
        "body": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
    }


async def test_inventory_lists_every_visible_file_once(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    task = await _task(ravi, pid, "Kickoff")
    sub = (await ravi.post(f"{B}/tasks/{task['id']}/subtasks", json={"title": "Deep"})).json()[
        "data"
    ]
    subsub = (await ravi.post(f"{B}/tasks/{sub['id']}/subtasks", json={"title": "Deeper"})).json()[
        "data"
    ]
    comment = (
        await ravi.post(f"{B}/tasks/{task['id']}/comments", json=_comment_body("hi"))
    ).json()["data"]

    p = await _upload(ravi, f"/projects/{pid}/files", "plan.docx", b"PK project")
    assert p.status_code == 201, p.text
    assert p.json()["data"]["project_id"] == pid
    await _upload(ravi, f"/tasks/{task['id']}/attachments", "task.csv", b"a,b\n1,2")
    await _upload(ravi, f"/tasks/{subsub['id']}/attachments", "deep.png", b"\x89PNG\r\n\x1a\n0000")
    await _upload(ravi, f"/comments/{comment['id']}/attachments", "comment.txt")
    # a file in another project never shows here
    other = await _project(ravi, "Mobile App v2")
    other_task = await _task(ravi, other)
    await _upload(ravi, f"/tasks/{other_task['id']}/attachments", "elsewhere.txt")

    page = await _files(ravi, pid)
    names = sorted(f["filename"] for f in page["data"])
    assert names == ["comment.txt", "deep.png", "plan.docx", "task.csv"]
    assert page["total"] == 4 and page["next_cursor"] is None
    by = {f["filename"]: f for f in page["data"]}
    assert by["plan.docx"]["location"]["type"] == "project"
    assert by["plan.docx"]["kind"] == "document"
    assert by["task.csv"]["kind"] == "spreadsheet"
    assert by["deep.png"]["kind"] == "image"
    assert by["deep.png"]["location"]["task_title"] == "Deeper"
    assert by["comment.txt"]["location"]["type"] == "comment"
    assert by["comment.txt"]["location"]["task_key"] == task["key"]
    assert by["task.csv"]["uploaded_by_name"] == "Ravi Kumar"

    # filters
    assert [f["filename"] for f in (await _files(ravi, pid, where="project"))["data"]] == [
        "plan.docx"
    ]
    assert {f["filename"] for f in (await _files(ravi, pid, where="tasks"))["data"]} == {
        "task.csv",
        "deep.png",
    }
    assert [f["filename"] for f in (await _files(ravi, pid, kind="image"))["data"]] == ["deep.png"]
    assert [f["filename"] for f in (await _files(ravi, pid, q="PLAN"))["data"]] == ["plan.docx"]
    assert [f["filename"] for f in (await _files(ravi, pid, sort="name"))["data"]] == [
        "comment.txt",
        "deep.png",
        "plan.docx",
        "task.csv",
    ]

    # a deleted comment or a deleted parent hides its files
    await ravi.delete(f"{B}/comments/{comment['id']}")
    await ravi.delete(f"{B}/tasks/{sub['id']}")
    assert sorted(f["filename"] for f in (await _files(ravi, pid))["data"]) == [
        "plan.docx",
        "task.csv",
    ]


async def test_paging_with_a_cursor(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    for i in range(53):
        await _upload(ravi, f"/projects/{pid}/files", f"f{i:02}.txt")
    first = await _files(ravi, pid, sort="name")
    assert len(first["data"]) == 50 and first["total"] == 53
    second = await _files(ravi, pid, sort="name", cursor=first["next_cursor"])
    assert [f["filename"] for f in second["data"]] == ["f50.txt", "f51.txt", "f52.txt"]
    assert second["next_cursor"] is None
    r = await ravi.get(f"{B}/projects/{pid}/files", params={"cursor": "x"})
    assert r.status_code == 422


async def test_versions_add_undo_and_delete_promotes_previous(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    v1 = (await _upload(ravi, f"/projects/{pid}/files", "sow.docx", b"one")).json()["data"]
    r = await _upload(ravi, f"/projects/{pid}/files", "sow.docx", b"two", replace_id=v1["id"])
    assert r.status_code == 201, r.text
    v2 = r.json()["data"]
    assert v2["version"] == 2 and v2["version_group"] == v1["id"] and v2["is_current"]

    listed = (await _files(ravi, pid))["data"]
    assert [(f["id"], f["version"], f["versions_count"]) for f in listed] == [(v2["id"], 2, 2)]
    versions = (await ravi.get(f"{B}/attachments/{v1['id']}/versions")).json()["data"]
    assert [v["version"] for v in versions] == [2, 1]
    assert [v["is_current"] for v in versions] == [True, False]
    # the old version stays downloadable
    assert (await ravi.get(f"{B}/attachments/{v1['id']}/download")).content == b"one"

    # undo the new version: v1 is current again
    act = r.json()["meta"]["activity_id"]
    assert (await ravi.post(f"{B}/undo", json={"activity_id": act})).status_code == 200
    assert [f["id"] for f in (await _files(ravi, pid))["data"]] == [v1["id"]]

    # a third upload, then delete the current one: the previous is promoted, undo restores
    v3 = (
        await _upload(ravi, f"/projects/{pid}/files", "sow.docx", b"three", replace_id=v1["id"])
    ).json()["data"]
    assert v3["version"] == 3
    d = await ravi.delete(f"{B}/attachments/{v3['id']}")
    assert d.status_code == 200
    assert [f["id"] for f in (await _files(ravi, pid))["data"]] == [v1["id"]]
    u = await ravi.post(f"{B}/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert u.status_code == 200
    assert [f["id"] for f in (await _files(ravi, pid))["data"]] == [v3["id"]]


async def test_task_file_versions_stay_on_their_task(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t1, t2 = await _task(ravi, pid, "A"), await _task(ravi, pid, "B")
    f = (await _upload(ravi, f"/tasks/{t1['id']}/attachments", "q.xlsx")).json()["data"]
    wrong = await _upload(ravi, f"/tasks/{t2['id']}/attachments", "q.xlsx", replace_id=f["id"])
    assert wrong.status_code == 422
    ok = await _upload(ravi, f"/tasks/{t1['id']}/attachments", "q.xlsx", b"v2", replace_id=f["id"])
    assert ok.status_code == 201 and ok.json()["data"]["version"] == 2
    listed = (await ravi.get(f"{B}/tasks/{t1['id']}/attachments")).json()["data"]
    assert [a["version"] for a in listed] == [2]
    # a project upload can't replace a task's file
    bad = await _upload(ravi, f"/projects/{pid}/files", "q.xlsx", replace_id=f["id"])
    assert bad.status_code == 422


async def test_permissions_viewer_editor_guest_outsider(as_user: Clients) -> None:
    ravi, admin = await as_user("ravi"), await as_user("admin")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{B}/users")).json()["data"]
    }
    pid = await _project(ravi)
    f = (await _upload(ravi, f"/projects/{pid}/files", "plan.txt")).json()["data"]

    # editor (mei is on the Product team): uploads, can't delete ravi's file
    mei = await as_user("mei")
    assert (await _upload(mei, f"/projects/{pid}/files", "mine.txt")).status_code == 201
    assert (await mei.delete(f"{B}/attachments/{f['id']}")).status_code == 403

    # viewer: lists and downloads, can't upload or add a version
    await ravi.post(f"{B}/projects/{pid}/members", json={"user_id": users["mei"], "role": "viewer"})
    assert len((await _files(mei, pid))["data"]) == 2
    assert (await mei.get(f"{B}/attachments/{f['id']}/download")).status_code == 200
    assert (await _upload(mei, f"/projects/{pid}/files", "no.txt")).status_code == 403
    r = await _upload(mei, f"/projects/{pid}/files", "plan.txt", replace_id=f["id"])
    assert r.status_code == 403

    # outsider (tom isn't on the Product team): nothing, not even existence
    tom = await as_user("tom")
    assert (await tom.get(f"{B}/projects/{pid}/files")).status_code == 404
    assert (await tom.get(f"{B}/attachments/{f['id']}/download")).status_code == 404
    assert (await tom.get(f"{B}/attachments/{f['id']}/versions")).status_code == 404
    assert (await _upload(tom, f"/projects/{pid}/files", "x.txt")).status_code == 404

    # a private project's task file never appears to a non-member, nor in their search
    private = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, private)
    secret = (await _upload(ravi, f"/tasks/{t['id']}/attachments", "secret-plan.txt")).json()[
        "data"
    ]
    assert (await mei.get(f"{B}/projects/{private}/files")).status_code == 404
    hits = (await mei.get(f"{B}/search", params={"q": "secret-plan"})).json()["files"]
    assert secret["id"] not in {h["id"] for h in hits}

    # guest: only shared projects (H61). Priya is a member of Mobile App v2 (owner) but not
    # explicitly of Website Revamp.
    await admin.patch(f"{B}/users/{users['priya']}", json={"role": "guest"})
    priya = await as_user("priya")
    assert (await priya.get(f"{B}/projects/{pid}/files")).status_code == 404
    assert (await priya.get(f"{B}/attachments/{f['id']}/download")).status_code == 404
    assert [x["id"] for x in (await _files(priya, private))["data"]] == [secret["id"]]
    hits = (await priya.get(f"{B}/search", params={"q": "plan"})).json()["files"]
    assert {h["id"] for h in hits} == {secret["id"]}


async def test_search_files_group(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    a = (await _upload(ravi, f"/projects/{pid}/files", "Statement-of-work.docx")).json()["data"]
    b = (await _upload(ravi, f"/tasks/{t['id']}/attachments", "statement notes.txt")).json()["data"]
    res = (await ravi.get(f"{B}/search", params={"q": "statement"})).json()
    by = {h["id"]: h for h in res["files"]}
    assert set(by) == {a["id"], b["id"]}
    assert by[a["id"]]["project_name"] == "Website Revamp" and by[a["id"]]["task_id"] is None
    assert by[b["id"]]["task_title"] == "T"
    only = (await ravi.get(f"{B}/search", params={"q": "statement", "type": "file"})).json()
    assert only["tasks"] == [] and len(only["files"]) == 2
    # old versions aren't listed twice
    await _upload(ravi, f"/projects/{pid}/files", "Statement-of-work.docx", replace_id=a["id"])
    res = (await ravi.get(f"{B}/search", params={"q": "statement-of"})).json()
    assert len(res["files"]) == 1


async def test_upload_then_delete_by_project_admin_and_events(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    mei = await as_user("mei")
    pid = await _project(ravi)
    f = (await _upload(mei, f"/projects/{pid}/files", "m.txt")).json()["data"]
    # ravi owns the project (admin): may remove someone else's project file
    d = await ravi.delete(f"{B}/attachments/{f['id']}")
    assert d.status_code == 200
    assert (await _files(ravi, pid))["data"] == []
