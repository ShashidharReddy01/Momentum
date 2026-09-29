"""S5.3.1 Pulse · Daily Digest: per-person schedule at their digest time, lists built from what
they can see, one model line that may cite only those lists, no digest when there's nothing to
report or they turned digests off."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import func, select

from momentum.agents.loader import load_definitions
from momentum.agents.triggers import evaluate_schedules, personal_cron
from momentum.ai.models import LlmCall
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.comments.service import create_comment
from momentum.domain.notifications.models import Notification
from momentum.domain.notifications.schemas import NotificationPrefsIn
from momentum.domain.notifications.service import set_prefs
from momentum.domain.tasks import service as tasks
from momentum.domain.users.models import User
from tests.ai_fixtures import world
from tests.test_agent_runtime import Env, make_env

_ = (make_env, world)
PULSE = next(d for d, _s in load_definitions() if d.key == "daily_digest")


def test_personal_cron_uses_the_persons_digest_time() -> None:
    person = User(prefs={"notifications": {"digest_time": "07:05"}})
    assert personal_cron("30 8 * * 1-5", person, "digest_time") == "5 7 * * 1-5"
    assert personal_cron("30 8 * * 1-5", User(prefs={}), "digest_time") == "30 8 * * 1-5"
    assert personal_cron("30 8 * * 1-5", person, None) == "30 8 * * 1-5"
    bad = User(prefs={"notifications": {"digest_time": "7am"}})
    assert personal_cron("30 8 * * 1-5", bad, "digest_time") == "30 8 * * 1-5"


async def _run_for(env: Env, user_id: Any, key: str = "k") -> str:
    async with env.uow.transaction() as s:
        trigger = {"type": "schedule", "for_user_id": str(user_id), "requested_by": str(user_id)}
        await enqueue_run(s, env.agent, trigger, key)
    [status] = await env.drain()
    return status


async def _digests(env: Env, user_id: Any) -> list[Notification]:
    async with env.uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(Notification).where(
                        Notification.user_id == user_id, Notification.kind == "digest"
                    )
                )
            ).scalars()
        )


async def _calls(env: Env) -> int:
    async with env.uow.transaction() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(LlmCall)
                .where(LlmCall.feature == "agent:daily_digest")
            )
            or 0
        )


async def _setup_tasks(env: Env) -> tuple[str, str]:
    """Ravi: the copy task due today, the FAQ overdue; returns their keys."""
    w = env.world
    today = datetime.now(ZoneInfo(w.ravi.actor.timezone)).date()
    async with env.uow.transaction() as s:
        rid = w.ravi.actor.id
        await tasks.update_task(s, w.ravi, w.copy.id, {"assignee_id": rid, "due_on": today})
        await tasks.update_task(
            s, w.ravi, w.faq.id, {"assignee_id": rid, "due_on": today - timedelta(days=2)}
        )
    return f"T-{w.copy.number}", f"T-{w.faq.number}"


async def test_nothing_to_report_sends_nothing_and_calls_no_model(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(PULSE)
    assert await _run_for(env, env.world.lena.actor.id) == "succeeded"
    assert await _digests(env, env.world.lena.actor.id) == []
    assert await _calls(env) == 0
    [run] = await env.runs()
    assert any("Nothing to report" in s["summary"] for s in run.trace)


async def test_the_digest_lists_what_is_due_and_what_happened(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")  # the packaged mock line
    await env.install(PULSE)
    due, overdue = await _setup_tasks(env)
    async with env.uow.transaction() as s:  # ana mentions ravi
        mention = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "mention",
                            "attrs": {
                                "id": str(env.world.ravi.actor.id),
                                "label": "Ravi",
                                "kind": "user",
                            },
                        },
                        {"type": "text", "text": " can you check the numbers?"},
                    ],
                }
            ],
        }
        await create_comment(s, env.world.ana, env.world.copy.id, mention)
    assert await _run_for(env, env.world.ravi.actor.id) == "succeeded"
    [digest] = await _digests(env, env.world.ravi.actor.id)
    [run] = await env.runs()
    assert digest.entity_type == "agent_run" and digest.entity_id == run.id
    assert "1 due today" in digest.title and "1 overdue" in digest.title
    body = (run.output or {})["text"]
    assert f"Due today (1):\n- {due} Draft pricing copy" in body
    assert f"Overdue (1):\n- {overdue} Draft pricing FAQ" in body
    assert "Mentions (1)" in body and "check the numbers" in body
    assert body.startswith("(mock) Start with")  # the model's line, citing only these keys
    assert await _calls(env) == 1
    # the next digest only reports what's new: the mention is not repeated
    assert await _run_for(env, env.world.ravi.actor.id, "k2") == "succeeded"
    runs = await env.runs()
    assert "Mentions" not in (runs[-1].output or {})["text"]


async def test_a_line_citing_other_tasks_is_dropped(
    make_env: Callable[..., Env], tmp_path: Any
) -> None:
    env = make_env()
    (tmp_path / "agent__daily_digest.yaml").write_text(
        yaml.safe_dump({"default": {"text": "Start with T-99999, it's urgent."}}), encoding="utf-8"
    )
    await env.install(PULSE)
    await _setup_tasks(env)
    assert await _run_for(env, env.world.ravi.actor.id) == "succeeded"
    [run] = await env.runs()
    assert not (run.output or {})["text"].startswith("Start with")
    assert any("outside the digest" in s["summary"] for s in run.trace)


async def test_digests_turned_off_cost_nothing(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(PULSE)
    await _setup_tasks(env)
    async with env.uow.transaction() as s:
        await set_prefs(s, env.world.ravi, NotificationPrefsIn(digest="off"))
    assert await _run_for(env, env.world.ravi.actor.id) == "succeeded"
    assert await _digests(env, env.world.ravi.actor.id) == []
    assert await _calls(env) == 0


async def test_each_person_gets_it_at_their_own_digest_time(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(PULSE)
    async with env.uow.transaction() as s:
        await set_prefs(s, env.world.ravi, NotificationPrefsIn(digest_time="07:05"))
        ravi = await s.get(User, env.world.ravi.actor.id)
        assert ravi is not None
        tz = ZoneInfo(ravi.timezone)
    monday = datetime(2026, 10, 5, 7, 5, tzinfo=tz).astimezone(UTC)
    async with env.uow.transaction() as s:
        await evaluate_schedules(s, env.settings, monday)
    async with env.uow.transaction() as s:
        runs = list(
            (await s.execute(select(AgentRun).where(AgentRun.agent_id == env.agent.id))).scalars()
        )
    people = {r.trigger["for_user_id"] for r in runs}
    assert str(env.world.ravi.actor.id) in people
    # someone without a digest time isn't woken at ravi's time (unless theirs is 08:30 there)
    assert (
        str(env.world.ana.actor.id) not in people or env.world.ana.actor.timezone != ravi.timezone
    )


def test_schedules_without_at_hash_as_before() -> None:
    """Adding ``at`` must not change stored schedules (installed agents would turn drifted)."""
    from momentum.domain.agents.service import canonical

    herald = next(d for d, _s in load_definitions() if d.key == "status_reporter")
    [schedule] = [t for t in canonical(herald)["triggers"] if t["type"] == "schedule"]
    assert set(schedule) == {"type", "cron", "timezone"}
    [pulse] = canonical(PULSE)["triggers"]
    assert pulse["at"] == "digest_time"
