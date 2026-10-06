"""Phase 7.5 S75-04: project fields (spec §5.1). Definitions, values of every type, history
rows, undo, permissions, events, template defaults and lineage, the Mo tool, and the rule action
``set_project_field`` with its stage-gate skip (spec §5.5).

The AC: setting a project field via the UI/API, a rule or the Mo tool writes exactly one history
row and one undoable activity."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.fields.models import ProjectFieldEvent, ProjectFieldValue
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.projects.models import Project
from momentum.domain.rules.engine import run_rules
from momentum.domain.rules.models import RuleRun
from tests.ai_fixtures import REG, World, call, world
from tests.helpers import Clients

_ = world  # the fixture is used by name

SessionFactory = async_sessionmaker[AsyncSession]
B = "/api/v1"
STAGES = ["Pre-sales", "Discovery", "Contracts", "Implementation", "Go-live", "Hypercare"]


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _users(c: httpx.AsyncClient) -> dict[str, str]:
    return {u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{B}/users")).json()["data"]}


async def _field(c: httpx.AsyncClient, name: str, type_: str, **extra: Any) -> dict[str, Any]:
    r = await c.post(f"{B}/project-fields", json={"name": name, "type": type_, **extra})
    assert r.status_code == 201, r.text
    return dict(r.json()["data"])


async def _stage(c: httpx.AsyncClient) -> tuple[str, dict[str, str]]:
    f = await _field(c, "Stage", "single_select", options=[{"label": s} for s in STAGES])
    return f["id"], {o["label"]: o["id"] for o in f["options"]}


async def _set(c: httpx.AsyncClient, pid: str, fid: str, value: Any) -> httpx.Response:
    return await c.put(f"{B}/projects/{pid}/project-field-values/{fid}", json={"value": value})


async def _values(c: httpx.AsyncClient, pid: str) -> dict[str, Any]:
    rows = (await c.get(f"{B}/projects/{pid}/project-field-values")).json()["data"]
    return {r["field_id"]: r["value"] for r in rows}


async def _history(sf: SessionFactory, pid: str) -> list[ProjectFieldEvent]:
    async with sf() as s:
        rows = await s.execute(
            select(ProjectFieldEvent)
            .where(ProjectFieldEvent.project_id == uuid.UUID(pid))
            .order_by(ProjectFieldEvent.at, ProjectFieldEvent.id)
        )
        return list(rows.scalars())


async def _field_activities(sf: SessionFactory, pid: str) -> list[Activity]:
    async with sf() as s:
        rows = await s.execute(
            select(Activity)
            .where(Activity.entity_id == uuid.UUID(pid), Activity.verb == "project.field_set")
            .order_by(Activity.created_at)
        )
        return list(rows.scalars())


# ---------------- definitions ----------------


async def test_project_fields_are_workspace_definitions_kept_apart_from_task_fields(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    stage_id, _ = await _stage(ravi)
    listed = (await ravi.get(f"{B}/project-fields")).json()["data"]
    assert [f["name"] for f in listed] == ["Stage"] and listed[0]["applies_to"] == "project"
    library = {f["name"]: f["applies_to"] for f in (await ravi.get(f"{B}/fields")).json()["data"]}
    assert library["Stage"] == "project"
    # a project field is never attached to a project as a task field
    pid = await _project(ravi)
    r = await ravi.post(f"{B}/projects/{pid}/fields/attach", json={"field_id": stage_id})
    assert r.status_code == 422 and r.json()["code"] == "project_field"
    # names are unique among project fields (not across task fields)
    r = await ravi.post(f"{B}/project-fields", json={"name": "stage", "type": "text"})
    assert r.status_code == 422 and r.json()["code"] == "name_taken"
    # rename and re-option: the creator or an admin
    r = await ravi.patch(f"{B}/project-fields/{stage_id}", json={"name": "Lifecycle stage"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "Lifecycle stage"
    mei = await as_user("mei")
    r = await mei.patch(f"{B}/project-fields/{stage_id}", json={"name": "Mine now"})
    assert r.status_code == 403


async def test_guests_cannot_add_project_fields(as_user: Clients) -> None:
    admin = await as_user("admin")
    users = await _users(admin)
    await admin.patch(f"{B}/users/{users['priya']}", json={"role": "guest"})
    guest = await as_user("priya")
    r = await guest.post(f"{B}/project-fields", json={"name": "Region", "type": "text"})
    assert r.status_code == 403


# ---------------- values: every type, history, undo, events ----------------


async def test_every_type_validates_and_writes_one_history_row_and_one_activity(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = await _users(ravi)
    stage_id, stages = await _stage(ravi)
    fields = {
        "text": (await _field(ravi, "Account", "text"))["id"],
        "number": (await _field(ravi, "Seats", "number"))["id"],
        "currency": (
            await _field(
                ravi, "Contract value", "currency", options={"precision": 0, "unit": "EUR"}
            )
        )["id"],
        "percent": (await _field(ravi, "Adoption", "percent"))["id"],
        "date": (await _field(ravi, "Go-live date", "date"))["id"],
        "checkbox": (await _field(ravi, "Signed", "checkbox"))["id"],
        "url": (await _field(ravi, "CRM link", "url"))["id"],
        "people": (await _field(ravi, "Account owner", "people"))["id"],
    }
    tags = await _field(
        ravi, "Modules", "multi_select", options=[{"label": "HR"}, {"label": "Pay"}]
    )
    good: dict[str, Any] = {
        stage_id: stages["Discovery"],
        fields["text"]: "Zenith Health",
        fields["number"]: 120,
        fields["currency"]: 48000,
        fields["percent"]: 35.5,
        fields["date"]: "2026-12-01",
        fields["checkbox"]: True,
        fields["url"]: "https://crm.example.com/zenith",
        fields["people"]: [users["mei"]],
        tags["id"]: [o["id"] for o in tags["options"]],
    }
    for fid, value in good.items():
        r = await _set(ravi, pid, fid, value)
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["activity_id"]
    assert await _values(ravi, pid) == good
    assert len(await _history(session_factory, pid)) == len(good)
    assert len(await _field_activities(session_factory, pid)) == len(good)

    bad: dict[str, Any] = {
        stage_id: "not-an-option",
        fields["number"]: "many",
        fields["date"]: "next week",
        fields["checkbox"]: "yes",
        fields["people"]: ["not-a-uuid"],
    }
    for fid, value in bad.items():
        assert (await _set(ravi, pid, fid, value)).status_code == 422
    # setting the value it already has changes and records nothing
    r = await _set(ravi, pid, stage_id, stages["Discovery"])
    assert r.status_code == 200 and r.json()["meta"]["activity_id"] is None
    assert len(await _history(session_factory, pid)) == len(good)


async def test_history_events_and_undo(as_user: Clients, session_factory: SessionFactory) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    stage_id, stages = await _stage(ravi)
    await _set(ravi, pid, stage_id, stages["Pre-sales"])
    moved = await _set(ravi, pid, stage_id, stages["Discovery"])

    history = (await ravi.get(f"{B}/projects/{pid}/project-field-history")).json()["data"]
    assert [(h["old"], h["new"]) for h in history] == [
        (None, stages["Pre-sales"]),
        (stages["Pre-sales"], stages["Discovery"]),
    ]
    only = await ravi.get(f"{B}/projects/{pid}/project-field-history?field_id={stage_id}")
    assert len(only.json()["data"]) == 2

    # the event reaches the project and every portfolio containing it
    folio = (await ravi.post(f"{B}/portfolios", json={"name": "Onboarding"})).json()["data"]
    await ravi.post(f"{B}/portfolios/{folio['id']}/projects", json={"project_id": pid})
    await _set(ravi, pid, stage_id, stages["Contracts"])
    async with session_factory() as s:
        ev = (
            await s.execute(
                select(OutboxEvent)
                .where(OutboxEvent.type == "project.field_changed")
                .order_by(OutboxEvent.id.desc())
                .limit(1)
            )
        ).scalar_one()
    assert set(ev.payload["channels"]) == {f"project:{pid}", f"portfolio:{folio['id']}"}
    assert ev.payload["data"]["new"] == stages["Contracts"]

    # undo of the Discovery move conflicts: the field changed again since
    r = await ravi.post(f"{B}/undo", json={"activity_id": moved.json()["meta"]["activity_id"]})
    assert r.status_code == 409
    # undo of the latest restores Discovery and writes its own history row
    acts = await _field_activities(session_factory, pid)
    r = await ravi.post(f"{B}/undo", json={"activity_id": str(acts[-1].id)})
    assert r.status_code == 200, r.text
    assert (await _values(ravi, pid))[stage_id] == stages["Discovery"]
    rows = await _history(session_factory, pid)
    assert (rows[-1].old, rows[-1].new) == (stages["Contracts"], stages["Discovery"])


async def test_clearing_removes_the_value_and_is_history_too(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    fid = (await _field(ravi, "Account", "text"))["id"]
    await _set(ravi, pid, fid, "Zenith")
    r = await _set(ravi, pid, fid, None)
    assert r.status_code == 200 and r.json()["data"]["value"] is None
    assert fid not in await _values(ravi, pid)
    rows = await _history(session_factory, pid)
    assert [(h.old, h.new) for h in rows] == [(None, "Zenith"), ("Zenith", None)]
    await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await _values(ravi, pid))[fid] == "Zenith"


async def test_permissions_editor_sets_viewer_reads_outsider_sees_nothing(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = await _users(ravi)
    fid = (await _field(ravi, "Account", "text"))["id"]
    await ravi.post(f"{B}/projects/{pid}/members", json={"user_id": users["mei"], "role": "viewer"})
    mei = await as_user("mei")
    assert (await _set(mei, pid, fid, "Nope")).status_code == 403
    assert (await mei.get(f"{B}/projects/{pid}/project-field-values")).status_code == 200
    kim = await as_user("kim")  # not on the Product team, not a member
    assert (await kim.get(f"{B}/projects/{pid}/project-field-values")).status_code in (403, 404)
    assert (await kim.get(f"{B}/projects/{pid}/project-field-history")).status_code in (403, 404)
    assert (await _set(kim, pid, fid, "Nope")).status_code in (403, 404)


# ---------------- templates: defaults and lineage ----------------


async def test_templates_carry_project_field_defaults_and_set_lineage(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    stage_id, stages = await _stage(ravi)
    value_id = (await _field(ravi, "Contract value", "currency"))["id"]
    await _set(ravi, pid, stage_id, stages["Pre-sales"])
    await _set(ravi, pid, value_id, 1000)
    saved = await ravi.post(
        f"{B}/templates/from-project", json={"project_id": pid, "name": "Customer onboarding"}
    )
    assert saved.status_code == 201, saved.text
    template = saved.json()["data"]
    assert template["payload"]["project_field_defaults"] == {
        stage_id: stages["Pre-sales"],
        value_id: 1000,
    }
    teams = (await ravi.get(f"{B}/teams")).json()["data"]
    team = next(t["id"] for t in teams if t["name"] == "Product")
    made = await ravi.post(
        f"{B}/templates/{template['id']}/new-project",
        json={"team_id": team, "name": "Zenith onboarding", "start_date": "2026-11-01"},
    )
    assert made.status_code == 201, made.text
    new_pid = made.json()["data"]["id"]
    assert await _values(ravi, new_pid) == {stage_id: stages["Pre-sales"], value_id: 1000}
    async with session_factory() as s:
        project = await s.get(Project, uuid.UUID(new_pid))
        assert project is not None and str(project.template_id) == template["id"]
        other = await s.get(Project, uuid.UUID(pid))
        assert other is not None and other.template_id is None  # only template-made projects
    # the defaults are history like any other change
    assert len(await _history(session_factory, new_pid)) == 2


# ---------------- the rule action ----------------


async def _milestone(c: httpx.AsyncClient, pid: str, title: str) -> str:
    sec = (await c.get(f"{B}/projects/{pid}/sections")).json()["data"][0]["id"]
    r = await c.post(f"{B}/projects/{pid}/tasks", json={"title": title, "section_id": sec})
    assert r.status_code == 201, r.text
    tid = str(r.json()["data"]["id"])
    r = await c.post(f"{B}/tasks/{tid}/convert", json={"type": "milestone"})
    assert r.status_code == 200, r.text
    return tid


async def _stage_rule(c: httpx.AsyncClient, pid: str, stage_id: str, option: str) -> str:
    r = await c.post(
        f"{B}/rules",
        json={
            "name": "Contract signed moves to Implementation",
            "project_id": pid,
            "trigger": {"type": "task.completed"},
            "conditions": [{"field": "title", "op": "eq", "value": "contract SIGNED"}],
            "actions": [{"type": "set_project_field", "field_id": stage_id, "value": option}],
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _runs(sf: SessionFactory, rule_id: str) -> list[RuleRun]:
    async with sf() as s:
        rows = await s.execute(
            select(RuleRun)
            .where(RuleRun.rule_id == uuid.UUID(rule_id))
            .order_by(RuleRun.started_at)
        )
        return list(rows.scalars())


async def _run(sf: SessionFactory, settings: Settings) -> None:
    async with sf() as s, s.begin():
        await run_rules(s, settings)


async def test_rule_sets_the_projects_stage_once_with_history_and_undo(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    stage_id, stages = await _stage(ravi)
    rid = await _stage_rule(ravi, pid, stage_id, stages["Implementation"])
    other = await _milestone(ravi, pid, "Kickoff held")
    signed = await _milestone(ravi, pid, "Contract signed")
    await ravi.post(f"{B}/tasks/{other}/complete")
    await ravi.post(f"{B}/tasks/{signed}/complete")
    await _run(session_factory, settings)

    assert (await _values(ravi, pid))[stage_id] == stages["Implementation"]
    runs = await _runs(session_factory, rid)
    # the other milestone's completion doesn't pass the title condition: no run at all
    assert [(r.status, r.actions_run) for r in runs] == [("success", 1)]
    rows = await _history(session_factory, pid)
    assert [(h.old, h.new) for h in rows] == [(None, stages["Implementation"])]
    (act,) = await _field_activities(session_factory, pid)
    assert act.actor_kind == "rule" and act.undo_payload is not None
    r = await ravi.post(f"{B}/undo", json={"activity_id": str(act.id)})
    assert r.status_code == 200, r.text
    assert stage_id not in await _values(ravi, pid)


async def test_rule_validation_needs_a_project_field_and_a_valid_value(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    stage_id, _ = await _stage(ravi)
    task_field = (
        await ravi.post(f"{B}/projects/{pid}/fields", json={"name": "Effort", "type": "number"})
    ).json()["data"]["id"]
    base = {"name": "R", "trigger": {"type": "task.completed"}}

    async def make(project_id: str | None, action: dict[str, Any]) -> int:
        body = {**base, "project_id": project_id, "actions": [action]}
        return (await ravi.post(f"{B}/rules", json=body)).status_code

    act = {"type": "set_project_field", "field_id": stage_id, "value": "not-an-option"}
    assert await make(pid, act) == 422
    assert await make(pid, {**act, "field_id": task_field, "value": 3}) == 422
    assert await make(pid, {**act, "field_id": "priority", "value": "high"}) == 422
    admin = await as_user("admin")
    body = {**base, "project_id": None, "actions": [{**act, "value": None}]}
    assert (await admin.post(f"{B}/rules", json=body)).status_code == 422  # workspace rule


async def test_rule_never_overrides_a_stage_gate(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    stage_id, stages = await _stage(ravi)
    signed_field = (await _field(ravi, "Signed on", "date"))["id"]
    folio = (await ravi.post(f"{B}/portfolios", json={"name": "Onboarding"})).json()["data"]
    await ravi.post(f"{B}/portfolios/{folio['id']}/projects", json={"project_id": pid})
    async with session_factory() as s, s.begin():
        await s.execute(
            update(Portfolio)
            .where(Portfolio.id == uuid.UUID(folio["id"]))
            .values(
                stage_field_id=uuid.UUID(stage_id),
                stage_gates={
                    stages["Implementation"]: {
                        "required_fields": [signed_field],
                        "required_files": ["*contract*signed*.pdf"],
                    }
                },
            )
        )
    rid = await _stage_rule(ravi, pid, stage_id, stages["Implementation"])
    tid = await _milestone(ravi, pid, "Contract signed")
    await ravi.post(f"{B}/tasks/{tid}/complete")
    await _run(session_factory, settings)

    assert stage_id not in await _values(ravi, pid)
    (run,) = await _runs(session_factory, rid)
    assert run.status == "success" and run.actions_run == 0
    assert run.error is not None and "not met" in run.error and "Signed on" in run.error
    assert await _history(session_factory, pid) == []

    # meet the gate, run it again: now the stage moves
    await _set(ravi, pid, signed_field, "2026-10-01")
    upload = await ravi.post(
        f"{B}/projects/{pid}/files",
        files={"file": ("Contract-signed.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    await ravi.post(f"{B}/tasks/{tid}/uncomplete")
    await ravi.post(f"{B}/tasks/{tid}/complete")
    await _run(session_factory, settings)
    assert (await _values(ravi, pid))[stage_id] == stages["Implementation"]


# ---------------- the Mo tool ----------------


async def test_mo_tool_sets_a_project_field_by_label_with_one_history_row(
    uow: UnitOfWork, world: World
) -> None:
    from momentum.domain.fields.project_values import create_project_field
    from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn

    async with uow.transaction() as s:
        await create_project_field(
            s,
            world.ravi,
            FieldCreateIn(
                name="Stage",
                type="single_select",
                options=[SelectOptionIn(label=x) for x in STAGES],
            ),
        )
    args = {"project": world.project.name, "field": "stage", "value": "Go-live"}
    dry = await call(uow, world.ravi, "set_project_field", args)
    assert dry.ok and "Would set Stage = Go-live" in dry.result.summary
    out = await call(uow, world.ravi, "set_project_field", args, mode="apply")
    assert out.ok, out.result.error
    again = await call(uow, world.ravi, "set_project_field", args, mode="apply")
    assert "already has" in again.result.summary
    viewer = await call(uow, world.lena, "set_project_field", args, mode="apply")
    assert not viewer.ok
    unknown = await call(uow, world.ravi, "set_project_field", {**args, "value": "Closed won"})
    assert not unknown.ok
    async with uow.transaction() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(ProjectFieldEvent)
                .where(ProjectFieldEvent.project_id == world.project.id)
            )
        ).scalar_one()
        acts = (
            await s.execute(
                select(Activity).where(
                    Activity.entity_id == world.project.id, Activity.verb == "project.field_set"
                )
            )
        ).scalars()
        value = (await s.execute(select(ProjectFieldValue.value))).scalar_one()
    assert n == 1
    assert len(list(acts)) == 1
    assert value  # an option id, not the label
    read = await call(uow, world.ravi, "get_project", {"project": world.project.name})
    fields = read.result.data["project"]["fields"]  # type: ignore[index]
    assert {
        "name": "Stage",
        "type": "single_select",
        "choices": STAGES,
        "value": "Go-live",
    } in fields
    tool = REG.get("set_project_field")
    assert tool is not None and tool.spec.risk == "low"
