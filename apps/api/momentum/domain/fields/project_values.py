"""Phase 7.5 (spec §5.1): project fields. The one write path for a project's field values.

Project fields are workspace-wide field definitions with ``applies_to='project'`` (Stage,
Account owner, Contract value…), using the same types, options and validation as task fields.
Every change, from the UI, the API, a rule or Mo, goes through ``set_project_field_value``:
it needs editor access to the project, records one ``project.field_set`` activity with an undo,
writes one ``project_field_events`` history row and emits ``project.field_changed`` to the
project's channel and to every portfolio that contains the project.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.fields.models import FieldDef, ProjectFieldEvent, ProjectFieldValue
from momentum.domain.fields.schemas import FieldCreateIn, FieldPatchIn
from momentum.domain.fields.service import _normalize_options, validate_value


async def list_project_field_defs(session: AsyncSession, ctx: Ctx) -> list[FieldDef]:
    """Every live project field of the workspace, by name."""
    rows = await session.execute(
        select(FieldDef)
        .where(
            FieldDef.workspace_id == ctx.workspace_id,
            FieldDef.applies_to == "project",
            FieldDef.deleted_at.is_(None),
        )
        .order_by(FieldDef.name)
    )
    return list(rows.scalars())


async def get_project_field(session: AsyncSession, ctx: Ctx, field_id: uuid.UUID) -> FieldDef:
    field = await session.get(FieldDef, field_id)
    if (
        field is None
        or field.workspace_id != ctx.workspace_id
        or field.deleted_at is not None
        or field.applies_to != "project"
    ):
        raise NotFound("Project field not found")
    return field


async def create_project_field(
    session: AsyncSession, ctx: Ctx, data: FieldCreateIn
) -> Mutation[FieldDef]:
    """A new workspace project field. Members and admins may add one (not guests or agents):
    like a task field, it holds nothing until someone sets a value on a project they edit."""
    if ctx.actor.role == "guest" or ctx.actor.is_agent or ctx.actor.id is None:
        raise Forbidden("Only workspace members can add project fields")
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Field name can't be empty")
    taken = (
        await session.execute(
            select(FieldDef.id).where(
                FieldDef.workspace_id == ctx.workspace_id,
                FieldDef.applies_to == "project",
                FieldDef.deleted_at.is_(None),
                FieldDef.name.ilike(name),
            )
        )
    ).first()
    if taken is not None:
        raise ValidationFailed("A project field with that name already exists", code="name_taken")
    field = FieldDef(
        workspace_id=ctx.workspace_id,
        name=name,
        type=data.type,
        options=_normalize_options(data.type, data.options),
        description=data.description,
        is_library=True,
        applies_to="project",
        created_by=ctx.actor.id,
    )
    session.add(field)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="field",
        entity_id=field.id,
        verb="field.created",
        changes={"name": (None, field.name), "applies_to": (None, "project")},
    )
    await emit(
        session,
        ctx,
        type="field.created",
        entity_type="field",
        entity_id=field.id,
        data={"applies_to": "project"},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def patch_project_field(
    session: AsyncSession, ctx: Ctx, field_id: uuid.UUID, data: FieldPatchIn
) -> Mutation[FieldDef]:
    """Rename, redescribe or re-option a project field. The creator or a workspace admin may
    (it changes the field for every project). Options keep their ids, so values stay valid; an
    option that disappears leaves values pointing at it (shown as an unknown option), as with
    task fields."""
    field = await get_project_field(session, ctx, field_id)
    if ctx.actor.role != "admin" and ctx.actor.id != field.created_by:
        raise Forbidden("Only the field's creator or an admin can change a project field")
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
        changed["options"] = (None, "changed")
    if not changed:
        return Mutation(field)
    act = await record_activity(
        session, ctx, entity_type="field", entity_id=field.id, verb="field.updated", changes=changed
    )
    await emit(
        session,
        ctx,
        type="field.updated",
        entity_type="field",
        entity_id=field.id,
        data={"applies_to": "project"},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(field, act.id)


async def project_field_values(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[ProjectFieldValue]:
    await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(ProjectFieldValue)
        .join(FieldDef, FieldDef.id == ProjectFieldValue.field_id)
        .where(ProjectFieldValue.project_id == project_id, FieldDef.deleted_at.is_(None))
    )
    return list(rows.scalars())


async def field_history(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID | None = None
) -> list[ProjectFieldEvent]:
    await get_visible_project(session, ctx, project_id)
    q = select(ProjectFieldEvent).where(ProjectFieldEvent.project_id == project_id)
    if field_id is not None:
        q = q.where(ProjectFieldEvent.field_id == field_id)
    rows = await session.execute(q.order_by(ProjectFieldEvent.at, ProjectFieldEvent.id))
    return list(rows.scalars())


async def set_project_field_value(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    value: Any,
    *,
    record_undo: bool = True,
    batch_id: uuid.UUID | None = None,
    note: dict[str, Any] | None = None,
) -> Mutation[ProjectFieldValue | None]:
    """Set (or clear, with ``None``) a project's value for a project field. Setting the value it
    already has changes nothing and records nothing. ``note`` is added to the activity's changes
    (S75-05: a stage move that overrode a gate says so)."""
    project, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "change project fields")
    field = await get_project_field(session, ctx, field_id)
    clean = validate_value(field, value)
    row = await session.get(ProjectFieldValue, (project_id, field_id))
    old = row.value if row is not None else None
    if old == clean:
        return Mutation(row, None)
    changes: dict[str, Any] = {f"field:{field.name}": (old, clean)}
    for k, v in (note or {}).items():
        changes[k] = (None, v)
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project_id,
        verb="project.field_set",
        changes=changes,
        undo=undo_op(
            "projects.field_set",
            project_id=project_id,
            field_id=field_id,
            value=old,
            expect=clean,
        )
        if record_undo
        else None,
        batch_id=batch_id,
    )
    if clean is None:
        if row is not None:
            await session.delete(row)
        result: ProjectFieldValue | None = None
    else:
        if row is None:
            row = ProjectFieldValue(
                project_id=project_id, field_id=field_id, workspace_id=ctx.workspace_id
            )
            session.add(row)
        row.value = clean
        row.updated_by = ctx.actor.id
        result = row
    session.add(
        ProjectFieldEvent(
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            field_id=field_id,
            old=old,
            new=clean,
            actor_id=ctx.actor.id,
        )
    )
    await session.flush()
    from momentum.domain.portfolios.membership import portfolio_ids_containing

    portfolios = await portfolio_ids_containing(session, project)
    await emit(
        session,
        ctx,
        type="project.field_changed",
        entity_type="project",
        entity_id=project_id,
        data={"field_id": str(field_id), "old": old, "new": clean},
        channels=[f"project:{project_id}", *(f"portfolio:{p}" for p in portfolios)],
        activity_id=act.id,
    )
    return Mutation(result, act.id)


@undo_handler("projects.field_set")
async def _undo_set(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    project_id = uuid.UUID(str(args["project_id"]))
    field_id = uuid.UUID(str(args["field_id"]))
    row = await session.get(ProjectFieldValue, (project_id, field_id))
    if (row.value if row is not None else None) != args.get("expect"):
        raise UndoConflict("This field was changed again since")
    # the undo is a change too: it writes its own history row (stage time stays truthful)
    await set_project_field_value(
        session, ctx, project_id, field_id, args.get("value"), record_undo=False
    )
