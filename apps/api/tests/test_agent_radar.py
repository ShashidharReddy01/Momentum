"""S5.3.7 Radar: heuristic risk signals in code, a note on the project's overview (readable by
anyone who can see the project), a line in the owner's Pulse digest, no model call when there's
nothing to flag."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from momentum.agents.loader import load_definitions
from momentum.ai.models import LlmCall
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import world
from tests.helpers import Clients
from tests.test_agent_runtime import Env, make_env

_ = (make_env, world)
RADAR = next(d for d, _s in load_definitions() if d.key == "risk_watcher")
PULSE = next(d for d, _s in load_definitions() if d.key == "daily_digest")
TODAY = datetime.now(UTC).date()


async def _run(env: Env, key: str = "k") -> None:
    async with env.uow.transaction() as s:
        trigger = {"type": "schedule", "project_id": str(env.world.project.id), "timezone": "UTC"}
        await enqueue_run(s, env.agent, trigger, key)
    assert await env.drain() == ["succeeded"]


async def _calls(env: Env) -> int:
    async with env.uow.transaction() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(LlmCall)
                .where(LlmCall.feature == "agent:risk_watcher")
            )
            or 0
        )


async def test_a_calm_project_gets_a_none_note_without_a_model_call(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    env = make_env()
    await env.install(RADAR)
    await _run(env)
    assert await _calls(env) == 0
    ravi = await as_user("ravi")
    note = (await ravi.get(f"/api/v1/projects/{env.world.project.id}/risk")).json()
    assert note["level"] == "none" and note["signals"] == []


async def test_signals_make_a_note_on_the_overview_and_in_the_owners_digest(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    env = make_env(llm_fixtures_dir="")  # the packaged mock note
    await env.install(RADAR)
    w = env.world
    async with env.uow.transaction() as s:
        # two overdue (copy, faq), and copy waits on faq, which is overdue: a chain
        for t in (w.copy, w.faq):
            await tasks.update_task(s, w.ravi, t.id, {"due_on": TODAY - timedelta(days=3)})
        await tasks.add_dependency(s, w.ravi, w.copy.id, w.faq.id)
        # nobody on a task due tomorrow
        soon = (await tasks.create_task(s, w.ravi, w.project.id, "Book the venue")).entity[0]
        await tasks.update_task(s, w.ravi, soon.id, {"due_on": TODAY + timedelta(days=1)})
    await _run(env)
    assert await _calls(env) == 1
    ravi, tom = await as_user("ravi"), await as_user("tom")
    note = (await ravi.get(f"/api/v1/projects/{w.project.id}/risk")).json()
    kinds = {sig["kind"] for sig in note["signals"]}
    assert kinds == {"overdue", "blocked", "unassigned"}
    assert note["level"] in ("medium", "high")
    assert note["summary"].startswith("(mock) Start with")
    assert any(
        f"T-{soon.number} Book the venue" in t for sig in note["signals"] for t in sig["tasks"]
    )
    # someone who can't see the project can't read its note
    assert (await tom.get(f"/api/v1/projects/{w.project.id}/risk")).status_code == 404

    # the owner's Pulse digest carries the risk line
    pulse_env = make_env(llm_fixtures_dir="")
    await pulse_env.install(PULSE)
    async with pulse_env.uow.transaction() as s:
        trigger = {"type": "schedule", "for_user_id": str(w.ravi.actor.id)}
        await enqueue_run(s, pulse_env.agent, trigger, "p")
    assert await pulse_env.drain() == ["succeeded"]
    [run] = await pulse_env.runs()
    assert "Project risks (Radar) (1):" in (run.output or {})["text"]
