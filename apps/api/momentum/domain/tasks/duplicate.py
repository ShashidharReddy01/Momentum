"""E7.4 parity (P1): duplicate a task, as in Asana's "Duplicate task".

The copy sits right below the original (in the same section, or under the same parent) and
carries what defines the work: title ("Copy of …"), description, assignee, start and due dates,
priority, estimate, custom field values, tags and the whole subtask tree. Not copied, as in Asana's
defaults: comments, attachments, followers (the person duplicating follows the copy),
dependencies, completion and the repeat rule. Everything is one batch, so one undo removes the
copy and its subtasks.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.mutation import Mutation
from momentum.domain.access import get_visible_task, require_project_role
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.fields.service import set_task_field_value
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tags.service import add_task_tag
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import create_subtask, create_task, update_task
from momentum.domain.users.models import User

TITLE_MAX = 500


async def duplicate_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> Mutation[tuple[Task, TaskProject | None]]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "duplicate this task")
    batch = uuid.uuid4()
    title = f"Copy of {task.title}"[:TITLE_MAX]
    if task.parent_id is not None:
        sub = await create_subtask(
            session, ctx, task.parent_id, title, after_id=task.id, batch_id=batch
        )
        copy, copy_placement = sub.entity, None
    elif placement is not None:
        top = await create_task(
            session,
            ctx,
            placement.project_id,
            title,
            section_id=placement.section_id,
            after_id=task.id,
            batch_id=batch,
        )
        copy, copy_placement = top.entity
    else:
        raise ValidationFailed("Only tasks in a project can be duplicated")
    await _copy_details(session, ctx, task, copy.id, batch)
    return Mutation((copy, copy_placement), batch_id=batch)


async def _copy_details(
    session: AsyncSession, ctx: Ctx, source: Task, target_id: uuid.UUID, batch: uuid.UUID
) -> None:
    patch: dict[str, Any] = {}
    if source.description:
        patch["description"] = source.description
    for key in ("start_on", "due_on", "due_at"):
        value = getattr(source, key)
        if value is not None:
            patch[key] = value.isoformat()
    if source.priority:
        patch["priority"] = source.priority
    if source.estimate_minutes is not None:
        patch["estimate_minutes"] = source.estimate_minutes
    if source.assignee_id is not None:
        assignee = await session.get(User, source.assignee_id)
        if assignee is not None and assignee.status != "disabled":
            patch["assignee_id"] = str(source.assignee_id)
    if patch:
        await update_task(session, ctx, target_id, patch, batch_id=batch)

    values = (
        await session.execute(
            select(FieldValue)
            .join(FieldDef, FieldDef.id == FieldValue.field_id)
            .where(FieldValue.task_id == source.id, FieldDef.deleted_at.is_(None))
        )
    ).scalars()
    for v in list(values):
        if v.value is None:
            continue
        try:  # a field of another project the original is also in doesn't apply to the copy
            await set_task_field_value(session, ctx, target_id, v.field_id, v.value, batch_id=batch)
        except ValidationFailed:
            continue

    tags = (
        await session.execute(
            select(TaskTag.tag_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(TaskTag.task_id == source.id, Tag.deleted_at.is_(None))
        )
    ).scalars()
    for tag_id in list(tags):
        await add_task_tag(session, ctx, target_id, tag_id, None)

    children = (
        await session.execute(
            select(Task)
            .where(Task.parent_id == source.id, Task.deleted_at.is_(None))
            .order_by(Task.parent_position)
        )
    ).scalars()
    for child in list(children):
        sub = await create_subtask(session, ctx, target_id, child.title, batch_id=batch)
        await _copy_details(session, ctx, child, sub.entity.id, batch)
