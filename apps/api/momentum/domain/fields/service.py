"""S2.3.1/S2.3.2: custom field definitions, the workspace library, per-project attachment, and
field values (get/set on a task, or in bulk for a whole project's list/board view).

Field management (create/edit/archive/attach/detach/reorder) is deliberately **not undoable** in
this slice (unlike almost everything else in Momentum): each of those needs its own restore
payload design, and none of them are the kind of frequent, easy-to-fat-finger action (like a
rename or a drag) that undo mainly protects against. Documented here rather than silently
different from the rest of the app.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.domain.access import get_visible_project, get_visible_task, require_project_role
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.fields.schemas import (
    FieldCreateIn,
    FieldPatchIn,
    NumberOptions,
    SelectOptionIn,
)
from momentum.domain.tasks.models import TaskProject

SELECT_TYPES = ("single_select", "multi_select")
NUMERIC_TYPES = ("number", "currency", "percent")


def _channels(project_id: uuid.UUID) -> list[str]:
    return [f"project:{project_id}"]


def _new_option_id() -> str:
    return secrets.token_hex(4)


def _normalize_options(
    field_type: str, options: list[SelectOptionIn] | NumberOptions | None
) -> Any:
    """Options-in (from the API) -> the JSONB shape stored on `FieldDef.options`, assigning a
    fresh id to any select option that doesn't already have one."""
    if field_type in SELECT_TYPES:
        if options is None:
            return []
        if not isinstance(options, list):
            raise ValidationFailed(f"{field_type} needs a list of options")
        seen: set[str] = set()
        out = []
        for opt in options:
            oid = opt.id or _new_option_id()
            if oid in seen:
                raise ValidationFailed("Duplicate option id")
            seen.add(oid)
            out.append(
                {"id": oid, "label": opt.label, "color": opt.color, "archived": opt.archived}
            )
        return out
    if field_type in NUMERIC_TYPES:
        if options is None:
            return {"precision": 0, "unit": None}
        if isinstance(options, list):
            raise ValidationFailed(f"{field_type} doesn't take a list of options")
        return options.model_dump()
    if options is not None:
        raise ValidationFailed(f"{field_type} fields don't take options")
    return None


async def list_workspace_fields(session: AsyncSession, ctx: Ctx) -> list[FieldDef]:
    """The shared library: fields any project can attach."""
    rows = await session.execute(
        select(FieldDef)
        .where(
            FieldDef.workspace_id == ctx.workspace_id,
            FieldDef.deleted_at.is_(None),
            FieldDef.is_library.is_(True),
        )
        .order_by(FieldDef.name)
    )
    return list(rows.scalars())


async def list_project_fields(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[tuple[ProjectField, FieldDef]]:
    await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(ProjectField, FieldDef)
        .join(FieldDef, FieldDef.id == ProjectField.field_id)
        .where(ProjectField.project_id == project_id, FieldDef.deleted_at.is_(None))
        .order_by(ProjectField.position)
    )
    return [(pf, f) for pf, f in rows.all()]


async def _neighbor_positions(
    session: AsyncSession,
    project_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
    *,
    exclude: uuid.UUID | None = None,
) -> tuple[str | None, str | None]:
    rows = await session.execute(
        select(ProjectField)
        .where(ProjectField.project_id == project_id)
        .order_by(ProjectField.position)
    )
    fields = [pf for pf in rows.scalars() if pf.field_id != exclude]
    ids = [pf.field_id for pf in fields]
    if after_id is not None:
        if after_id not in ids:
            raise NotFound("Neighbor field not found")
        i = ids.index(after_id)
        nxt = fields[i + 1].position if i + 1 < len(fields) else None
        return fields[i].position, nxt
    if before_id is not None:
        if before_id not in ids:
            raise NotFound("Neighbor field not found")
        i = ids.index(before_id)
        prev = fields[i - 1].position if i > 0 else None
        return prev, fields[i].position
    return (fields[-1].position if fields else None), None


async def _get_attached(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID
) -> tuple[ProjectField, FieldDef]:
    """A field attached to a project the caller can edit; NotFound otherwise."""
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "manage fields")
    pf = await session.get(ProjectField, (project_id, field_id))
    field = await session.get(FieldDef, field_id) if pf else None
    if pf is None or field is None or field.deleted_at is not None:
        raise NotFound("Field not found on this project")
    return pf, field


async def create_field(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, data: FieldCreateIn
) -> Mutation[FieldDef]:
    """Create a field def and attach it to ``project_id`` in one step (the usual "+ Add field"
    flow: most fields start life on one project, `is_library` just controls whether other
    projects are later offered it)."""
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "manage fields")
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Field name can't be empty")
    field = FieldDef(
        workspace_id=ctx.workspace_id,
        name=name,
        type=data.type,
        options=_normalize_options(data.type, data.options),
        description=data.description,
        is_library=data.is_library,
        created_by=ctx.actor.id,
    )
    session.add(field)
    await session.flush()
    a, _ = await _neighbor_positions(session, project_id, None, None)
    session.add(
        ProjectField(project_id=project_id, field_id=field.id, position=key_between(a, None))
    )
    act = await record_activity(
        session,
        ctx,
        entity_type="field",
        entity_id=field.id,
        verb="field.created",
        changes={"name": (None, field.name)},
    )
    await emit(
        session,
        ctx,
        type="field.created",
        entity_type="field",
        entity_id=field.id,
        data={"project_id": str(project_id)},
        channels=_channels(project_id),
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def attach_field(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
) -> Mutation[FieldDef]:
    """Attach an existing library field (from another project) to ``project_id``."""
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "manage fields")
    field = await session.get(FieldDef, field_id)
    if field is None or field.workspace_id != ctx.workspace_id or field.deleted_at is not None:
        raise NotFound("Field not found")
    if await session.get(ProjectField, (project_id, field_id)) is not None:
        raise Conflict("This field is already on the project", code="already_attached")
    a, b = await _neighbor_positions(session, project_id, after_id, before_id)
    session.add(ProjectField(project_id=project_id, field_id=field.id, position=key_between(a, b)))
    act = await record_activity(
        session,
        ctx,
        entity_type="field",
        entity_id=field.id,
        verb="field.attached",
        changes={"name": (None, field.name)},
    )
    await emit(
        session,
        ctx,
        type="field.attached",
        entity_type="field",
        entity_id=field.id,
        data={"project_id": str(project_id)},
        channels=_channels(project_id),
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def patch_field(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    data: FieldPatchIn,
) -> Mutation[FieldDef]:
    """Rename/redescribe/re-option a field def. Edits reach every project it's attached to
    (it's a shared definition), so this project just needs to be one of them."""
    _, field = await _get_attached(session, ctx, project_id, field_id)
    changed: dict[str, tuple[Any, Any]] = {}
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationFailed("Field name can't be empty")
        if name != field.name:
            changed["name"] = (field.name, name)
            field.name = name
    if "description" in data.model_fields_set and data.description != field.description:
        changed["description"] = (field.description, data.description)
        field.description = data.description
    if "options" in data.model_fields_set:
        field.options = _normalize_options(field.type, data.options)
    if not changed and "options" not in data.model_fields_set:
        return Mutation(field)
    act = await record_activity(
        session, ctx, entity_type="field", entity_id=field.id, verb="field.updated", changes=changed
    )
    other_projects = await _project_ids_using(session, field.id)
    await emit(
        session,
        ctx,
        type="field.updated",
        entity_type="field",
        entity_id=field.id,
        data={},
        channels=[c for pid in other_projects for c in _channels(pid)],
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def archive_field(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID
) -> Mutation[FieldDef]:
    """Archive the field def entirely (hides it from every project that has it, not just this
    one). Its values aren't deleted, so it isn't a destructive action — just not visible without
    a (future) unarchive."""
    _, field = await _get_attached(session, ctx, project_id, field_id)
    field.deleted_at = datetime.now(UTC)
    act = await record_activity(
        session, ctx, entity_type="field", entity_id=field.id, verb="field.archived"
    )
    other_projects = await _project_ids_using(session, field.id)
    await emit(
        session,
        ctx,
        type="field.archived",
        entity_type="field",
        entity_id=field.id,
        data={},
        channels=[c for pid in other_projects for c in _channels(pid)],
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def detach_field(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID
) -> None:
    """Remove a field from just this project (the def and its values elsewhere are untouched)."""
    pf, field = await _get_attached(session, ctx, project_id, field_id)
    await session.delete(pf)
    await emit(
        session,
        ctx,
        type="field.detached",
        entity_type="field",
        entity_id=field.id,
        data={"project_id": str(project_id)},
        channels=_channels(project_id),
    )


async def move_project_field(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
) -> Mutation[FieldDef]:
    pf, field = await _get_attached(session, ctx, project_id, field_id)
    if field_id in (after_id, before_id):
        raise ValidationFailed("Can't move a field next to itself")
    a, b = await _neighbor_positions(session, project_id, after_id, before_id, exclude=field_id)
    pf.position = key_between(a, b)
    await emit(
        session,
        ctx,
        type="field.moved",
        entity_type="field",
        entity_id=field.id,
        data={"project_id": str(project_id), "position": pf.position},
        channels=_channels(project_id),
    )
    return Mutation(field)


async def set_field_visibility(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID, is_visible: bool
) -> Mutation[FieldDef]:
    pf, field = await _get_attached(session, ctx, project_id, field_id)
    pf.is_visible = is_visible
    await emit(
        session,
        ctx,
        type="field.updated",
        entity_type="field",
        entity_id=field.id,
        data={"project_id": str(project_id)},
        channels=_channels(project_id),
    )
    return Mutation(field)


async def _project_ids_using(session: AsyncSession, field_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(ProjectField.project_id).where(ProjectField.field_id == field_id)
    )
    return list(rows.scalars())


# ---------------- values ----------------

_DATE_LEN = len("2024-01-01")


def validate_value(field: FieldDef, value: Any) -> Any:
    if value is None:
        return None
    t = field.type
    if t in ("text", "url"):
        if not isinstance(value, str) or not value.strip():
            raise ValidationFailed("Expected text")
        if len(value) > 2000:
            raise ValidationFailed("That's too long")
        return value
    if t == "checkbox":
        if not isinstance(value, bool):
            raise ValidationFailed("Expected true or false")
        return value
    if t in NUMERIC_TYPES:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationFailed("Expected a number")
        return value
    if t == "date":
        if not isinstance(value, str) or len(value) != _DATE_LEN:
            raise ValidationFailed("Expected a YYYY-MM-DD date")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValidationFailed("Expected a YYYY-MM-DD date") from None
        return value
    if t in SELECT_TYPES:
        ids = {o["id"] for o in (field.options or [])}
        if t == "single_select":
            if not isinstance(value, str) or value not in ids:
                raise ValidationFailed("Unknown option")
            return value
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValidationFailed("Expected a list of option ids")
        if len(set(value)) != len(value):
            raise ValidationFailed("Duplicate option ids")
        if not set(value) <= ids:
            raise ValidationFailed("Unknown option")
        return value
    if t == "people":
        if not isinstance(value, list):
            raise ValidationFailed("Expected a list of user ids")
        out = []
        for v in value:
            try:
                out.append(str(uuid.UUID(str(v))))
            except ValueError:
                raise ValidationFailed("Invalid user id") from None
        return out
    raise ValidationFailed("Unsupported field type")  # pragma: no cover - type is check-constrained


async def get_task_field_values(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> list[FieldValue]:
    await get_visible_task(session, ctx, task_id)
    rows = await session.execute(select(FieldValue).where(FieldValue.task_id == task_id))
    return list(rows.scalars())


async def list_project_field_values(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[FieldValue]:
    """Every field value across a project's tasks, in one query. The list/board views call this
    once per project rather than once per visible task — the S2.3.2 AC (10 fields x 2,000 tasks
    stays within the list's performance budget) depends on this being a single round trip, not
    N of them."""
    await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(FieldValue)
        .join(TaskProject, TaskProject.task_id == FieldValue.task_id)
        .where(TaskProject.project_id == project_id)
    )
    return list(rows.scalars())


async def set_task_field_value(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, field_id: uuid.UUID, value: Any
) -> FieldValue | None:
    _, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "set field values")
    field = await session.get(FieldDef, field_id)
    if field is None or field.workspace_id != ctx.workspace_id or field.deleted_at is not None:
        raise NotFound("Field not found")
    clean = validate_value(field, value)
    row = await session.get(FieldValue, (task_id, field_id))
    if clean is None:
        if row is not None:
            await session.delete(row)
        result = None
    else:
        if row is None:
            row = FieldValue(task_id=task_id, field_id=field_id)
            session.add(row)
        row.value = clean
        row.updated_by = ctx.actor.id
        result = row
    await session.flush()
    # the task channel (pane) plus the project channel (list/board row chips — S2.3.2) so both
    # stay live; a task with no placement (shouldn't normally happen) just gets the former.
    channels = [f"task:{task_id}"]
    if placement is not None:
        channels.append(f"project:{placement.project_id}")
    await emit(
        session,
        ctx,
        type="task.field_updated",
        entity_type="task",
        entity_id=task_id,
        data={"field_id": str(field_id)},
        channels=channels,
    )
    return result
