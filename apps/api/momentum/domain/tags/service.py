"""S2.3.3: workspace tags, task attach/detach, and a cross-project tag page.

Two permission paths, both reusing checks that already exist rather than adding new ones
(`core/permissions.py` and `domain/access.py` are unmodified):

- Standalone tag-library management (create/rename/recolor/delete a tag on its own, e.g. from a
  workspace settings screen) needs `Action.PROJECT_CREATE` (admin/member) — the same bar
  Momentum already uses for other shared, workspace-level objects like teams and projects.
- Attaching/detaching a tag on a task — including creating one inline while tagging, the normal
  everyday flow — only needs editor access to *that task* (`get_visible_task` +
  `require_project_role`), same as fields' values. A member who can edit a task can tag it even
  if they couldn't create a team or project on their own.

Unlike fields, tag mutations go through the normal activity trail and are ordinary, frequent
actions — there's no per-project fan-out to design an undo payload around here, so nothing about
tags is called out as an exception the way field management is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, require
from momentum.domain.access import (
    get_visible_project,
    get_visible_task,
    require_project_role,
    visible_projects_clause,
)
from momentum.domain.projects.models import Project
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tags.schemas import TagCreateIn, TagPatchIn
from momentum.domain.tasks.models import Task, TaskProject


async def list_tags(session: AsyncSession, ctx: Ctx) -> list[Tag]:
    """The workspace's tag library, alphabetical."""
    rows = await session.execute(
        select(Tag)
        .where(Tag.workspace_id == ctx.workspace_id, Tag.deleted_at.is_(None))
        .order_by(func.lower(Tag.name))
    )
    return list(rows.scalars())


async def _get_tag(session: AsyncSession, ctx: Ctx, tag_id: uuid.UUID) -> Tag:
    tag = await session.get(Tag, tag_id)
    if tag is None or tag.workspace_id != ctx.workspace_id or tag.deleted_at is not None:
        raise NotFound("Tag not found")
    return tag


async def _find_by_name(session: AsyncSession, ctx: Ctx, name: str) -> Tag | None:
    row = await session.execute(
        select(Tag).where(
            Tag.workspace_id == ctx.workspace_id,
            Tag.deleted_at.is_(None),
            func.lower(Tag.name) == name.lower(),
        )
    )
    return row.scalar_one_or_none()


async def create_tag(session: AsyncSession, ctx: Ctx, data: TagCreateIn) -> Mutation[Tag]:
    require(ctx, Action.PROJECT_CREATE)
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Tag name can't be empty")
    if await _find_by_name(session, ctx, name) is not None:
        raise Conflict("A tag with this name already exists", code="duplicate_name")
    tag = Tag(workspace_id=ctx.workspace_id, name=name, color=data.color)
    session.add(tag)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="tag",
        entity_id=tag.id,
        verb="tag.created",
        changes={"name": (None, tag.name)},
    )
    await emit(
        session,
        ctx,
        type="tag.created",
        entity_type="tag",
        entity_id=tag.id,
        data={},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(tag, act.id)


async def patch_tag(
    session: AsyncSession, ctx: Ctx, tag_id: uuid.UUID, data: TagPatchIn
) -> Mutation[Tag]:
    require(ctx, Action.PROJECT_CREATE)
    tag = await _get_tag(session, ctx, tag_id)
    changed: dict[str, tuple[object, object]] = {}
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationFailed("Tag name can't be empty")
        existing = await _find_by_name(session, ctx, name)
        if existing is not None and existing.id != tag.id:
            raise Conflict("A tag with this name already exists", code="duplicate_name")
        if name != tag.name:
            changed["name"] = (tag.name, name)
            tag.name = name
    if data.color is not None and data.color != tag.color:
        changed["color"] = (tag.color, data.color)
        tag.color = data.color
    if not changed:
        return Mutation(tag)
    act = await record_activity(
        session, ctx, entity_type="tag", entity_id=tag.id, verb="tag.updated", changes=changed
    )
    await emit(
        session,
        ctx,
        type="tag.updated",
        entity_type="tag",
        entity_id=tag.id,
        data={},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(tag, act.id)


async def delete_tag(session: AsyncSession, ctx: Ctx, tag_id: uuid.UUID) -> None:
    """Soft-delete the tag everywhere (its `task_tags` rows are left as-is; a deleted tag just
    stops showing up, same as an archived field)."""
    require(ctx, Action.PROJECT_CREATE)
    tag = await _get_tag(session, ctx, tag_id)
    tag.deleted_at = datetime.now(UTC)
    await record_activity(session, ctx, entity_type="tag", entity_id=tag.id, verb="tag.deleted")
    await emit(
        session,
        ctx,
        type="tag.deleted",
        entity_type="tag",
        entity_id=tag.id,
        data={},
        channels=[f"workspace:{ctx.workspace_id}"],
    )


# ---------------- task tags ----------------


async def get_task_tags(session: AsyncSession, ctx: Ctx, task_id: uuid.UUID) -> list[Tag]:
    await get_visible_task(session, ctx, task_id)
    rows = await session.execute(
        select(Tag)
        .join(TaskTag, TaskTag.tag_id == Tag.id)
        .where(TaskTag.task_id == task_id, Tag.deleted_at.is_(None))
        .order_by(func.lower(Tag.name))
    )
    return list(rows.scalars())


async def list_project_task_tags(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[tuple[uuid.UUID, Tag]]:
    """Every tag across a project's tasks, in one query — mirrors
    `fields.service.list_project_field_values` so list/board rows pay one round trip, not one per
    visible task."""
    await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(TaskTag.task_id, Tag)
        .join(Tag, Tag.id == TaskTag.tag_id)
        .join(TaskProject, TaskProject.task_id == TaskTag.task_id)
        .where(TaskProject.project_id == project_id, Tag.deleted_at.is_(None))
    )
    return [(task_id, tag) for task_id, tag in rows.all()]


async def add_task_tag(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    tag_id: uuid.UUID | None,
    name: str | None,
) -> Mutation[Tag]:
    """Attach an existing tag (`tag_id`), or create one by `name` if it doesn't exist yet and
    attach that — the normal "type a new tag while tagging a task" flow. Attaching an
    already-attached tag is a no-op, not a conflict (tagging is idempotent from the caller's
    point of view)."""
    _, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "tag this task")
    tag: Tag | None
    if tag_id is not None:
        tag = await _get_tag(session, ctx, tag_id)
    elif name is not None and name.strip():
        clean = name.strip()
        tag = await _find_by_name(session, ctx, clean)
        if tag is None:
            tag = Tag(workspace_id=ctx.workspace_id, name=clean, color="#94a3b8")
            session.add(tag)
            await session.flush()
    else:
        raise ValidationFailed("Provide a tag_id or a name")
    if await session.get(TaskTag, (task_id, tag.id)) is None:
        session.add(TaskTag(task_id=task_id, tag_id=tag.id))
        act = await record_activity(
            session,
            ctx,
            entity_type="task",
            entity_id=task_id,
            verb="task.tagged",
            changes={"tag": (None, tag.name)},
        )
        channels = [f"task:{task_id}"]
        if placement is not None:
            channels.append(f"project:{placement.project_id}")
        await emit(
            session,
            ctx,
            type="task.tagged",
            entity_type="task",
            entity_id=task_id,
            data={"tag_id": str(tag.id)},
            channels=channels,
            activity_id=act.id,
        )
        return Mutation(tag, act.id)
    return Mutation(tag)


async def remove_task_tag(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, tag_id: uuid.UUID
) -> None:
    _, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "untag this task")
    link = await session.get(TaskTag, (task_id, tag_id))
    if link is None:
        raise NotFound("This tag isn't on the task")
    tag = await session.get(Tag, tag_id)
    await session.delete(link)
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task_id,
        verb="task.untagged",
        changes={"tag": (tag.name if tag else None, None)},
    )
    channels = [f"task:{task_id}"]
    if placement is not None:
        channels.append(f"project:{placement.project_id}")
    await emit(
        session,
        ctx,
        type="task.untagged",
        entity_type="task",
        entity_id=task_id,
        data={"tag_id": str(tag_id)},
        channels=channels,
        activity_id=act.id,
    )


async def list_tag_tasks(
    session: AsyncSession, ctx: Ctx, tag_id: uuid.UUID
) -> list[tuple[Task, TaskProject | None]]:
    """The tag page: every visible, incomplete task carrying this tag, across every project the
    caller can see, newest first. Visibility is scoped through `visible_projects_clause` — the
    same predicate every other cross-project listing (Home, project search) already uses — so a
    tag never leaks a task from a private project the caller isn't in."""
    tag = await _get_tag(session, ctx, tag_id)
    rows = await session.execute(
        select(Task, TaskProject)
        .join(TaskTag, TaskTag.task_id == Task.id)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .join(Project, Project.id == TaskProject.project_id)
        .where(
            TaskTag.tag_id == tag.id,
            Task.deleted_at.is_(None),
            Task.completed_at.is_(None),
            visible_projects_clause(ctx),
        )
        .order_by(Task.created_at.desc())
    )
    return [(t, p) for t, p in rows.all()]
