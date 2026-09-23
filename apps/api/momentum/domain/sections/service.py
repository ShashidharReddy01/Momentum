"""Sections: ordered groups inside a project (phase-1.md S1.2.1)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.sections.models import Section

# Hook for the tasks module to move or delete a section's tasks before the section is deleted
# (registered by domain/tasks in S1.2.2; sections must not import tasks).
SectionTasksHandler = Callable[
    [AsyncSession, Ctx, Section, str, uuid.UUID | None], Awaitable[dict[str, Any]]
]
_on_delete_tasks: list[SectionTasksHandler] = []


def on_section_delete(fn: SectionTasksHandler) -> SectionTasksHandler:
    _on_delete_tasks.append(fn)
    return fn


def _channels(project_id: uuid.UUID) -> list[str]:
    return [f"project:{project_id}"]


async def list_sections(session: AsyncSession, project_id: uuid.UUID) -> list[Section]:
    rows = await session.execute(
        select(Section)
        .where(Section.project_id == project_id, Section.deleted_at.is_(None))
        .order_by(Section.position, Section.id)
    )
    return list(rows.scalars())


async def _get_editable(session: AsyncSession, ctx: Ctx, section_id: uuid.UUID) -> Section:
    section = await session.get(Section, section_id)
    if (
        section is None
        or section.deleted_at is not None
        or section.workspace_id != ctx.workspace_id
    ):
        raise NotFound("Section not found")
    _, role = await get_visible_project(session, ctx, section.project_id)
    require_project_role(role, "editor", "change sections")
    return section


async def _neighbor_positions(
    session: AsyncSession,
    project_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
    *,
    exclude: uuid.UUID | None = None,
) -> tuple[str | None, str | None]:
    """Resolve (a, b) positions for inserting after/before a neighbor (or at the end)."""
    sections = [s for s in await list_sections(session, project_id) if s.id != exclude]
    ids = [s.id for s in sections]
    if after_id is not None:
        if after_id not in ids:
            raise NotFound("Neighbor section not found")
        i = ids.index(after_id)
        nxt = sections[i + 1].position if i + 1 < len(sections) else None
        return sections[i].position, nxt
    if before_id is not None:
        if before_id not in ids:
            raise NotFound("Neighbor section not found")
        i = ids.index(before_id)
        prev = sections[i - 1].position if i > 0 else None
        return prev, sections[i].position
    return (sections[-1].position if sections else None), None


async def create_section(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    name: str,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
) -> Mutation[Section]:
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "add sections")
    if not name.strip():
        raise ValidationFailed("Section name can't be empty")
    a, b = await _neighbor_positions(session, project_id, after_id, before_id)
    section = Section(
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        name=name.strip(),
        position=key_between(a, b),
    )
    session.add(section)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="section",
        entity_id=section.id,
        verb="section.created",
        changes={"name": (None, section.name)},
        undo=undo_op("sections.delete", section_id=section.id),
    )
    await emit(
        session,
        ctx,
        type="section.created",
        entity_type="section",
        entity_id=section.id,
        data={"project_id": str(project_id), "position": section.position},
        channels=_channels(project_id),
        activity_id=act.id,
    )
    return Mutation(section, act.id, version=section.version)


async def rename_section(
    session: AsyncSession, ctx: Ctx, section_id: uuid.UUID, name: str, *, record_undo: bool = True
) -> Mutation[Section]:
    section = await _get_editable(session, ctx, section_id)
    name = name.strip()
    if not name:
        raise ValidationFailed("Section name can't be empty")
    if name == section.name:
        return Mutation(section, version=section.version)
    old = section.name
    section.name = name
    section.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="section",
        entity_id=section.id,
        verb="section.updated",
        changes={"name": (old, name)},
        undo=undo_op("sections.rename", section_id=section.id, name=old, version=section.version)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="section.updated",
        entity_type="section",
        entity_id=section.id,
        data={"changes": {"name": [old, name]}, "version": section.version},
        channels=_channels(section.project_id),
        activity_id=act.id,
    )
    return Mutation(section, act.id, version=section.version)


async def move_section(
    session: AsyncSession,
    ctx: Ctx,
    section_id: uuid.UUID,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    *,
    record_undo: bool = True,
) -> Mutation[Section]:
    section = await _get_editable(session, ctx, section_id)
    if section_id in (after_id, before_id):
        raise ValidationFailed("Can't move a section next to itself")
    a, b = await _neighbor_positions(
        session, section.project_id, after_id, before_id, exclude=section.id
    )
    old = section.position
    section.position = key_between(a, b)
    section.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="section",
        entity_id=section.id,
        verb="section.moved",
        changes={"position": (old, section.position)},
        undo=undo_op(
            "sections.set_position", section_id=section.id, position=old, version=section.version
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="section.moved",
        entity_type="section",
        entity_id=section.id,
        data={"position": section.position, "version": section.version},
        channels=_channels(section.project_id),
        activity_id=act.id,
    )
    return Mutation(section, act.id, version=section.version)


async def delete_section(
    session: AsyncSession,
    ctx: Ctx,
    section_id: uuid.UUID,
    *,
    tasks: str = "move_to",
    target_section_id: uuid.UUID | None = None,
) -> Mutation[Section]:
    """Soft-delete a section. Its tasks are moved to ``target_section_id`` (default: the first
    remaining section) or deleted, via handlers registered by the tasks module."""
    section = await _get_editable(session, ctx, section_id)
    remaining = [s for s in await list_sections(session, section.project_id) if s.id != section.id]
    if not remaining:
        raise Conflict("A project needs at least one section", code="last_section")
    if tasks not in ("move_to", "delete"):
        raise ValidationFailed("tasks must be 'move_to' or 'delete'")
    target = target_section_id or remaining[0].id
    if tasks == "move_to" and target not in {s.id for s in remaining}:
        raise NotFound("Target section not found")
    batch_id = uuid.uuid4()
    moved: dict[str, Any] = {}
    for handler in _on_delete_tasks:
        moved.update(await handler(session, ctx, section, tasks, target))
    section.deleted_at = datetime.now(UTC)
    section.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="section",
        entity_id=section.id,
        verb="section.deleted",
        undo=undo_op("sections.restore", section_id=section.id, tasks=moved),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="section.deleted",
        entity_type="section",
        entity_id=section.id,
        data={"tasks": tasks, "target_section_id": str(target) if tasks == "move_to" else None},
        channels=_channels(section.project_id),
        activity_id=act.id,
    )
    return Mutation(section, act.id, batch_id=batch_id, version=section.version)


# Undo handlers (tasks restoration hooks are registered by the tasks module).
SectionRestoreHandler = Callable[[AsyncSession, Ctx, Section, dict[str, Any]], Awaitable[None]]
_on_restore: list[SectionRestoreHandler] = []


def on_section_restore(fn: SectionRestoreHandler) -> SectionRestoreHandler:
    _on_restore.append(fn)
    return fn


def _sid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["section_id"]))


@undo_handler("sections.rename")
async def _undo_rename(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    section = await _get_editable(session, ctx, _sid(args))
    if section.version != int(args["version"]):
        raise UndoConflict("This section changed after your edit")
    await rename_section(session, ctx, section.id, str(args["name"]), record_undo=False)


@undo_handler("sections.set_position")
async def _undo_move(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    section = await _get_editable(session, ctx, _sid(args))
    if section.version != int(args["version"]):
        raise UndoConflict("This section moved again after your change")
    section.position = str(args["position"])
    section.version += 1
    await emit(
        session,
        ctx,
        type="section.moved",
        entity_type="section",
        entity_id=section.id,
        data={"position": section.position, "version": section.version},
        channels=_channels(section.project_id),
    )


@undo_handler("sections.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    section = await session.get(Section, _sid(args))
    if section is None or section.workspace_id != ctx.workspace_id:
        raise NotFound()
    _, role = await get_visible_project(session, ctx, section.project_id)
    require_project_role(role, "editor", "restore sections")
    section.deleted_at = None
    section.version += 1
    for handler in _on_restore:
        await handler(session, ctx, section, dict(args.get("tasks") or {}))
    await emit(
        session,
        ctx,
        type="section.created",
        entity_type="section",
        entity_id=section.id,
        data={"project_id": str(section.project_id), "position": section.position},
        channels=_channels(section.project_id),
    )


@undo_handler("sections.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    section = await _get_editable(session, ctx, _sid(args))
    remaining = await session.execute(
        select(func.count())
        .select_from(Section)
        .where(
            Section.project_id == section.project_id,
            Section.deleted_at.is_(None),
            Section.id != section.id,
        )
    )
    if remaining.scalar_one() == 0:
        raise UndoConflict("A project needs at least one section")
    section.deleted_at = datetime.now(UTC)
    await emit(
        session,
        ctx,
        type="section.deleted",
        entity_type="section",
        entity_id=section.id,
        channels=_channels(section.project_id),
    )
