"""Phase 7.6 S76-05 (spec §7, §8.3): a job's memory reads, each a recorded step: ``job.entities``
(match, get, whether a bank account is the one on file), ``job.skills`` (the active skills for
this job, most specific first; using them is counted) and ``job.settings()`` (the pack's settings
for the job's project)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.domain.entities import service as entities
from momentum.domain.skills import service as skills

if TYPE_CHECKING:
    from momentum.agents.jobs.effects import SkillProposal
    from momentum.agents.jobs.job import JobState


class EntityView(BaseModel):
    """An entity as a job sees it: bank details only as "on file" and the last four digits."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    aliases: list[str]
    attributes: dict[str, Any]
    profile: dict[str, Any]
    status: str
    bank_last4: str | None = None


class MatchCandidate(BaseModel):
    id: uuid.UUID
    name: str
    score: float


class EntityMatch(BaseModel):
    entity_id: uuid.UUID | None
    method: str | None
    candidates: list[MatchCandidate]


class SkillView(BaseModel):
    id: uuid.UUID
    kind: str
    scope_type: str
    scope_id: uuid.UUID | None
    field: str | None
    content: dict[str, Any]
    version: int


def _entity_view(e: Any) -> EntityView:
    out = entities.entity_out(e)
    bank = (e.attributes or {}).get("bank") or {}
    return EntityView(
        id=out.id,
        type=out.type,
        key=out.key,
        name=out.name,
        aliases=out.aliases,
        attributes=out.attributes,
        profile=out.profile,
        status=out.status,
        bank_last4=bank.get("last4"),
    )


class JobEntities:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def match(
        self, key: str, type: str, name: str, *, tax_id: str | None = None
    ) -> EntityMatch:
        """Tax id, then exact name or alias, then trigram similarity ≥ 0.6; otherwise candidates
        (ask a person with ``pick_entity`` when two are close)."""
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> EntityMatch:
            m = await entities.match(s, state.workspace_id, type, name, tax_id=tax_id)
            return EntityMatch(
                entity_id=m.entity_id,
                method=m.method,
                candidates=[
                    MatchCandidate(id=c.id, name=c.name, score=c.score) for c in m.candidates
                ],
            )

        return cast(EntityMatch, await state.run_step(key, "step", body, TypeAdapter(EntityMatch)))

    async def get(self, key: str, entity_id: uuid.UUID) -> EntityView:
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> EntityView:
            return _entity_view(await entities.get_entity(s, state.ctx, entity_id))

        return cast(EntityView, await state.run_step(key, "step", body, TypeAdapter(EntityView)))

    async def bank_matches(self, key: str, entity_id: uuid.UUID, account: str) -> bool | None:
        """Whether ``account`` is the one on file for the entity (``None`` when none is). The
        account itself is never recorded: only the answer is."""
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> bool | None:
            return await entities.bank_matches(s, state.ctx, entity_id, account)

        return cast(bool | None, await state.run_step(key, "step", body, TypeAdapter(bool | None)))


class JobSkills:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def for_(
        self,
        key: str,
        *,
        entity_id: uuid.UUID | None = None,
        kinds: list[str] | None = None,
        field: str | None = None,
    ) -> list[SkillView]:
        """Active skills for this job: the entity's, the project's, the workspace's (most
        specific first). Each one returned counts as used."""
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[SkillView]:
            rows = await skills.active_for(
                s,
                state.workspace_id,
                state.pack.key,
                entity_id=entity_id,
                project_id=state.project_id,
                kinds=kinds,
                field=field,
            )
            await skills.record_use(s, [r.id for r in rows])
            return [
                SkillView(
                    id=r.id,
                    kind=r.kind,
                    scope_type=r.scope_type,
                    scope_id=r.scope_id,
                    field=r.field,
                    content=r.content,
                    version=r.version,
                )
                for r in rows
            ]

        return cast(
            list[SkillView],
            await state.run_step(key, "step", body, TypeAdapter(list[SkillView])),
        )

    async def propose(
        self,
        key: str,
        kind: str,
        content: dict[str, Any],
        *,
        scope: str = "workspace",
        scope_id: uuid.UUID | None = None,
        field: str | None = None,
        provenance: dict[str, Any] | None = None,
        record_values: Any = None,
    ) -> SkillProposal:
        """``job.effects.skills.propose`` as its own step."""
        from momentum.agents.jobs.effects import Effects, SkillProposal

        state = self._state

        async def body(_s: AsyncSession, _meta: dict[str, Any]) -> SkillProposal:
            return await Effects(state).skills.propose(
                kind,
                content,
                scope=scope,
                scope_id=scope_id,
                field=field,
                provenance=provenance,
                record_values=record_values,
            )

        return cast(
            SkillProposal, await state.run_step(key, "effect", body, TypeAdapter(SkillProposal))
        )


async def settings(state: JobState, key: str) -> Any:
    """The pack's settings for the job's project (defaults, workspace, project), as its model."""
    from momentum.domain.pack_settings.service import effective_values

    model = state.pack.settings

    async def body(s: AsyncSession, _meta: dict[str, Any]) -> dict[str, Any]:
        return await effective_values(
            s, model, state.workspace_id, state.pack.key, state.project_id
        )

    values = await state.run_step(key, "step", body, TypeAdapter(dict))
    return model.model_validate(values)
