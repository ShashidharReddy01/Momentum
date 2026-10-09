"""Phase 7.6 S76-06 (spec §8.8): agent health. Every metric checked against constructed data with
known answers (AC: the health numbers match the constructed data exactly)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents import health
from momentum.app import create_app
from momentum.core.db import UnitOfWork
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.asks.models import Ask
from momentum.domain.records import service as records
from momentum.domain.records.models import Record, RecordVersion
from momentum.domain.skills.models import Skill
from tests.ai_fixtures import World, world
from tests.helpers import Clients, ctx_for
from tests.jobs_env import JobsEnv
from tests.test_records import _agent_ctx, bill

_ = world
B = "/api/v1"


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


def _run(agent: Agent, **over: Any) -> AgentRun:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": agent.workspace_id,
        "agent_id": agent.id,
        "trigger": {"type": "manual"},
        "status": "succeeded",
        "mode": "job",
        "steps": 1,
        "input": {},
        "trace": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": Decimal("0.10"),
        "request_id": uuid.uuid4(),
        "created_at": now - timedelta(hours=2),
        "started_at": now - timedelta(hours=2),
    }
    base.update(over)
    return AgentRun(**base)


async def _build(env: JobsEnv, world: World) -> dict[str, Any]:
    """5 top-level jobs (3 succeeded, 1 failed, 1 running), 4 records from the first, 2 asks,
    one proposed skill (plus echo's 2 starters)."""
    agent = env.agent
    now = datetime.now(UTC)
    runs = []
    for active, total, status, err in (
        (10, 100, "succeeded", None),
        (20, 200, "succeeded", None),
        (30, 300, "succeeded", None),
        (40, 400, "failed", "Boom happened"),
    ):
        created = now - timedelta(hours=3)
        runs.append(
            _run(
                agent,
                status=status,
                error=err,
                active_seconds=active,
                created_at=created,
                finished_at=created + timedelta(seconds=total),
            )
        )
    runs.append(_run(agent, status="running"))
    async with env.uow.transaction() as s:
        for r in runs:
            s.add(r)
    first = runs[0].id
    impl = env.packs.packs["echo"].record_type("echo_bill")
    agent_ctx = await _agent_ctx(env)
    project_id = world.project.id
    made = []
    for i in range(4):
        async with env.uow.transaction() as s:
            r = await records.create_record(
                s, agent_ctx, impl, project_id=project_id, data=bill(number=f"N-{i}")
            )
            r.run_id = first
            made.append(r.id)
    a, b = made[0], made[1]
    async with env.uow.transaction() as s:
        s.add(
            RecordVersion(
                workspace_id=agent.workspace_id,
                record_id=a,
                version=2,
                data={},
                provenance={},
                checks=[],
                status="needs_review",
                via="review",
                change={"ops": [{"op": "set", "path": "number"}], "fields": ["number"]},
            )
        )
        s.add(
            RecordVersion(
                workspace_id=agent.workspace_id,
                record_id=b,
                version=2,
                data={},
                provenance={},
                checks=[],
                status="approved",
                via="agent",
                change={"ops": [{"op": "set_status", "status": "approved"}], "fields": []},
            )
        )
        for answered in (True, False):
            s.add(
                Ask(
                    workspace_id=agent.workspace_id,
                    agent_id=agent.id,
                    run_id=first,
                    step_key=f"q{answered}",
                    task_id=world.copy.id,
                    to_user_ids=[world.ravi.actor.id],
                    route="requester",
                    kind="text",
                    title="?",
                    body="",
                    evidence=[],
                    default_on_expiry={"action": "fail"},
                    status="answered" if answered else "open",
                    answer="x" if answered else None,
                    expires_at=now + timedelta(days=7),
                    reminders_sent=0,
                    created_at=now - timedelta(minutes=10),
                    answered_at=now - timedelta(minutes=9) if answered else None,
                )
            )
        s.add(
            Skill(
                workspace_id=agent.workspace_id,
                pack_key="echo",
                scope_type="workspace",
                kind="hint",
                content={"text": "x"},
                status="proposed",
                source="learned",
                metrics={"uses": 4, "helped": 3, "hurt": 1},
            )
        )
    return {"records": made}


async def test_every_metric_matches_the_constructed_data(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    await _build(env, world)
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        agent = await s.get(Agent, env.agent.id)
        assert agent is not None
        h = await health.compute(s, admin, agent, env.packs, 30)
    assert h.jobs == 5 and h.items == 4
    assert h.success_rate == 0.75
    assert h.median_active_seconds == 25.0
    assert h.median_waiting_seconds == 225.0  # 90, 180, 270, 360
    assert h.asks_per_item == 0.5
    assert h.median_answer_seconds == 60.0
    assert h.human_touch_rate == 0.25
    assert h.auto_approved_rate == 0.25
    assert h.cost_per_item_usd == pytest.approx(0.125)  # 5 runs at $0.10, over 4 items
    assert h.skills is not None
    assert (h.skills.active, h.skills.proposed, h.skills.helped, h.skills.hurt) == (2, 1, 3, 1)
    assert h.time_saved_minutes == 21.0  # 6 min for each of 3 untouched, half that for 1 corrected
    assert h.detail is True
    assert h.top_corrected_fields == [("number", 1)]
    assert h.top_failure_reasons == [("Boom happened", 1)]
    assert h.calibration is not None and h.calibration.note == "Not enough reviewed items yet"


async def test_calibration_with_enough_reviewed_items(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    built = await _build(env, world)
    impl = env.packs.packs["echo"].record_type("echo_bill")
    agent_ctx = await _agent_ctx(env)
    project_id = world.project.id
    run_id = None
    async with env.uow.transaction() as s:
        first = await s.get(Record, built["records"][0])
        assert first is not None
        run_id = first.run_id
    corrected = []
    for i in range(20):
        async with env.uow.transaction() as s:
            r = await records.create_record(
                s, agent_ctx, impl, project_id=project_id, data=bill(number=f"C-{i}")
            )
            r.run_id, r.status, r.confidence = run_id, "approved", Decimal("0.9")
            if i < 5:
                corrected.append(r.id)
                s.add(
                    RecordVersion(
                        workspace_id=r.workspace_id,
                        record_id=r.id,
                        version=2,
                        data={},
                        provenance={},
                        checks=[],
                        status="approved",
                        via="review",
                        change={"ops": [{"op": "set", "path": "total"}], "fields": ["total"]},
                    )
                )
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        agent = await s.get(Agent, env.agent.id)
        assert agent is not None
        h = await health.compute(s, admin, agent, env.packs, 30)
    assert h.calibration is not None and h.calibration.reviewed == 20
    [band] = h.calibration.bands
    assert (band.band, band.items, band.predicted, band.actual) == ("0.85-0.95", 20, 0.9, 0.75)


async def test_members_see_the_summary_and_guests_nothing(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    await _build(env, world)
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.momentum.packs = env.packs
        clients = Clients(app)
        ana = await clients("ana")
        r = (await ana.get(f"{B}/agents/{env.agent.id}/health", params={"days": 30})).json()
        assert r["detail"] is False and r["items"] == 4
        assert r["calibration"] is None and r["top_corrected_fields"] is None
        admin = await clients("admin")
        r = (await admin.get(f"{B}/agents/{env.agent.id}/health")).json()
        assert r["detail"] is True and r["top_failure_reasons"] == [["Boom happened", 1]]
        await clients.close()
