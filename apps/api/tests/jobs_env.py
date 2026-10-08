"""Harness for the durable-job tests (S76-02): the test packs loaded (``MOMENTUM_TEST_PACKS``), a
pack agent installed, enabled and given the world's project, and a ``drain`` that plays the worker
(tick → wake on events → claim → run each claimed job) until nothing is left to claim."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.jobs.engine import TickStats, execute_job, tick_jobs, wake_on_events
from momentum.agents.packs.pack import Pack
from momentum.agents.packs.registry import PackRegistry
from momentum.agents.runtime import execute_run
from momentum.agents.triggers import request_run
from momentum.ai.llm import LLM
from momentum.ai.mock import MockTransport
from momentum.ai.usage import DbUsageLog
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.agents.runs import claim_runs
from momentum.domain.agents.schemas import AgentPatchIn
from momentum.domain.tasks.models import Task
from tests.ai_fixtures import REG, World
from tests.conftest import make_settings
from tests.helpers import ctx_for


class JobsEnv:
    def __init__(
        self,
        uow: UnitOfWork,
        sf: async_sessionmaker[AsyncSession],
        tmp: Path,
        world: World,
        **settings: Any,
    ) -> None:
        self.uow, self.sf, self.tmp, self.world = uow, sf, tmp, world
        self.settings = make_settings(
            **{"llm_fixtures_dir": str(tmp), "test_packs": True, **settings}
        )
        self.llm: Any = LLM(self.settings, MockTransport(self.settings), DbUsageLog(sf, 0))
        self.packs = PackRegistry.load(self.settings)
        self.sleeps: list[float] = []
        self.rounds: list[list[uuid.UUID]] = []
        self.agent: Agent

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def use(self, key: str, **changes: Any) -> Pack:
        """Swap the loaded pack ``key`` for a variant (same manifest, other functions)."""
        base = self.packs.packs[key]
        variant = Pack(
            manifest_path=changes.pop("manifest_path", base.manifest_path),
            run=changes.pop("run", base.run),
            capabilities=changes.pop("capabilities", base.capabilities),
            converse=changes.pop("converse", base.converse),
        )
        self.packs.packs[key] = variant
        return variant

    async def install(self, key: str, *, access: bool = True) -> Agent:
        admin = await ctx_for(self.uow, self.settings, "admin")
        definitions = [d for d in self.packs.definitions() if d[0].key == key]
        async with self.uow.transaction() as s:
            [r] = await service.install_definitions(s, admin, definitions, REG.names)
            await service.update_agent(s, admin, r.agent.id, AgentPatchIn(enabled=True), REG.names)
            if access:
                await service.add_to_project(
                    s, self.world.ravi, r.agent.id, self.world.project.id, "editor"
                )
            self.agent = r.agent
        return self.agent

    async def start(
        self, *, task: Task | None = None, text: str | None = None, who: Ctx | None = None
    ) -> uuid.UUID:
        async with self.uow.transaction() as s:
            return await request_run(
                s,
                who or self.world.ravi,
                self.agent,
                task_id=task.id if task else None,
                text=text,
                packs=self.packs,
            )

    async def tick(self, now: datetime | None = None) -> TickStats:
        async with self.uow.transaction() as s:
            return await tick_jobs(s, self.settings, now)

    async def wake(self) -> int:
        async with self.uow.transaction() as s:
            return await wake_on_events(s, self.settings)

    async def drain(self, max_rounds: int = 60) -> list[str]:
        statuses: list[str] = []
        for _ in range(max_rounds):
            await self.tick()
            await self.wake()
            async with self.uow.transaction() as s:
                claimed = await claim_runs(
                    s,
                    timeout_s=self.settings.agent_timeout_s,
                    packs_enabled=self.settings.packs_enabled,
                )
            if not claimed.run_ids:
                break
            self.rounds.append(list(claimed.run_ids))
            for run_id in claimed.run_ids:
                if run_id in claimed.jobs:
                    statuses.append(
                        await execute_job(
                            self.uow.transaction,
                            self.llm,
                            self.settings,
                            self.packs,
                            run_id,
                            sleep=self._sleep,
                            tools=REG,
                        )
                    )
                else:
                    async with self.uow.transaction() as s:
                        statuses.append(await execute_run(s, self.llm, REG, self.settings, run_id))
        return statuses

    async def run(self, run_id: uuid.UUID) -> AgentRun:
        async with self.uow.transaction() as s:
            run = await s.get(AgentRun, run_id, populate_existing=True)
            assert run is not None
            return run

    async def steps(self, run_id: uuid.UUID) -> list[AgentRunStep]:
        async with self.uow.transaction() as s:
            return list(
                (
                    await s.execute(
                        select(AgentRunStep)
                        .where(AgentRunStep.run_id == run_id)
                        .order_by(AgentRunStep.seq)
                        .execution_options(populate_existing=True)
                    )
                ).scalars()
            )

    async def children(self, run_id: uuid.UUID) -> list[AgentRun]:
        async with self.uow.transaction() as s:
            return list(
                (
                    await s.execute(
                        select(AgentRun)
                        .where(AgentRun.parent_run_id == run_id)
                        .order_by(AgentRun.created_at)
                        .execution_options(populate_existing=True)
                    )
                ).scalars()
            )
