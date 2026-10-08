"""Phase 7.6 (spec §3.4): a pack's **project setup**, the checklist offered when an admin adds the
pack's agent to a project.

Setup is **declarative**: a pack lists what it needs (task fields, a section; pack settings join in
S76-05), so the preview has no side effects and the same list is applied on confirm. Applying writes
through the ordinary services, as the confirming person, under one ``batch_id``, so a single undo
reverts the whole setup. Things that already exist are reused, never duplicated: a field the project
already has (by name) is left as it is; a library field with that name and type is attached.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Conflict, ValidationFailed
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.agents.models import Agent
from momentum.domain.fields import service as fields_service
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.schemas import FieldCreateIn, FieldType, SelectOptionIn
from momentum.domain.projects.models import ProjectMember
from momentum.domain.sections import service as sections_service

Action = Literal["create", "attach", "exists", "skip"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskField(_Strict):
    """A task field the pack fills in (e.g. Bernie's Vendor, Amount)."""

    kind: Literal["task_field"] = "task_field"
    name: str = Field(min_length=1, max_length=100)
    type: FieldType
    options: tuple[str, ...] = ()  # option labels, for select fields


class Section(_Strict):
    """A section the pack uses, created unless the project already has one of ``unless``."""

    kind: Literal["section"] = "section"
    name: str = Field(min_length=1, max_length=200)
    unless: tuple[str, ...] = ()


SetupItem = TaskField | Section


@dataclass(frozen=True)
class SetupChange:
    kind: str
    name: str
    action: Action
    detail: str
    field_id: uuid.UUID | None = None


async def preview(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, items: tuple[SetupItem, ...]
) -> list[SetupChange]:
    """What applying ``items`` to the project would do, as the caller. Nothing is written."""
    await get_visible_project(session, ctx, project_id)
    attached = {
        f.name.casefold(): f
        for _pf, f in await fields_service.list_project_fields(session, ctx, project_id)
    }
    sections = {
        s.name.casefold() for s in await sections_service.list_sections(session, project_id)
    }
    changes: list[SetupChange] = []
    for item in items:
        if isinstance(item, TaskField):
            have = attached.get(item.name.casefold())
            if have is not None:
                note = "" if have.type == item.type else f" (it's a {have.type} field)"
                changes.append(
                    SetupChange("task_field", item.name, "exists", f"Already on the project{note}")
                )
                continue
            library = await _library_field(session, ctx, item)
            if library is not None:
                changes.append(
                    SetupChange(
                        "task_field",
                        item.name,
                        "attach",
                        f"Add the workspace's {item.name} field",
                        library.id,
                    )
                )
            else:
                changes.append(
                    SetupChange("task_field", item.name, "create", f"New {item.type} field")
                )
        else:
            covered = [n for n in item.unless if n.casefold() in sections]
            if item.name.casefold() in sections:
                changes.append(
                    SetupChange("section", item.name, "exists", "Already on the project")
                )
            elif covered:
                changes.append(
                    SetupChange("section", item.name, "skip", f"The project has {covered[0]}")
                )
            else:
                changes.append(SetupChange("section", item.name, "create", "New section"))
    return changes


@dataclass(frozen=True)
class SetupResult:
    batch_id: uuid.UUID | None
    changes: list[SetupChange]


async def apply(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, items: tuple[SetupItem, ...]
) -> SetupResult:
    """Apply the setup as the caller, as one undoable batch. Like adding the agent to the project,
    it's a project admin's call (spec §3.4). Re-running it is harmless: what exists is reused, so a
    second apply changes nothing."""
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "admin", "set up an agent on this project")
    changes = await preview(session, ctx, project_id, items)
    by_name: dict[tuple[str, str], SetupItem] = {(i.kind, i.name): i for i in items}
    batch_id = uuid.uuid4()
    wrote = False
    for change in changes:
        item = by_name[(change.kind, change.name)]
        if change.action == "attach" and change.field_id is not None:
            await fields_service.attach_field(
                session,
                ctx,
                project_id,
                change.field_id,
                None,
                None,
                batch_id=batch_id,
                undoable=True,
            )
            wrote = True
        elif change.action == "create" and isinstance(item, TaskField):
            options = [SelectOptionIn(label=o) for o in item.options] if item.options else None
            if item.type in ("single_select", "multi_select") and not options:
                raise ValidationFailed(f"Setup field {item.name} needs its options")
            await fields_service.create_field(
                session,
                ctx,
                project_id,
                FieldCreateIn(name=item.name, type=item.type, options=options),
                batch_id=batch_id,
                undoable=True,
            )
            wrote = True
        elif change.action == "create" and isinstance(item, Section):
            await sections_service.create_section(
                session, ctx, project_id, item.name, batch_id=batch_id
            )
            wrote = True
    return SetupResult(batch_id if wrote else None, changes)


async def _library_field(session: AsyncSession, ctx: Ctx, item: TaskField) -> FieldDef | None:
    return (
        await session.execute(
            select(FieldDef)
            .where(
                FieldDef.workspace_id == ctx.workspace_id,
                FieldDef.deleted_at.is_(None),
                FieldDef.applies_to == "task",
                FieldDef.is_library.is_(True),
                FieldDef.type == item.type,
                func.lower(FieldDef.name) == item.name.lower(),
            )
            .order_by(FieldDef.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def items_for(
    session: AsyncSession, agent: Agent, project_id: uuid.UUID, packs: object
) -> tuple[SetupItem, ...]:
    """The setup the agent's pack declares for ``project_id``, once the agent is in the project.

    ``packs`` is the app's ``PackRegistry`` (typed loosely to keep this module free of the registry
    import cycle)."""
    from momentum.agents.packs.registry import PackRegistry

    assert isinstance(packs, PackRegistry)
    if agent.kind != "pack" or agent.pack_key is None:
        raise ValidationFailed(f"{agent.name} isn't a pack agent, so it has no project setup")
    if agent.pack_key not in packs.packs:
        raise Conflict(f"{agent.name}'s pack isn't loaded on this server", code="pack_not_loaded")
    member = await session.get(ProjectMember, (project_id, agent.user_id))
    if member is None:
        raise Conflict(f"Add {agent.name} to this project first", code="not_member")
    return packs.packs[agent.pack_key].setup
