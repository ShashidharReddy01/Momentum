"""Workspace memory (S3.1.5): short, admin-curated facts injected into Mo's prompts.

Who may edit: workspace bullets need a workspace admin; team bullets a team lead (or admin);
project bullets a project admin. Anyone who can see the scope can read its bullets (they reach
their prompts anyway). Edits are ordinary mutations: activity with undo, and an outbox event.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import AiMemory
from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, require
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    get_visible_team,
    require_project_role,
    require_team_manager,
)

Scope = Literal["workspace", "team", "project"]
MAX_TEXT = 300
MAX_PER_SCOPE = 50


async def _check_scope(
    session: AsyncSession, ctx: Ctx, scope: str, scope_id: uuid.UUID | None, *, write: bool
) -> None:
    if scope == "workspace":
        if scope_id is not None:
            raise ValidationFailed("Workspace memory has no scope id")
        if write:
            require(ctx, Action.WORKSPACE_ADMIN)
        return
    if scope_id is None:
        raise ValidationFailed(f"{scope.capitalize()} memory needs a {scope} id")
    if scope == "team":
        team = await get_visible_team(session, ctx, scope_id)
        if write:
            await require_team_manager(session, ctx, team)
        return
    if scope == "project":
        _, role = await get_visible_project(session, ctx, scope_id)
        if write:
            require_project_role(role, "admin", "edit this project's AI memory")
        return
    raise ValidationFailed(f"Unknown memory scope {scope}")


def _clean(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise ValidationFailed("A memory bullet can't be empty")
    if len(text) > MAX_TEXT:
        raise ValidationFailed(f"Keep a memory bullet under {MAX_TEXT} characters")
    return text


def _channels(ctx: Ctx, m: AiMemory) -> list[str]:
    return [f"{m.scope}:{m.scope_id or ctx.workspace_id}"]


async def list_memory(
    session: AsyncSession, ctx: Ctx, scope: Scope = "workspace", scope_id: uuid.UUID | None = None
) -> list[AiMemory]:
    await _check_scope(session, ctx, scope, scope_id, write=False)
    stmt = select(AiMemory).where(
        AiMemory.workspace_id == ctx.workspace_id,
        AiMemory.scope == scope,
        AiMemory.deleted_at.is_(None),
    )
    stmt = stmt.where(
        AiMemory.scope_id.is_(None) if scope_id is None else AiMemory.scope_id == scope_id
    )
    return list((await session.execute(stmt.order_by(AiMemory.created_at, AiMemory.id))).scalars())


async def _get(session: AsyncSession, ctx: Ctx, memory_id: uuid.UUID) -> AiMemory:
    m = await session.get(AiMemory, memory_id)
    if m is None or m.workspace_id != ctx.workspace_id or m.deleted_at is not None:
        raise NotFound("Memory bullet not found")
    return m


async def create_memory(
    session: AsyncSession, ctx: Ctx, scope: Scope, scope_id: uuid.UUID | None, text: str
) -> Mutation[AiMemory]:
    await _check_scope(session, ctx, scope, scope_id, write=True)
    text = _clean(text)
    count = (
        await session.execute(
            select(func.count())
            .select_from(AiMemory)
            .where(
                AiMemory.workspace_id == ctx.workspace_id,
                AiMemory.scope == scope,
                AiMemory.scope_id.is_(None) if scope_id is None else AiMemory.scope_id == scope_id,
                AiMemory.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if count >= MAX_PER_SCOPE:
        raise ValidationFailed(f"At most {MAX_PER_SCOPE} bullets here; remove one first")
    m = AiMemory(
        workspace_id=ctx.workspace_id,
        scope=scope,
        scope_id=scope_id,
        text=text,
        created_by=ctx.actor.id,
    )
    session.add(m)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="ai_memory",
        entity_id=m.id,
        verb="ai_memory.created",
        changes={"text": (None, text)},
        undo=undo_op("ai_memory.delete", memory_id=m.id),
    )
    await emit(
        session,
        ctx,
        type="ai_memory.changed",
        entity_type="ai_memory",
        entity_id=m.id,
        data={"scope": scope},
        channels=_channels(ctx, m),
        activity_id=act.id,
    )
    await session.refresh(m)  # server-side timestamps
    return Mutation(m, act.id)


async def update_memory(
    session: AsyncSession, ctx: Ctx, memory_id: uuid.UUID, text: str
) -> Mutation[AiMemory]:
    m = await _get(session, ctx, memory_id)
    await _check_scope(session, ctx, m.scope, m.scope_id, write=True)
    text = _clean(text)
    if text == m.text:
        return Mutation(m)
    old, m.text = m.text, text
    act = await record_activity(
        session,
        ctx,
        entity_type="ai_memory",
        entity_id=m.id,
        verb="ai_memory.updated",
        changes={"text": (old, text)},
        undo=undo_op("ai_memory.set_text", memory_id=m.id, text=old, expect=text),
    )
    await emit(
        session,
        ctx,
        type="ai_memory.changed",
        entity_type="ai_memory",
        entity_id=m.id,
        data={"scope": m.scope},
        channels=_channels(ctx, m),
        activity_id=act.id,
    )
    await session.flush()
    await session.refresh(m)  # server-side timestamps
    return Mutation(m, act.id)


async def delete_memory(
    session: AsyncSession, ctx: Ctx, memory_id: uuid.UUID
) -> Mutation[AiMemory]:
    m = await _get(session, ctx, memory_id)
    await _check_scope(session, ctx, m.scope, m.scope_id, write=True)
    m.deleted_at = datetime.now(UTC)
    act = await record_activity(
        session,
        ctx,
        entity_type="ai_memory",
        entity_id=m.id,
        verb="ai_memory.deleted",
        changes={"text": (m.text, None)},
        undo=undo_op("ai_memory.restore", memory_id=m.id),
    )
    await emit(
        session,
        ctx,
        type="ai_memory.changed",
        entity_type="ai_memory",
        entity_id=m.id,
        data={"scope": m.scope},
        channels=_channels(ctx, m),
        activity_id=act.id,
    )
    await session.flush()
    await session.refresh(m)  # server-side timestamps
    return Mutation(m, act.id)


async def memory_for(
    session: AsyncSession, ctx: Ctx, *, project_id: uuid.UUID | None = None
) -> list[str]:
    """The bullets a prompt for ``ctx.actor`` should carry: the workspace's, plus the team's and
    the project's when the prompt is about a project the actor can see."""
    stmt = select(AiMemory.text).where(
        AiMemory.workspace_id == ctx.workspace_id,
        AiMemory.deleted_at.is_(None),
        AiMemory.scope == "workspace",
    )
    bullets = list(
        (await session.execute(stmt.order_by(AiMemory.created_at, AiMemory.id))).scalars()
    )
    if project_id is not None:
        try:
            project, _ = await get_visible_project(session, ctx, project_id)
        except NotFound:
            return bullets
        for scope, sid in (("team", project.team_id), ("project", project.id)):
            bullets += list(
                (
                    await session.execute(
                        select(AiMemory.text)
                        .where(
                            AiMemory.workspace_id == ctx.workspace_id,
                            AiMemory.deleted_at.is_(None),
                            AiMemory.scope == scope,
                            AiMemory.scope_id == sid,
                        )
                        .order_by(AiMemory.created_at, AiMemory.id)
                    )
                ).scalars()
            )
    return bullets


# ---------------- undo ----------------


def _mid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["memory_id"]))


@undo_handler("ai_memory.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await delete_memory(session, ctx, _mid(args))


@undo_handler("ai_memory.set_text")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    m = await _get(session, ctx, _mid(args))
    if m.text != args["expect"]:
        raise UndoConflict("This memory bullet changed after your edit")
    await update_memory(session, ctx, m.id, str(args["text"]))


@undo_handler("ai_memory.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    m = await session.get(AiMemory, _mid(args))
    if m is None or m.workspace_id != ctx.workspace_id:
        raise NotFound("Memory bullet not found")
    await _check_scope(session, ctx, m.scope, m.scope_id, write=True)
    m.deleted_at = None
    await emit(
        session,
        ctx,
        type="ai_memory.changed",
        entity_type="ai_memory",
        entity_id=m.id,
        data={"scope": m.scope},
        channels=_channels(ctx, m),
    )
    await session.flush()
