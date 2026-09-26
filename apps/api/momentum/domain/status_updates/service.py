"""S3.4.3: project status updates. The one write path for them: the UI's "Post update", Mo's
draft once a person publishes it, and the ``create_status_update`` AI tool all come here.

Posting an update also sets the project's (denormalized) ``status``, bumps its version, and is
undoable in one step: the update is withdrawn and the previous status restored, unless the
project's status was changed again since (then the undo is refused, never overwriting it).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.status_updates.models import SECTION_KEYS, StatusUpdate
from momentum.domain.status_updates.schemas import StatusUpdateIn

STATUS_LABELS = {
    "on_track": "On track",
    "at_risk": "At risk",
    "off_track": "Off track",
    "on_hold": "On hold",
    "complete": "Complete",
}
SECTION_LABELS = {
    "completed": "Completed",
    "slipped": "Slipped",
    "blockers": "Blockers",
    "next": "Next",
}


def body_text(data: StatusUpdateIn) -> str:
    lines = [f"{STATUS_LABELS[data.status]}: {data.title.strip()}"]
    if data.summary.strip():
        lines.append(data.summary.strip())
    for key in SECTION_KEYS:
        items = getattr(data.sections, key)
        if items:
            lines.append(f"{SECTION_LABELS[key]}:")
            lines += [f"- {i.text.strip()}" for i in items]
    return "\n".join(lines)


async def list_status_updates(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, *, limit: int = 20
) -> list[StatusUpdate]:
    """A visible project's updates, newest first."""
    project, _ = await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(StatusUpdate)
        .where(
            StatusUpdate.entity_type == "project",
            StatusUpdate.entity_id == project.id,
            StatusUpdate.deleted_at.is_(None),
        )
        .order_by(StatusUpdate.created_at.desc(), StatusUpdate.id.desc())
        .limit(limit)
    )
    return list(rows.scalars())


async def create_status_update(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    data: StatusUpdateIn,
    *,
    batch_id: uuid.UUID | None = None,
) -> Mutation[StatusUpdate]:
    project, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "post a status update")
    body: dict[str, Any] = {
        "summary": data.summary.strip(),
        "sections": data.sections.model_dump(),
    }
    update = StatusUpdate(
        workspace_id=ctx.workspace_id,
        entity_type="project",
        entity_id=project.id,
        status=data.status,
        title=data.title.strip(),
        body=body,
        body_text=body_text(data),
        author_id=ctx.actor.id,
        generated_by_ai=data.generated_by_ai or ctx.via in ("ai", "agent"),
        created_via=ctx.via,
    )
    session.add(update)
    previous = project.status
    project.status = data.status
    project.version += 1
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb="project.status_updated",
        changes={"status": (previous, data.status), "status_update": (None, update.title)},
        undo=undo_op(
            "status_updates.withdraw",
            update_id=update.id,
            project_id=project.id,
            previous_status=previous,
        ),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="status_update.created",
        entity_type="status_update",
        entity_id=update.id,
        data={"project_id": str(project.id), "status": data.status, "version": project.version},
        channels=[f"project:{project.id}"],
        activity_id=act.id,
    )
    return Mutation(update, act.id, version=project.version)


@undo_handler("status_updates.withdraw")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    update = await session.get(StatusUpdate, uuid.UUID(str(args["update_id"])))
    if update is None or update.deleted_at is not None:
        raise UndoConflict("That status update is already gone")
    project, _ = await get_visible_project(session, ctx, update.entity_id)
    if project.status != update.status:
        raise UndoConflict("The project's status changed after this update")
    update.deleted_at = datetime.now(UTC)
    previous = args.get("previous_status")
    project.status = previous
    project.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb="project.status_withdrawn",
        changes={"status": (update.status, previous), "status_update": (update.title, None)},
    )
    await emit(
        session,
        ctx,
        type="status_update.withdrawn",
        entity_type="status_update",
        entity_id=update.id,
        data={"project_id": str(project.id), "status": previous, "version": project.version},
        channels=[f"project:{project.id}"],
        activity_id=act.id,
    )
