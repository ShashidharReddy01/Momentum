"""S5.3.4 Nudge: which tasks get a reminder (overdue by more than a day, or stalled 5 days),
the limits (once per 2 days, escalate on the 4th, then stop), and what it respects (snooze per
task, "don't nudge me", waiting on someone else's work)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import update

from momentum.agents.loader import load_definitions
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.comments.models import Comment
from momentum.domain.notifications.schemas import NotificationPrefsIn
from momentum.domain.notifications.service import set_prefs
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from tests.ai_fixtures import world
from tests.helpers import Clients
from tests.test_agent_runtime import Env, _comments, make_env

_ = (make_env, world)
NUDGE = next(d for d, _s in load_definitions() if d.key == "nudger")
TODAY = datetime.now(UTC).date()


async def _run(env: Env, key: str) -> None:
    async with env.uow.transaction() as s:
        trigger = {
            "type": "schedule",
            "project_id": str(env.world.project.id),
            "timezone": "UTC",
            "requested_by": str(env.world.ravi.actor.id),
        }
        await enqueue_run(s, env.agent, trigger, key)
    assert await env.drain() == ["succeeded"]


async def _assign(env: Env, task: Task, who: Any, due: date | None) -> None:
    async with env.uow.transaction() as s:
        await tasks.update_task(
            s, env.world.ravi, task.id, {"assignee_id": who.actor.id, "due_on": due}
        )


async def _nudges(env: Env, task: Task) -> list[Comment]:
    return [c for c in await _comments(env, task.id) if c.author_id == env.account.id]


def _text(c: Comment) -> str:
    return " ".join(
        n.get("text", "") or "@" + n.get("attrs", {}).get("label", "")
        for p in c.body["content"]
        for n in p.get("content", [])
    )


def _mentioned(c: Comment) -> set[str]:
    return {
        n["attrs"]["id"]
        for p in c.body["content"]
        for n in p.get("content", [])
        if n.get("type") == "mention"
    }


async def _age_nudges(env: Env, task: Task, days: int) -> None:
    async with env.uow.transaction() as s:
        await s.execute(
            update(Comment)
            .where(Comment.task_id == task.id, Comment.author_id == env.account.id)
            .values(created_at=Comment.created_at - timedelta(days=days))
        )


async def test_an_overdue_task_gets_one_reminder_every_two_days_then_escalates(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")  # packaged mock: plain templates
    await env.install(NUDGE)
    copy, faq = env.world.copy, env.world.faq
    await _assign(env, copy, env.world.ana, TODAY - timedelta(days=3))
    await _assign(env, faq, env.world.ana, TODAY - timedelta(days=1))  # only a day late: fine
    await _run(env, "d1")
    [first] = await _nudges(env, copy)
    assert await _nudges(env, faq) == []
    assert _mentioned(first) == {str(env.world.ana.actor.id)}
    assert first.is_ai and "3 days overdue" in _text(first)
    await _run(env, "d1b")  # the same day: nothing more
    assert len(await _nudges(env, copy)) == 1
    for n in range(2, 4):  # two more reminders, two days apart
        await _age_nudges(env, copy, 2)
        await _run(env, f"d{n}")
        assert len(await _nudges(env, copy)) == n
    await _age_nudges(env, copy, 2)
    await _run(env, "d4")
    *_, fourth = await _nudges(env, copy)
    assert _mentioned(fourth) == {str(env.world.ana.actor.id), str(env.world.ravi.actor.id)}
    assert "3 reminders" in _text(fourth)
    await _age_nudges(env, copy, 2)
    await _run(env, "d5")  # after escalating, it stops
    assert len(await _nudges(env, copy)) == 4


async def test_snooze_and_dont_nudge_me_are_respected(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    env = make_env(llm_fixtures_dir="")
    await env.install(NUDGE)
    copy = env.world.copy
    await _assign(env, copy, env.world.ana, TODAY - timedelta(days=4))
    ana = await as_user("ana")
    r = await ana.put(
        f"/api/v1/me/tasks/{copy.id}/nudge-snooze",
        json={"until": (TODAY + timedelta(days=3)).isoformat()},
    )
    assert r.status_code == 200, r.text
    detail = (await ana.get(f"/api/v1/tasks/{copy.id}")).json()
    assert detail["my_nudge_snoozed_until"] == (TODAY + timedelta(days=3)).isoformat()
    # someone else can't snooze ana's reminders
    ravi = await as_user("ravi")
    other = await ravi.put(f"/api/v1/me/tasks/{copy.id}/nudge-snooze", json={"until": None})
    assert other.status_code == 404
    await _run(env, "a")
    assert await _nudges(env, copy) == []
    await ana.put(f"/api/v1/me/tasks/{copy.id}/nudge-snooze", json={"until": None})
    async with env.uow.transaction() as s:
        await set_prefs(s, env.world.ana, NotificationPrefsIn(nudge_me=False))
    await _run(env, "b")
    assert await _nudges(env, copy) == []
    async with env.uow.transaction() as s:
        await set_prefs(s, env.world.ana, NotificationPrefsIn(nudge_me=True))
    await _run(env, "c")
    assert len(await _nudges(env, copy)) == 1


async def test_waiting_on_someone_else_is_not_nudged_but_stalled_work_is(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")
    await env.install(NUDGE)
    copy, faq = env.world.copy, env.world.faq
    await _assign(env, copy, env.world.ana, TODAY - timedelta(days=5))
    await _assign(env, faq, env.world.ravi, None)
    async with env.uow.transaction() as s:
        await tasks.add_dependency(s, env.world.ravi, copy.id, faq.id)  # copy waits on ravi's faq
        # faq has no due date but nobody touched it for a week
        await s.execute(
            update(Task)
            .where(Task.id == faq.id)
            .values(updated_at=datetime.now(UTC) - timedelta(days=7))
        )
    await _run(env, "a")
    assert await _nudges(env, copy) == []
    [stalled] = await _nudges(env, faq)
    assert "hasn't moved in 7 days" in _text(stalled)


async def test_the_model_phrases_but_cannot_cite_other_tasks(
    make_env: Callable[..., Env], tmp_path: Path
) -> None:
    env = make_env()
    await env.install(NUDGE)
    copy, faq = env.world.copy, env.world.faq
    await _assign(env, copy, env.world.ana, TODAY - timedelta(days=3))
    await _assign(env, faq, env.world.ana, TODAY - timedelta(days=3))
    ck, fk = f"T-{copy.number}", f"T-{faq.number}"
    (tmp_path / "nudge.yaml").write_text(
        yaml.safe_dump(
            {
                "default": {
                    "tool_calls": [
                        {
                            "name": "submit_result",
                            "arguments": {
                                "messages": [
                                    {
                                        "key": ck,
                                        "text": f"(mock) {ck} is a few days late: any help needed?",
                                    },
                                    {"key": fk, "text": f"(mock) {fk} is late, like {ck}."},
                                ]
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    await _run(env, "a")
    [phrased] = await _nudges(env, copy)
    [fallback] = await _nudges(env, faq)
    assert "any help needed?" in _text(phrased)
    assert "(mock)" not in _text(fallback) and "3 days overdue" in _text(fallback)
