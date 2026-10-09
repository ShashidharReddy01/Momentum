"""Phase 7.6 S76-05 (spec §7.1): entities (vendors…). Members only, never guests; bank details
only as "•••• 4821" (the fingerprint is never sent)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut
from momentum.core.activity import Activity
from momentum.core.errors import Conflict
from momentum.domain.entities import service
from momentum.domain.entities.service import EntityOut, entity_out

router = APIRouter(tags=["entities"])


class EntityPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=300)
    attributes: dict[str, Any] | None = None
    expected_version: int | None = Field(default=None, ge=1)


class AliasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str = Field(min_length=1, max_length=300)


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    into_id: uuid.UUID


def _impl(runtime: Any, type: str) -> Any:
    registry = getattr(runtime, "packs", None)
    impl = registry.entity_type(type) if registry is not None else None
    if impl is None:
        raise Conflict(f"The {type} type is not available on this server", code="type_unavailable")
    return impl


@router.get("/entities", response_model=ListOut[EntityOut], summary="Entities (vendors…)")
async def list_entities(
    ctx: CtxDep,
    uow: UowDep,
    type: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default="active", max_length=12),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListOut[EntityOut]:
    async with uow.transaction() as s:
        rows = await service.list_entities(s, ctx, type=type, q=q, status=status, limit=limit)
        return ListOut(data=[entity_out(e) for e in rows])


@router.get("/entities/{entity_id}", response_model=EntityOut, summary="One entity")
async def get_entity(entity_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> EntityOut:
    async with uow.transaction() as s:
        return entity_out(await service.get_entity(s, ctx, entity_id))


class EntityActivityOut(BaseModel):
    id: uuid.UUID
    verb: str
    actor_id: uuid.UUID | None
    actor_kind: str
    diff: dict[str, Any]
    created_at: datetime


@router.get(
    "/entities/{entity_id}/activity",
    response_model=ListOut[EntityActivityOut],
    summary="What happened to an entity, newest first (S76-08, its page's timeline)",
)
async def entity_activity(
    entity_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[EntityActivityOut]:
    async with uow.transaction() as s:
        e = await service.get_entity(s, ctx, entity_id)
        rows = (
            await s.execute(
                select(Activity)
                .where(
                    Activity.workspace_id == ctx.workspace_id,
                    Activity.entity_type == "entity",
                    Activity.entity_id == e.id,
                )
                .order_by(Activity.id.desc())
                .limit(50)
            )
        ).scalars()
        return ListOut(
            data=[
                EntityActivityOut(
                    id=a.id,
                    verb=a.verb,
                    actor_id=a.actor_id,
                    actor_kind=a.actor_kind,
                    diff=a.diff or {},
                    created_at=a.created_at,
                )
                for a in rows
            ]
        )


@router.patch(
    "/entities/{entity_id}",
    response_model=EntityOut,
    summary="Rename an entity or change its attributes (validated by its type)",
)
async def patch_entity(
    entity_id: uuid.UUID, body: EntityPatchIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> EntityOut:
    async with uow.transaction() as s:
        e = await service.get_entity(s, ctx, entity_id)
        e = await service.update_entity(
            s,
            ctx,
            _impl(runtime, e.type),
            entity_id,
            name=body.name,
            attributes=body.attributes,
            expected_version=body.expected_version,
        )
        return entity_out(e)


@router.post("/entities/{entity_id}/aliases", response_model=EntityOut, summary="Add an alias")
async def add_alias(entity_id: uuid.UUID, body: AliasIn, ctx: CtxDep, uow: UowDep) -> EntityOut:
    async with uow.transaction() as s:
        return entity_out(await service.add_alias(s, ctx, entity_id, body.alias))


@router.post(
    "/entities/{entity_id}/merge",
    response_model=EntityOut,
    summary="Merge into another entity: records, aliases and skills move (admins, stewards)",
)
async def merge(entity_id: uuid.UUID, body: MergeIn, ctx: CtxDep, uow: UowDep) -> EntityOut:
    async with uow.transaction() as s:
        return entity_out(await service.merge(s, ctx, entity_id, body.into_id))


@router.post(
    "/entities/{entity_id}/archive",
    response_model=EntityOut,
    summary="Archive an entity (admins, stewards)",
)
async def archive(entity_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> EntityOut:
    async with uow.transaction() as s:
        return entity_out(await service.archive(s, ctx, entity_id))
