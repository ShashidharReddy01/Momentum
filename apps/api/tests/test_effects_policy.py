"""Phase 7.6 S76-06 (spec §8): governance. The policy engine; consent for setting-gated event and
schedule triggers (the admin who switched it on named on the run); declared effects and the
service guards an agent can never pass; kill switches; classified packs' traces scrubbed; the
injection-eval rule of ``packs check``; OpenTelemetry names on every step."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.packs.check import check_packs, has_injection_eval
from momentum.agents.packs.pack import Pack
from momentum.agents.triggers import consume_events, evaluate_schedules
from momentum.core.db import UnitOfWork
from momentum.domain.agents import service as agents_service
from momentum.domain.pack_settings.service import put_values
from momentum.domain.tasks import service as tasks
from momentum.sdk import Job, step
from momentum.sdk.policy import Decision, Policy, Rule
from tests.ai_fixtures import REG, World, world
from tests.conftest import make_settings
from tests.helpers import ctx_for
from tests.jobs_env import JobsEnv

_ = world


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


# ---------- the policy engine ----------


POLICY = Policy(
    "test.invoice",
    rules=[
        Rule(
            "duplicate",
            when=lambda c: c.dupe,
            decide="hold",
            route="requester",
            reason="Looks like {dupe_of}.",
        ),
        Rule(
            "material",
            when=lambda c: c.amount >= 1000,
            decide="require_human",
            route="approver",
            reason="{amount} {currency} is material.",
        ),
        Rule("auto_ok", when=lambda c: c.auto, decide="allow", reason="Auto-approval is on."),
    ],
    default=Decision(
        "require_human", route="approver", rule_id="default_human", reason="Auto-approval is off."
    ),
)


def _ctx(**over: Any) -> SimpleNamespace:
    base = {"dupe": False, "dupe_of": "", "amount": 10, "currency": "USD", "auto": False}
    base.update(over)
    return SimpleNamespace(**base)


def test_the_first_rule_that_fires_decides_and_every_rule_is_traced() -> None:
    d = POLICY.evaluate(_ctx(amount=1500, auto=True))
    assert (d.decision, d.rule_id, d.route) == ("require_human", "material", "approver")
    assert d.reason == "1500 USD is material."
    assert [e["fired"] for e in d.evaluated] == [False, True, True]  # all of them, in order
    assert POLICY.evaluate(_ctx(auto=True)).decision == "allow"
    held = POLICY.evaluate(_ctx(dupe=True, dupe_of="INV-1", auto=True))
    assert (held.decision, held.reason) == ("hold", "Looks like INV-1.")
    default = POLICY.evaluate(_ctx())
    assert (default.decision, default.rule_id) == ("require_human", "default_human")
    assert default.as_dict()["evaluated"] == [
        {"rule_id": "duplicate", "fired": False},
        {"rule_id": "material", "fired": False},
        {"rule_id": "auto_ok", "fired": False},
    ]


def test_a_rule_that_breaks_hands_the_decision_to_a_person() -> None:
    p = Policy("x", rules=[Rule("boom", when=lambda c: 1 / 0, decide="allow")])
    d = p.evaluate(_ctx())
    assert d.decision == "require_human" and "couldn't run" in d.reason
    assert d.evaluated[0] == {"rule_id": "boom", "fired": None, "error": "ZeroDivisionError"}
    with pytest.raises(ValueError):
        Rule("bad", when=lambda c: True, decide="maybe")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Policy("dupes", rules=[Rule("a", when=bool, decide="allow")] * 2)


# ---------- consent: setting-gated triggers ----------


def _gated(env: JobsEnv, trigger: dict[str, Any]) -> None:
    base = env.packs.packs["echo"]
    folder = env.tmp / "echo-gated"
    shutil.copytree(base.manifest_path.parent, folder, ignore=shutil.ignore_patterns("__pycache__"))
    raw = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    raw["triggers"] = [trigger]
    (folder / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    env.use("echo", manifest_path=folder / "manifest.yaml")


async def test_an_event_trigger_runs_only_where_its_setting_is_on_and_names_who(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.agents.extensions import attach_file

    env = make_env()
    _gated(env, {"type": "event", "event": "attachment.created", "setting": "watch_uploads"})
    await env.install("echo")
    async with env.uow.transaction() as s:
        await consume_events(s, env.settings, packs=env.packs)  # from now on
    async with env.uow.transaction() as s:
        await attach_file(s, world.ravi, env.settings, world.copy.id, "a.txt", b"one", "text/plain")
    async with env.uow.transaction() as s:
        assert (await consume_events(s, env.settings, packs=env.packs)).queued == 0  # off
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        await put_values(
            s,
            admin,
            env.packs.packs["echo"].settings,
            "echo",
            world.project.id,
            {"watch_uploads": True},
        )
    async with env.uow.transaction() as s:
        await attach_file(s, world.ravi, env.settings, world.copy.id, "b.txt", b"two", "text/plain")
    async with env.uow.transaction() as s:
        assert (await consume_events(s, env.settings, packs=env.packs)).queued == 1
    from sqlalchemy import select

    from momentum.domain.agents.models import AgentRun

    async with env.uow.transaction() as s:
        run = await s.scalar(select(AgentRun).where(AgentRun.agent_id == env.agent.id))
    assert run is not None and run.trigger["consent"]["setting"] == "watch_uploads"
    assert run.trigger["consent"]["by"] == str(admin.actor.id)
    assert run.trigger["consent"]["level"] == "project"


async def test_a_project_schedule_runs_only_where_its_setting_is_on(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    _gated(
        env, {"type": "schedule", "cron": "* * * * *", "per": "project", "setting": "watch_uploads"}
    )
    await env.install("echo")
    now = datetime.now(UTC)
    async with env.uow.transaction() as s:
        assert (await evaluate_schedules(s, env.settings, now, packs=env.packs)).queued == 0
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        await put_values(
            s, admin, env.packs.packs["echo"].settings, "echo", None, {"watch_uploads": True}
        )
    async with env.uow.transaction() as s:
        # once per minute evaluated (this one and the one before, in case the tick ran late)
        assert (await evaluate_schedules(s, env.settings, now, packs=env.packs)).queued >= 1


# ---------- effects and guards ----------


async def test_effects_are_declared_and_the_guards_hold(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    attempts: dict[str, str] = {}

    async def run(job: Job) -> dict[str, str]:
        assert job.task_id is not None
        task = job.task_id

        async def try_(name: str, fn: Any) -> None:
            try:
                await job.step(name, fn)
                attempts[name] = "ok"
            except Exception as e:  # the step fails; the job carries on to report it
                attempts[name] = type(e).__name__

        @step
        async def rename_undeclared() -> None:
            await job.effects.tasks.rename(task, "x")  # echo doesn't declare tasks.rename

        @step
        async def complete_someone_elses() -> None:
            await job.effects.tasks.complete_own(task)  # not declared either

        await try_("rename", rename_undeclared)
        await try_("complete", complete_someone_elses)
        return attempts

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    # each undeclared effect raised PackError (a developer error, caught here in tests)
    assert ((await env.run(run_id)).output or {})["result"] == {
        "rename": "PackError",
        "complete": "PackError",
    }


async def test_complete_own_is_only_for_the_agents_own_subtask(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    """Declared (failer) and even assigned to the agent: a task it didn't make isn't its own."""

    async def complete(job: Job) -> None:
        assert job.task_id is not None

        @step
        async def _c() -> None:
            await job.effects.tasks.complete_own(job.task_id)  # type: ignore[arg-type]

        await job.step("c", _c)

    faq_id = world.faq.id
    env2 = make_env()
    env2.use("failer", run=complete)
    await env2.install("failer")
    async with env2.uow.transaction() as s:  # even assigned to it, it isn't its own subtask
        await tasks.update_task(s, world.ravi, faq_id, {"assignee_id": env2.agent.user_id})
    rid = await env2.start(task=SimpleNamespace(id=faq_id))  # type: ignore[arg-type]
    await env2.drain()
    assert "can complete only its own subtasks" in ((await env2.run(rid)).error or "")


async def test_agents_never_delete_or_decide_approvals(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.agents.triggers import agent_ctx
    from momentum.core.errors import Forbidden
    from momentum.domain.users.models import User

    env = make_env()
    await env.install("echo")
    async with env.uow.transaction() as s:
        account = await s.get(User, env.agent.user_id)
        assert account is not None
    ctx = agent_ctx(env.agent, account, env.settings)
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await tasks.delete_task(s, ctx, world.copy.id)


# ---------- kill switches ----------


async def test_taking_the_agent_off_a_project_cancels_its_jobs_there(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> None:
        await job.wait_for_event("w", "task.completed", task_id=job.task_id)

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    rid = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    async with env.uow.transaction() as s:
        await agents_service.remove_from_project(s, world.ravi, env.agent.id, world.project.id)
    run = await env.run(rid)
    assert run.status == "cancelled" and "taken off the project" in (run.error or "")


async def test_with_packs_switched_off_jobs_wait(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    rid = await env.start(task=world.copy, text="hi")
    env.settings = make_settings(
        llm_fixtures_dir=str(env.tmp), test_packs=True, packs_enabled=False
    )
    assert await env.drain() == []  # not claimed
    assert (await env.run(rid)).status == "queued"
    _ = REG


# ---------- classified packs, injection evals, telemetry names ----------


async def test_a_classified_packs_logs_and_errors_are_scrubbed(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> None:
        job.log("Paying GB82 WEST 1234 5698 7654 32 for ap@acme-demo.test")

        @step
        async def boom() -> None:
            raise ValueError("bad total 4111 1111 1111 1111")

        await job.step("boom", boom)

    env = make_env()
    base = env.packs.packs["echo"]
    folder = env.tmp / "echo-fin"
    shutil.copytree(base.manifest_path.parent, folder, ignore=shutil.ignore_patterns("__pycache__"))
    raw = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    raw["data"] = {"classification": "financial"}
    (folder / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    env.use("echo", manifest_path=folder / "manifest.yaml", run=run)
    await env.install("echo")
    rid = await env.start(task=world.copy)
    await env.drain()
    r = await env.run(rid)
    steps = await env.steps(rid)
    text = str(r.trace) + str([s.error for s in steps]) + str(r.error)
    for secret in ("GB82", "ap@acme", "4111 1111"):
        assert secret not in text
    assert "[redacted]" in text


def test_a_pack_reading_external_content_needs_an_injection_eval(tmp_path: Path) -> None:
    from momentum.agents.packs.loader import TEST_PACKS_DIR

    folder = tmp_path / "reader"
    shutil.copytree(TEST_PACKS_DIR / "echo", folder, ignore=shutil.ignore_patterns("__pycache__"))
    raw = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    raw["data"] = {"classification": "internal", "reads_external_content": True}
    (folder / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    pack = Pack(manifest_path=folder / "manifest.yaml")
    assert not has_injection_eval(pack)
    (folder / "evals").mkdir()
    (folder / "evals" / "safety.yaml").write_text(
        yaml.safe_dump({"cases": [{"id": "footer_says_approve", "tags": ["injection"]}]}),
        encoding="utf-8",
    )
    assert has_injection_eval(pack)
    assert not any("injection" in p for p in check_packs(make_settings(test_packs=True)))


async def test_every_step_carries_genai_names(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    rid = await env.start(task=world.copy, text="hi")
    assert await env.drain() == ["succeeded"]
    [reply] = await env.steps(rid)
    assert reply.attrs["gen_ai.operation.name"] == "invoke_agent"
    assert reply.attrs["gen_ai.agent.name"] == "Echo"
