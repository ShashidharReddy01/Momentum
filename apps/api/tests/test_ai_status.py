"""S3.4.3 status updates: the domain write path (status set, undo withdraws and restores, undo
refused after a newer change, permissions), per-reader citations, the ``create_status_update``
tool (preview changes nothing), the facts collected for a draft, and the draft check (every
remaining claim cites a fact; invented or uncited claims removed with notes)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from momentum.ai.llm import build_llm
from momentum.ai.status_draft import KEY, collect_facts, draft_status
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, NotFound
from momentum.core.events import OutboxEvent
from momentum.core.undo import UndoConflict, undo
from momentum.domain.projects.models import Project
from momentum.domain.status_updates import service
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import TaskDependency
from tests.ai_fixtures import World, call, key, world
from tests.conftest import make_settings
from tests.helpers import Clients

_ = world
NOW = datetime.now(UTC)


def update_in(status: str = "at_risk", text: str = "Copy is late") -> StatusUpdateIn:
    return StatusUpdateIn(
        status=status,  # type: ignore[arg-type]
        title="Weekly",
        summary=text,
        sections=StatusSections(slipped=[StatusItem(text=text)]),
    )


async def project_status(uow: UnitOfWork, project_id: uuid.UUID) -> str | None:
    async with uow.transaction() as s:
        p = await s.get(Project, project_id)
        assert p is not None
        await s.refresh(p)
        return p.status


async def test_post_sets_status_and_undo_withdraws(uow: UnitOfWork, world: World) -> None:
    pid = world.project.id
    async with uow.transaction() as s:
        m = await service.create_status_update(s, world.ravi, pid, update_in())
        assert m.activity_id is not None
        first_act = m.activity_id
    assert await project_status(uow, pid) == "at_risk"
    async with uow.transaction() as s:
        rows = await service.list_status_updates(s, world.ana, pid)
        assert [u.title for u in rows] == ["Weekly"] and rows[0].author_id == world.ravi.actor.id
        assert "At risk: Weekly" in rows[0].body_text and "- Copy is late" in rows[0].body_text
        events = (
            (
                await s.execute(
                    select(OutboxEvent).where(OutboxEvent.type == "status_update.created")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
    async with uow.transaction() as s:
        await undo(s, world.ravi, activity_id=first_act)
    assert await project_status(uow, pid) is None
    async with uow.transaction() as s:
        assert await service.list_status_updates(s, world.ravi, pid) == []


async def test_undo_refused_after_a_newer_status(uow: UnitOfWork, world: World) -> None:
    pid = world.project.id
    async with uow.transaction() as s:
        first = (await service.create_status_update(s, world.ravi, pid, update_in())).activity_id
        await service.create_status_update(s, world.ravi, pid, update_in("on_track", "Back on"))
    with pytest.raises(UndoConflict):
        async with uow.transaction() as s:
            await undo(s, world.ravi, activity_id=first)
    assert await project_status(uow, pid) == "on_track"


async def test_permissions(uow: UnitOfWork, world: World) -> None:
    pid, secret = world.project.id, world.secret.id
    with pytest.raises(Forbidden):
        async with uow.transaction() as s:
            await service.create_status_update(s, world.lena, pid, update_in())
    with pytest.raises(NotFound):
        async with uow.transaction() as s:
            await service.list_status_updates(s, world.ravi, secret)


async def test_tool_previews_then_posts(uow: UnitOfWork, world: World) -> None:
    pid = world.project.id
    args = {
        "project": "AI Tools Lab",
        "status": "off_track",
        "title": "Launch slips",
        "slipped": [f"[{key(world.copy)}] late"],
    }
    out = await call(uow, world.ravi, "create_status_update", args)
    assert out.ok and out.risk == "medium"
    assert out.result.summary.startswith("Would post a status update on AI Tools Lab")
    async with uow.transaction() as s:
        assert (await s.execute(select(func.count()).select_from(StatusUpdate))).scalar_one() == 0
    assert await project_status(uow, pid) is None
    out = await call(uow, world.ravi, "create_status_update", args, mode="apply")
    assert out.ok and await project_status(uow, pid) == "off_track"
    async with uow.transaction() as s:
        (u,) = (await s.execute(select(StatusUpdate))).scalars()
        assert u.generated_by_ai and u.created_via == "ai"
    viewer = await call(uow, world.lena, "create_status_update", args)
    assert not viewer.ok and viewer.result.error["code"] == "forbidden"  # type: ignore[index]


async def test_facts(uow: UnitOfWork, world: World) -> None:
    ravi = world.ravi
    copy_id, faq_id, pid = world.copy.id, world.faq.id, world.project.id
    today = NOW.date()
    async with uow.transaction() as s:
        done = (await tasks.create_task(s, ravi, pid, "Ship the banner")).entity[0]
        late = (await tasks.create_task(s, ravi, pid, "Old report")).entity[0]
        await tasks.set_completed(s, ravi, done.id, True)
        await tasks.update_task(s, ravi, late.id, {"due_on": today - timedelta(days=3)})
        await tasks.update_task(s, ravi, copy_id, {"due_on": today + timedelta(days=2)})
        await tasks.update_task(s, ravi, copy_id, {"due_on": today + timedelta(days=5)})
        s.add(TaskDependency(task_id=faq_id, depends_on_id=copy_id))
        # pulled earlier is not a slip; blocked only by finished work is not blocked
        early = (await tasks.create_task(s, ravi, pid, "Pulled in")).entity[0]
        await tasks.update_task(s, ravi, early.id, {"due_on": today + timedelta(days=6)})
        await tasks.update_task(s, ravi, early.id, {"due_on": today + timedelta(days=4)})
        unblocked = (await tasks.create_task(s, ravi, pid, "Free now")).entity[0]
        s.add(TaskDependency(task_id=unblocked.id, depends_on_id=done.id))
        numbers = {
            "done": done.number,
            "late": late.number,
            "early": early.number,
            "free": unblocked.number,
        }
    async with uow.transaction() as s:
        f = await collect_facts(s, ravi, pid, since=today - timedelta(days=7), today=today)
    joined = "\n".join
    assert f"T-{numbers['done']}" in joined(f.completed)
    assert f"T-{numbers['late']}" in joined(f.overdue) and "3 days overdue" in joined(f.overdue)
    assert key(world.copy) in joined(f.pushed) and "→" in joined(f.pushed)
    assert key(world.faq) in joined(f.blocked)
    assert key(world.copy) in joined(f.due_soon)
    assert key(world.hidden) not in f.keys
    assert f"T-{numbers['early']}]" not in joined(f.pushed)
    assert f"T-{numbers['free']}]" not in joined(f.blocked)


async def test_draft_keeps_only_claims_that_cite_facts(uow: UnitOfWork, world: World) -> None:
    ravi, pid = world.ravi, world.project.id
    async with uow.transaction() as s:
        await tasks.set_completed(s, ravi, world.copy.id, True)
    llm = build_llm(make_settings())
    async with uow.transaction() as s:
        r = await draft_status(s, llm, ravi.with_(via="ai"), pid, now=NOW)
    d = r.draft
    assert d.status == "at_risk" and d.generated_by_ai
    items = [*d.sections.completed, *d.sections.slipped, *d.sections.blockers, *d.sections.next]
    assert items, "the cited claims survive"
    for i in items:  # AC: every remaining claim cites a task from the facts
        assert KEY.findall(i.text) and all(k == key(world.copy) for k in KEY.findall(i.text))
    assert d.sections.slipped == []
    assert "T-999999" not in d.summary and key(world.copy) in d.summary
    notes = "\n".join(r.notes)
    assert "“Something vague slipped” cites no task" in notes
    assert "“Invented delay on [T-999999]” cites tasks outside" in notes
    assert "Removed references to T-999999 from the summary" in notes
    assert r.facts["completed"] == 1


async def test_draft_needs_edit_rights(uow: UnitOfWork, world: World) -> None:
    llm = build_llm(make_settings())
    with pytest.raises(Forbidden):
        async with uow.transaction() as s:
            await draft_status(s, llm, world.lena, world.project.id, now=NOW)


async def test_endpoints_draft_publish_history(
    as_user: Clients, uow: UnitOfWork, world: World
) -> None:
    ravi = await as_user("ravi")
    pid = world.project.id
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, world.copy.id, True)
    r = await ravi.post(f"/api/v1/ai/projects/{pid}/status-draft", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["facts"]["completed"] == 1 and body["notes"]
    assert any(c["valid"] and c["key"] == key(world.copy) for c in body["citations"])
    r = await ravi.post(f"/api/v1/projects/{pid}/status-updates", json=body["draft"])
    assert r.status_code == 201, r.text
    assert r.json()["data"]["generated_by_ai"] is True and r.json()["meta"]["activity_id"]
    hist = (await ravi.get(f"/api/v1/projects/{pid}/status-updates")).json()["data"]
    assert len(hist) == 1 and hist[0]["status"] == "at_risk"
    assert any(c["valid"] for c in hist[0]["citations"])
    # another reader sees citations resolved for them: tom can't read the project at all
    tom = await as_user("tom")
    assert (await tom.get(f"/api/v1/projects/{pid}/status-updates")).status_code == 404
    lena = await as_user("lena")
    assert (await lena.post(f"/api/v1/ai/projects/{pid}/status-draft", json={})).status_code == 403
    r = await lena.post(f"/api/v1/projects/{pid}/status-updates", json=body["draft"])
    assert r.status_code == 403
    assert date.fromisoformat(body["since"]) < NOW.date()
