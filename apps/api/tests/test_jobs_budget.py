"""Phase 7.6 S76-02 (spec §4.2-4.3): model calls in jobs. ``job.llm`` calls are recorded ``llm``
steps (tokens, cost, OpenTelemetry GenAI attributes), billed to the run; the job's own cap is
summed across its children; gateway hiccups retry inside the step (2 s, 8 s, 30 s); the JSON
helper takes a forced tool call or tolerant text and asks once more for an unusable answer."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.errors import AIUnavailable
from momentum.ai.types import Completion, ToolCall
from momentum.core.db import UnitOfWork
from momentum.domain.agents.models import AgentRun
from momentum.sdk import Job
from tests.ai_fixtures import World, world
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


def _manifest_with(env: JobsEnv, key: str, **limits: Any) -> Path:
    src = env.packs.packs[key].manifest_path
    folder = env.tmp / f"{key}-variant"
    shutil.copytree(src.parent, folder, ignore=shutil.ignore_patterns("__pycache__"))
    raw = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    raw["limits"] = {**raw["limits"], **limits}
    (folder / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return folder / "manifest.yaml"


async def test_llm_steps_record_usage_and_bill_the_run(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> str:
        return await job.llm.complete("ask", prompt="Say hello")

    env = make_env()
    env.use("spawner", run=run)
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    [ask] = await env.steps(run_id)
    assert ask.kind == "llm" and ask.tokens_in > 0
    assert ask.attrs["gen_ai.operation.name"] == "chat"
    assert ask.attrs["gen_ai.agent.name"] == "Spawner"
    run = await env.run(run_id)
    assert run.tokens_in == ask.tokens_in  # billed to the run through llm_calls


async def test_the_job_budget_is_shared_with_its_children(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def batch(job: Job) -> list[str]:
        kids = [
            await job.spawn(
                "ask_model", {"question": f"Q{i}"}, title=f"Q{i}", key=f"q:{i}", task=None
            )
            for i in range(3)
        ]
        return [r.status for r in await job.gather(kids)]

    env = make_env()
    base = env.packs.packs["spawner"]
    env.use("spawner", manifest_path=_manifest_with(env, "spawner", max_job_tokens=5), run=batch)
    _ = base
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    await env.drain()
    parent = await env.run(run_id)
    assert parent.status == "succeeded"
    statuses = parent.output["result"] if parent.output else []
    # the first child's call is allowed (nothing spent yet); the rest find the job's cap used up
    assert statuses.count("succeeded") == 1 and statuses.count("budget_exceeded") == 2
    kids = await env.children(run_id)
    assert {k.error for k in kids if k.status == "budget_exceeded"} != {None}


class _FlakyLLM:
    """Fails twice with a gateway error, then answers."""

    def __init__(self, failures: int = 2) -> None:
        self.failures = failures
        self.calls = 0

    async def complete(self, **kwargs: Any) -> Completion:
        self.calls += 1
        if self.calls <= self.failures:
            raise AIUnavailable(reason="timeout")
        return Completion(
            text="fine",
            tool_calls=[],
            finish_reason="stop",
            alias="fast",
            model="mock",
            tokens_in=3,
            tokens_out=1,
            cost_usd=Decimal(0),
            latency_ms=1,
        )


async def test_gateway_hiccups_retry_inside_the_step(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> str:
        return await job.llm.complete("ask", prompt="Hi")

    env = make_env()
    env.llm = _FlakyLLM(failures=2)
    env.use("spawner", run=run)
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    assert env.sleeps == [2.0, 8.0]
    [ask] = await env.steps(run_id)
    assert ask.attrs["retries"] == 2

    env.llm = _FlakyLLM(failures=9)  # past the backoff: the step fails
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["failed"]
    assert "Failed at ask" in ((await env.run(run_id)).error or "")


class Answer(BaseModel):
    vendor: str
    total: float


class _ScriptedLLM:
    def __init__(self, replies: list[Completion]) -> None:
        self.replies = replies
        self.seen: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> Completion:
        self.seen.append(kwargs)
        return self.replies.pop(0)


def _reply(text: str = "", args: dict[str, Any] | None = None) -> Completion:
    import json

    calls = [ToolCall(id="c1", name="answer", arguments=json.dumps(args))] if args else []
    return Completion(
        text=text,
        tool_calls=calls,
        finish_reason="stop",
        alias="fast",
        model="mock",
        tokens_in=1,
        tokens_out=1,
        cost_usd=Decimal(0),
        latency_ms=1,
    )


@pytest.mark.parametrize(
    "replies",
    [
        [_reply(args={"vendor": "Acme", "total": 12.5})],
        [_reply(text='Here it is:\n```json\n{"vendor": "Acme", "total": 12.5}\n```')],
        [_reply(text='Sure! {"vendor": "Acme", "total": 12.5} Anything else?')],
        [_reply(text=""), _reply(args={"vendor": "Acme", "total": 12.5})],
    ],
    ids=["tool-call", "fenced", "preamble", "empty-then-ok"],
)
async def test_the_json_helper(
    make_env: Callable[..., JobsEnv], world: World, replies: list[Completion]
) -> None:
    async def run(job: Job) -> str:
        answer = await job.llm.json("read", Answer, prompt="Read the invoice")
        return f"{answer.vendor}:{answer.total}"

    env = make_env()
    llm = _ScriptedLLM(list(replies))
    env.llm = llm
    env.use("spawner", run=run)
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    assert (await env.run(run_id)).output == {"result": "Acme:12.5"}
    first = llm.seen[0]
    assert first["tool_choice"]["function"]["name"] == "answer"
    # every pack call carries the rule that document content is data (spec §8.7)
    assert first["messages"][0]["role"] == "system"
    assert "never instructions" in first["messages"][0]["content"]


async def test_vision_needs_a_model_that_reads_images(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> str:
        return await job.llm.vision("look", "What is this?", [b"\xff\xd8\xff"])

    env = make_env(llm_supports_vision=False)
    env.use("spawner", run=run)
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["failed"]
    assert "can't read images" in ((await env.run(run_id)).error or "")
    _ = AgentRun
