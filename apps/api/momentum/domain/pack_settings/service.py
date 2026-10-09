"""Phase 7.6 S76-05 (spec §8.3): pack settings.

A pack defines its settings as a pydantic model (``momentum.sdk.PackSettings``: every field has a
default). Values are stored per workspace (``project_id`` null) and per project; the effective
values are the model's defaults, then the workspace's, then the project's, **field by field**.
Every write is validated against the whole model and records activity with undo.

Who may change them: workspace admins and the pack's **stewards** (the people listed in the
workspace value ``stewards``) for the workspace values; project admins (and workspace admins) for
a project's. ``approvers`` and ``stewards`` are also routes for agents' questions.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project
from momentum.domain.pack_settings.models import PackSettingsRow

PEOPLE_FIELDS = ("stewards", "approvers")


async def _row(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    pack_key: str,
    project_id: uuid.UUID | None,
    *,
    lock: bool = False,
) -> PackSettingsRow | None:
    stmt = select(PackSettingsRow).where(
        PackSettingsRow.workspace_id == workspace_id,
        PackSettingsRow.pack_key == pack_key,
        PackSettingsRow.project_id.is_(None)
        if project_id is None
        else PackSettingsRow.project_id == project_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row: PackSettingsRow | None = await session.scalar(stmt)
    return row


async def stored(
    session: AsyncSession, workspace_id: uuid.UUID, pack_key: str, project_id: uuid.UUID | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The workspace values and (when ``project_id`` is given) the project's own values."""
    ws = await _row(session, workspace_id, pack_key, None)
    proj = await _row(session, workspace_id, pack_key, project_id) if project_id else None
    return dict(ws.values if ws else {}), dict(proj.values if proj else {})


def effective(
    model: type[BaseModel], workspace: dict[str, Any], project: dict[str, Any]
) -> BaseModel:
    """Defaults, then workspace values, then project values, field by field."""
    try:
        return model.model_validate({**workspace, **project})
    except ValidationError as e:
        raise ValidationFailed(_problems(e)) from e


def _problems(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in err['loc']) or 'settings'}: {err['msg']}"
        for err in e.errors()[:8]
    )


async def effective_values(
    session: AsyncSession,
    model: type[BaseModel],
    workspace_id: uuid.UUID,
    pack_key: str,
    project_id: uuid.UUID | None,
) -> dict[str, Any]:
    ws, proj = await stored(session, workspace_id, pack_key, project_id)
    return effective(model, ws, proj).model_dump(mode="json")


async def people(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    pack_key: str,
    field: str,
    project_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """The user ids a people setting (``stewards``, ``approvers``) holds, project first."""
    ws, proj = await stored(session, workspace_id, pack_key, project_id)
    raw = proj.get(field, ws.get(field)) or []
    out: list[uuid.UUID] = []
    for x in raw if isinstance(raw, list) else [raw]:
        try:
            out.append(uuid.UUID(str(x)))
        except ValueError:
            continue
    return out


async def consent(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    pack_key: str,
    setting: str,
    project_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    """Spec §8.1: an event or schedule trigger's consent is the setting that turned it on (the
    project's value, else the workspace's). Who set it, and when, is named on every run it
    starts. ``None`` when the setting is off."""
    rows = [
        r
        for r in (
            await _row(session, workspace_id, pack_key, project_id) if project_id else None,
            await _row(session, workspace_id, pack_key, None),
        )
        if r is not None and setting in (r.values or {})
    ]
    if not rows or not rows[0].values.get(setting):
        return None
    row = rows[0]
    return {
        "setting": setting,
        "by": str(row.updated_by) if row.updated_by else None,
        "at": row.updated_at.isoformat() if row.updated_at else None,
        "level": "project" if row.project_id else "workspace",
    }


async def is_steward(
    session: AsyncSession, workspace_id: uuid.UUID, pack_key: str, user_id: uuid.UUID | None
) -> bool:
    return user_id is not None and user_id in await people(
        session, workspace_id, pack_key, "stewards"
    )


async def can_edit(
    session: AsyncSession, ctx: Ctx, pack_key: str, project_id: uuid.UUID | None
) -> bool:
    if ctx.actor.role == "guest" or ctx.actor.is_agent:
        return False
    if ctx.actor.is_admin:
        return True
    if project_id is None:
        return await is_steward(session, ctx.workspace_id, pack_key, ctx.actor.id)
    try:
        _project, role = await get_visible_project(session, ctx, project_id)
    except NotFound:
        return False
    return role == "admin"


async def put_values(
    session: AsyncSession,
    ctx: Ctx,
    model: type[BaseModel],
    pack_key: str,
    project_id: uuid.UUID | None,
    values: dict[str, Any],
) -> uuid.UUID:
    """Replace one level's values (a project's own, or the workspace's). Keys left out fall back
    to the level below. Returns the activity id (the change is undoable)."""
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)  # NotFound when hidden
    if not await can_edit(session, ctx, pack_key, project_id):
        raise Forbidden(
            "Only workspace admins and the agent's stewards can change its workspace settings"
            if project_id is None
            else "Only the project's admins can change the agent's settings for this project"
        )
    unknown = sorted(set(values) - set(model.model_fields))
    if unknown:
        raise ValidationFailed(f"Unknown setting(s): {', '.join(unknown)}")
    ws, proj = await stored(session, ctx.workspace_id, pack_key, project_id)
    new_ws, new_proj = (values, proj) if project_id is None else (ws, values)
    checked = effective(model, new_ws, new_proj)  # the whole model must still hold
    clean = {k: v for k, v in checked.model_dump(mode="json").items() if k in values}
    row = await _row(session, ctx.workspace_id, pack_key, project_id, lock=True)
    before = dict(row.values) if row else {}
    if row is None:
        row = PackSettingsRow(
            workspace_id=ctx.workspace_id, pack_key=pack_key, project_id=project_id, values={}
        )
        session.add(row)
    row.values, row.updated_by = clean, ctx.actor.id
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="pack_settings",
        entity_id=row.id,
        verb="pack_settings.updated",
        changes={k: (before.get(k), clean.get(k)) for k in set(before) | set(clean)},
        undo=undo_op("pack_settings.restore", row_id=row.id, values=before, expect=clean),
    )
    await emit(
        session,
        ctx,
        type="pack_settings.updated",
        entity_type="pack_settings",
        entity_id=row.id,
        data={"pack_key": pack_key, "project_id": str(project_id) if project_id else None},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return act.id


@undo_handler("pack_settings.restore")
async def _undo(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    row = await session.get(PackSettingsRow, uuid.UUID(str(args["row_id"])), with_for_update=True)
    if row is None or row.values != args.get("expect"):
        raise UndoConflict("These settings changed again since")
    row.values = dict(args.get("values") or {})
    row.updated_by = ctx.actor.id
