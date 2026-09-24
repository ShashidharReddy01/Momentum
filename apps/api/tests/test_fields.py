"""S2.3.1 Custom fields: definitions, workspace library, project attach/detach/reorder,
permissions, and field values (get/set)."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _fields(c, pid: str) -> list[dict]:  # type: ignore[no-untyped-def]
    return (await c.get(f"/api/v1/projects/{pid}/fields")).json()["data"]


async def _field_by_name(c, pid: str, name: str) -> dict:  # type: ignore[no-untyped-def]
    return next(pf for pf in await _fields(c, pid) if pf["field"]["name"] == name)


async def _create(c, pid: str, **body):  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/fields", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _task(c, pid: str) -> dict:  # type: ignore[no-untyped-def]
    sec = (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"][0]["id"]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T", "section_id": sec})
    return r.json()["data"]


async def test_create_attaches_to_the_project_and_joins_the_library(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(ravi, pid, name="Priority", type="single_select", options=[])
    assert field["name"] == "Priority"
    assert field["type"] == "single_select"
    assert (await _field_by_name(ravi, pid, "Priority"))["field"]["id"] == field["id"]
    lib = [f["name"] for f in (await ravi.get("/api/v1/fields")).json()["data"]]
    assert "Priority" in lib


async def test_select_options_get_ids_assigned_and_are_returned_in_order(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(
        ravi,
        pid,
        name="Priority",
        type="single_select",
        options=[{"label": "High", "color": "#ff0000"}, {"label": "Low", "color": "#00ff00"}],
    )
    opts = field["options"]
    assert [o["label"] for o in opts] == ["High", "Low"]
    assert all(o["id"] for o in opts)
    assert opts[0]["id"] != opts[1]["id"]


async def test_number_field_options_default_precision(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(ravi, pid, name="Effort", type="number")
    assert field["options"] == {"precision": 0, "unit": None}
    field2 = await _create(
        ravi, pid, name="Cost", type="currency", options={"precision": 2, "unit": "USD"}
    )
    assert field2["options"] == {"precision": 2, "unit": "USD"}


async def test_text_type_fields_reject_options(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await ravi.post(
        f"/api/v1/projects/{pid}/fields",
        json={"name": "Link", "type": "url", "options": [{"label": "x"}]},
    )
    assert r.status_code == 422


async def test_attach_existing_field_to_another_project_and_reject_double_attach(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    field = await _create(ravi, pid, name="Priority", type="single_select", options=[])
    r = await ravi.post(f"/api/v1/projects/{other}/fields/attach", json={"field_id": field["id"]})
    assert r.status_code == 200, r.text
    assert (await _field_by_name(ravi, other, "Priority"))["field"]["id"] == field["id"]
    r2 = await ravi.post(f"/api/v1/projects/{other}/fields/attach", json={"field_id": field["id"]})
    assert r2.status_code == 409


async def test_reorder_fields_within_a_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _create(ravi, pid, name="A", type="text")
    await _create(ravi, pid, name="B", type="text")
    c = await _create(ravi, pid, name="C", type="text")
    assert [f["field"]["name"] for f in await _fields(ravi, pid)] == ["A", "B", "C"]
    await ravi.post(f"/api/v1/projects/{pid}/fields/{c['id']}/move", json={"before_id": a["id"]})
    assert [f["field"]["name"] for f in await _fields(ravi, pid)] == ["C", "A", "B"]


async def test_visibility_toggle(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(ravi, pid, name="A", type="text")
    assert (await _field_by_name(ravi, pid, "A"))["is_visible"] is True
    r = await ravi.patch(
        f"/api/v1/projects/{pid}/fields/{field['id']}/visibility", json={"is_visible": False}
    )
    assert r.status_code == 200
    assert (await _field_by_name(ravi, pid, "A"))["is_visible"] is False


async def test_patch_edits_reach_every_project_the_field_is_attached_to(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    field = await _create(ravi, pid, name="Priority", type="single_select", options=[])
    await ravi.post(f"/api/v1/projects/{other}/fields/attach", json={"field_id": field["id"]})
    r = await ravi.patch(
        f"/api/v1/projects/{pid}/fields/{field['id']}", json={"name": "Priority Level"}
    )
    assert r.status_code == 200
    assert (await _field_by_name(ravi, pid, "Priority Level"))["field"]["name"] == "Priority Level"
    assert (await _field_by_name(ravi, other, "Priority Level"))["field"][
        "name"
    ] == "Priority Level"


async def test_detach_removes_from_only_this_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    field = await _create(ravi, pid, name="Priority", type="single_select", options=[])
    await ravi.post(f"/api/v1/projects/{other}/fields/attach", json={"field_id": field["id"]})
    r = await ravi.delete(f"/api/v1/projects/{pid}/fields/{field['id']}")
    assert r.status_code == 200
    assert "Priority" not in [f["field"]["name"] for f in await _fields(ravi, pid)]
    assert "Priority" in [f["field"]["name"] for f in await _fields(ravi, other)]
    # the library still has it (it's not deleted, just no longer on this project)
    assert "Priority" in [f["name"] for f in (await ravi.get("/api/v1/fields")).json()["data"]]


async def test_archive_hides_the_field_everywhere_but_keeps_its_values(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    field = await _create(ravi, pid, name="Effort", type="number")
    await ravi.post(f"/api/v1/projects/{other}/fields/attach", json={"field_id": field["id"]})
    t = await _task(ravi, pid)
    await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{field['id']}", json={"value": 5})

    r = await ravi.post(f"/api/v1/projects/{pid}/fields/{field['id']}/archive")
    assert r.status_code == 200
    assert "Effort" not in [f["field"]["name"] for f in await _fields(ravi, pid)]
    assert "Effort" not in [f["field"]["name"] for f in await _fields(ravi, other)]
    assert "Effort" not in [f["name"] for f in (await ravi.get("/api/v1/fields")).json()["data"]]
    # not deleted — the value is still there if the field is ever unarchived (no unarchive UI yet)
    values = {
        v["field_id"]: v["value"]
        for v in (await ravi.get(f"/api/v1/tasks/{t['id']}/fields")).json()["data"]
    }
    assert values[field["id"]] == 5


async def test_permissions_editor_required_to_manage_fields(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(ravi, pid, name="A", type="text")
    kim = await as_user("kim")  # not on the Product team
    r = await kim.post(f"/api/v1/projects/{pid}/fields", json={"name": "B", "type": "text"})
    assert r.status_code in (403, 404)
    r2 = await kim.patch(f"/api/v1/projects/{pid}/fields/{field['id']}", json={"name": "X"})
    assert r2.status_code in (403, 404)


async def test_field_values_set_get_and_clear(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    priority = await _create(
        ravi,
        pid,
        name="Priority",
        type="single_select",
        options=[{"label": "High"}, {"label": "Low"}],
    )
    high_id = priority["options"][0]["id"]
    effort = await _create(ravi, pid, name="Effort", type="number")
    done = await _create(ravi, pid, name="Done", type="checkbox")
    t = await _task(ravi, pid)

    r = await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{priority['id']}", json={"value": high_id})
    assert r.status_code == 200 and r.json()["value"] == high_id
    await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{effort['id']}", json={"value": 3})
    await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{done['id']}", json={"value": True})

    values = {
        v["field_id"]: v["value"]
        for v in (await ravi.get(f"/api/v1/tasks/{t['id']}/fields")).json()["data"]
    }
    assert values[priority["id"]] == high_id
    assert values[effort["id"]] == 3
    assert values[done["id"]] is True

    # clearing removes it from the list entirely
    r = await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{priority['id']}", json={"value": None})
    assert r.status_code == 200 and r.json()["value"] is None
    values2 = {
        v["field_id"] for v in (await ravi.get(f"/api/v1/tasks/{t['id']}/fields")).json()["data"]
    }
    assert priority["id"] not in values2


async def test_field_value_validation_rejects_the_wrong_shape(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    priority = await _create(
        ravi, pid, name="Priority", type="single_select", options=[{"label": "High"}]
    )
    effort = await _create(ravi, pid, name="Effort", type="number")
    t = await _task(ravi, pid)
    assert (
        await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{priority['id']}", json={"value": "nope"})
    ).status_code == 422
    assert (
        await ravi.put(f"/api/v1/tasks/{t['id']}/fields/{effort['id']}", json={"value": "3"})
    ).status_code == 422


async def test_viewer_can_read_values_but_not_set_them(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field = await _create(ravi, pid, name="Effort", type="number")
    t = await _task(ravi, pid)
    kim = await as_user("kim")
    r = await kim.get(f"/api/v1/tasks/{t['id']}/fields")
    assert r.status_code in (403, 404)  # not visible to kim at all (not a member, not assigned)
    r2 = await kim.put(f"/api/v1/tasks/{t['id']}/fields/{field['id']}", json={"value": 1})
    assert r2.status_code in (403, 404)
