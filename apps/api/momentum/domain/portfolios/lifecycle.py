"""Phase 7.5 (spec §5.2-§5.6): portfolio v2. Lifecycle settings (rule, stage field, SLA targets,
gates, columns), converting manual ↔ rule, saved views, members, readiness and stage moves.

Permissions (spec §5.6): everyone in the workspace sees a portfolio exists (guests only when they
are members); its rows are filtered by visibility. Editing (settings, rule, stages, gates, shared
views) needs the owner, an admin, or a member with ``editor``. Members are managed by the owner or
an admin. Anyone who can see the portfolio may save a personal view.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, visible_projects_clause
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.project_values import set_project_field_value
from momentum.domain.portfolios import service
from momentum.domain.portfolios.gates import Readiness, missing_words, readiness
from momentum.domain.portfolios.membership import members_clause
from momentum.domain.portfolios.models import (
    Portfolio,
    PortfolioItem,
    PortfolioMember,
    PortfolioView,
)
from momentum.domain.portfolios.rows import (
    BUILTIN_COLUMNS,
    COLUMN_LABELS,
    ViewSpec,
    column_key_ok,
    portfolio_rows_v2,
)
from momentum.domain.portfolios.schemas import (
    ConvertIn,
    PortfolioConfigIn,
    PortfolioViewIn,
    PortfolioViewPatchIn,
)
from momentum.domain.projects.models import Project
from momentum.domain.users.models import User

CONFIG_KEYS = ("rule", "stage_field_id", "stage_targets", "stage_gates", "columns")


async def _project_fields(session: AsyncSession, ctx: Ctx) -> dict[uuid.UUID, FieldDef]:
    rows = await session.execute(
        select(FieldDef).where(
            FieldDef.workspace_id == ctx.workspace_id,
            FieldDef.applies_to == "project",
            FieldDef.deleted_at.is_(None),
        )
    )
    return {f.id: f for f in rows.scalars()}


def _jsonable(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


# ---------------- settings ----------------


async def _validate_config(
    session: AsyncSession, ctx: Ctx, p: Portfolio, data: PortfolioConfigIn
) -> dict[str, Any]:
    """The new values (JSON-ready) of the keys the request sets, validated against the
    workspace's project fields."""
    fields = await _project_fields(session, ctx)
    out: dict[str, Any] = {}
    sent = data.model_fields_set
    if "stage_field_id" in sent:
        fid = data.stage_field_id
        if fid is not None:
            f = fields.get(fid)
            if f is None or f.type != "single_select":
                raise ValidationFailed(
                    "The stage field must be a single-select project field", code="invalid_stage"
                )
        out["stage_field_id"] = fid
    stage_id = out.get("stage_field_id", p.stage_field_id)
    options = (
        {str(o["id"]) for o in fields[stage_id].options or [] if isinstance(o, dict)}
        if stage_id in fields
        else set()
    )
    if "stage_targets" in sent:
        targets = data.stage_targets or {}
        if set(targets) - options:
            raise ValidationFailed("A target names a stage that isn't one", code="invalid_stage")
        out["stage_targets"] = dict(targets)
    if "stage_gates" in sent:
        gates = data.stage_gates or {}
        if set(gates) - options:
            raise ValidationFailed("A gate names a stage that isn't one", code="invalid_stage")
        for g in gates.values():
            if set(g.required_fields) - set(fields):
                raise ValidationFailed("A gate needs a project field that doesn't exist")
        out["stage_gates"] = {k: _jsonable(g.model_dump()) for k, g in gates.items()}
    if "columns" in sent:
        cols = data.columns or []
        keys = [c.key for c in cols]
        if len(set(keys)) != len(keys):
            raise ValidationFailed("A column is listed twice", code="invalid_columns")
        for c in cols:
            if not column_key_ok(c.key, fields):
                raise ValidationFailed(f"Unknown column {c.key}", code="invalid_columns")
        out["columns"] = [c.model_dump(exclude_none=True) for c in cols]
    if "rule" in sent:
        if data.rule is not None:
            for cond in data.rule.project_field_conditions:
                if cond.field_id not in fields:
                    raise ValidationFailed("A rule condition names an unknown project field")
        out["rule"] = _jsonable(data.rule.model_dump()) if data.rule is not None else None
    return out


async def configure(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    data: PortfolioConfigIn,
    *,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    await service.require_edit(session, ctx, p)
    new = await _validate_config(session, ctx, p, data)
    if "rule" in new and p.kind != "rule" and new["rule"] is not None:
        raise ValidationFailed("Convert the portfolio to a rule portfolio first", code="not_rule")
    changes: Diff = {}
    old: dict[str, Any] = {}
    for k, v in new.items():
        before = getattr(p, k)
        if before != v:
            changes[k] = (_jsonable(before), _jsonable(v))
            old[k] = _jsonable(before)
            setattr(p, k, v)
    if not changes:
        return Mutation(p, version=p.version)
    p.version += 1
    act = await service.record(
        session,
        ctx,
        p,
        "portfolio.updated",
        changes,
        undo_op("portfolios.configure", portfolio_id=p.id, version=p.version, old=old)
        if record_undo
        else None,
    )
    return Mutation(p, act, version=p.version)


@undo_handler("portfolios.configure")
async def _undo_configure(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    p = await service.get_portfolio(session, ctx, uuid.UUID(str(args["portfolio_id"])))
    if p.version != args["version"]:
        raise UndoConflict("This portfolio was changed again since")
    await configure(
        session, ctx, p.id, PortfolioConfigIn.model_validate(args["old"]), record_undo=False
    )


def effective_columns(p: Portfolio, fields: dict[uuid.UUID, FieldDef]) -> list[dict[str, Any]]:
    """The portfolio's columns in order: its saved list (unknown keys dropped), then every
    built-in and project field it doesn't mention (hidden when it has a saved list)."""
    saved = [c for c in p.columns or [] if column_key_ok(str(c.get("key")), fields)]
    seen = {str(c["key"]) for c in saved}
    rest = [k for k in BUILTIN_COLUMNS if k not in seen] + [
        f"field:{fid}" for fid in fields if f"field:{fid}" not in seen
    ]
    out: list[dict[str, Any]] = [
        {"key": str(c["key"]), "visible": bool(c.get("visible", True)), "width": c.get("width")}
        for c in saved
    ]
    out += [{"key": k, "visible": not saved, "width": None} for k in rest]
    for c in out:
        c["label"] = (
            COLUMN_LABELS[c["key"]]
            if c["key"] in COLUMN_LABELS
            else fields[uuid.UUID(c["key"].removeprefix("field:"))].name
        )
    return out


# ---------------- manual ↔ rule ----------------


async def _member_ids(session: AsyncSession, p: Portfolio) -> list[uuid.UUID]:
    """Every live project in the portfolio, before visibility (an editor converts the whole
    portfolio, not their view of it)."""
    q = select(Project.id).where(members_clause(p), Project.deleted_at.is_(None))
    if p.kind == "manual":
        q = q.join(PortfolioItem, PortfolioItem.project_id == Project.id).where(
            PortfolioItem.portfolio_id == p.id
        )
        q = q.order_by(PortfolioItem.position)
    else:
        q = q.order_by(Project.name, Project.id)
    return list((await session.execute(q)).scalars())


async def _set_items(session: AsyncSession, p: Portfolio, project_ids: list[uuid.UUID]) -> None:
    for item in (
        await session.execute(select(PortfolioItem).where(PortfolioItem.portfolio_id == p.id))
    ).scalars():
        await session.delete(item)
    await session.flush()
    last: str | None = None
    for pid in project_ids:
        last = key_between(last, None)
        session.add(
            PortfolioItem(
                portfolio_id=p.id, project_id=pid, workspace_id=p.workspace_id, position=last
            )
        )
    await session.flush()


async def convert(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    data: ConvertIn,
    *,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    """Manual → rule: the current projects become the rule's explicit ``project_ids`` (plus any
    criteria sent). Rule → manual: the projects the rule matches now become the list."""
    p = await service.get_portfolio(session, ctx, portfolio_id)
    await service.require_edit(session, ctx, p)
    if data.kind == p.kind:
        if data.kind == "rule" and data.rule is not None:
            return await configure(
                session, ctx, p.id, PortfolioConfigIn(rule=data.rule), record_undo=record_undo
            )
        return Mutation(p, version=p.version)
    before_ids = await _member_ids(session, p)
    old = {"kind": p.kind, "rule": p.rule, "items": [str(i) for i in before_ids]}
    if data.kind == "rule":
        rule = data.rule.model_dump() if data.rule is not None else {}
        rule = _jsonable(rule)
        explicit = list(dict.fromkeys([*rule.get("project_ids", []), *map(str, before_ids)]))
        rule["project_ids"] = explicit
        p.kind, p.rule = "rule", rule
        await _validate_config(session, ctx, p, PortfolioConfigIn.model_validate({"rule": rule}))
    else:
        await _set_items(session, p, before_ids)
        p.kind = "manual"
    p.version += 1
    await session.flush()
    act = await service.record(
        session,
        ctx,
        p,
        "portfolio.updated",
        {"kind": (old["kind"], p.kind)},
        undo_op("portfolios.convert", portfolio_id=p.id, version=p.version, old=old)
        if record_undo
        else None,
    )
    return Mutation(p, act, version=p.version)


@undo_handler("portfolios.convert")
async def _undo_convert(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    p = await service.get_portfolio(session, ctx, uuid.UUID(str(args["portfolio_id"])))
    if p.version != args["version"]:
        raise UndoConflict("This portfolio was changed again since")
    old = args["old"]
    if old["kind"] == "manual":
        await _set_items(session, p, [uuid.UUID(i) for i in old["items"]])
    p.kind, p.rule = old["kind"], old["rule"]
    p.version += 1
    await service.record(session, ctx, p, "portfolio.updated", {"kind": (None, p.kind)})


# ---------------- saved views ----------------


def _view_out_channels(p: Portfolio, v: PortfolioView) -> list[str]:
    return [f"portfolio:{p.id}"] if v.owner_id is None else [f"user:{v.owner_id}"]


async def list_views(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID
) -> list[PortfolioView]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    rows = await session.execute(
        select(PortfolioView)
        .where(
            PortfolioView.portfolio_id == p.id,
            PortfolioView.deleted_at.is_(None),
            or_(PortfolioView.owner_id.is_(None), PortfolioView.owner_id == ctx.actor.id),
        )
        .order_by(PortfolioView.owner_id.is_not(None), PortfolioView.name)
    )
    return list(rows.scalars())


async def get_view(
    session: AsyncSession, ctx: Ctx, p: Portfolio, view_id: uuid.UUID
) -> PortfolioView:
    v = await session.get(PortfolioView, view_id)
    if (
        v is None
        or v.portfolio_id != p.id
        or v.deleted_at is not None
        or (v.owner_id is not None and v.owner_id != ctx.actor.id)
    ):
        raise NotFound("View not found")
    return v


async def _check_view(
    session: AsyncSession, ctx: Ctx, p: Portfolio, group_by: str | None, sort: list[Any]
) -> None:
    fields = await _project_fields(session, ctx)
    if group_by is not None and not (
        group_by in ("status", "owner", "stage")
        or (group_by.startswith("field:") and column_key_ok(group_by, fields))
    ):
        raise ValidationFailed(f"Can't group by {group_by}", code="invalid_group")
    for s in sort:
        if not column_key_ok(s.key, fields):
            raise ValidationFailed(f"Can't sort by {s.key}", code="invalid_sort")


async def _view_activity(
    session: AsyncSession,
    ctx: Ctx,
    p: Portfolio,
    v: PortfolioView,
    verb: str,
    changes: Diff,
    undo: dict[str, Any] | None,
) -> uuid.UUID:
    act = await record_activity(
        session,
        ctx,
        entity_type="portfolio_view",
        entity_id=v.id,
        verb=verb,
        changes=changes,
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="portfolio_view",
        entity_id=v.id,
        data={"portfolio_id": str(p.id), "shared": v.owner_id is None},
        channels=_view_out_channels(p, v),
        activity_id=act.id,
    )
    return act.id


async def create_view(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, data: PortfolioViewIn
) -> Mutation[PortfolioView]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    if ctx.actor.id is None or ctx.actor.is_agent:
        raise Forbidden("Only people save views")
    if data.shared:
        await service.require_edit(session, ctx, p)
    await _check_view(session, ctx, p, data.group_by, data.sort)
    v = PortfolioView(
        workspace_id=ctx.workspace_id,
        portfolio_id=p.id,
        name=data.name,
        owner_id=None if data.shared else ctx.actor.id,
        layout=data.layout,
        filters=_jsonable(data.filters.model_dump(exclude_defaults=True)),
        group_by=data.group_by,
        sort=[s.model_dump() for s in data.sort],
    )
    session.add(v)
    await session.flush()
    act = await _view_activity(
        session,
        ctx,
        p,
        v,
        "portfolio.view_created",
        {"name": (None, v.name)},
        undo_op("portfolios.view_delete", view_id=v.id),
    )
    return Mutation(v, act)


async def update_view(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    view_id: uuid.UUID,
    data: PortfolioViewPatchIn,
) -> Mutation[PortfolioView]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    v = await get_view(session, ctx, p, view_id)
    if v.owner_id is None:
        await service.require_edit(session, ctx, p)
    sent = data.model_fields_set
    group_by = data.group_by if "group_by" in sent else v.group_by
    await _check_view(session, ctx, p, group_by, data.sort or [])
    changes: Diff = {}
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    if "name" in sent and data.name is not None:
        new["name"] = data.name
    if "layout" in sent and data.layout is not None:
        new["layout"] = data.layout
    if "filters" in sent and data.filters is not None:
        new["filters"] = _jsonable(data.filters.model_dump(exclude_defaults=True))
    if "group_by" in sent:
        new["group_by"] = data.group_by
    if "sort" in sent and data.sort is not None:
        new["sort"] = [s.model_dump() for s in data.sort]
    for k, val in new.items():
        if getattr(v, k) != val:
            old[k] = getattr(v, k)
            changes[k] = (getattr(v, k), val)
            setattr(v, k, val)
    if not changes:
        return Mutation(v)
    await session.flush()
    act = await _view_activity(
        session,
        ctx,
        p,
        v,
        "portfolio.view_updated",
        changes,
        undo_op("portfolios.view_restore_values", view_id=v.id, old=old),
    )
    return Mutation(v, act)


async def delete_view(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, view_id: uuid.UUID
) -> Mutation[PortfolioView]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    v = await get_view(session, ctx, p, view_id)
    if v.owner_id is None:
        await service.require_edit(session, ctx, p)
    v.deleted_at = datetime.now(UTC)
    act = await _view_activity(
        session,
        ctx,
        p,
        v,
        "portfolio.view_deleted",
        {"name": (v.name, None)},
        undo_op("portfolios.view_restore", view_id=v.id),
    )
    return Mutation(v, act)


async def _view_for_undo(session: AsyncSession, ctx: Ctx, view_id: Any) -> PortfolioView:
    v = await session.get(PortfolioView, uuid.UUID(str(view_id)))
    if v is None or v.workspace_id != ctx.workspace_id:
        raise UndoConflict("That view is gone")
    return v


@undo_handler("portfolios.view_delete")
async def _undo_view_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    v = await _view_for_undo(session, ctx, args["view_id"])
    v.deleted_at = datetime.now(UTC)


@undo_handler("portfolios.view_restore")
async def _undo_view_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    v = await _view_for_undo(session, ctx, args["view_id"])
    v.deleted_at = None


@undo_handler("portfolios.view_restore_values")
async def _undo_view_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    v = await _view_for_undo(session, ctx, args["view_id"])
    for k, val in (args.get("old") or {}).items():
        setattr(v, k, val)


# ---------------- members ----------------


def _require_manage_members(ctx: Ctx, p: Portfolio) -> None:
    if not (ctx.actor.is_admin or p.owner_id == ctx.actor.id):
        raise Forbidden("Only the portfolio's owner or an admin can change its members")


async def list_members(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID
) -> list[tuple[PortfolioMember, User]]:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    rows = await session.execute(
        select(PortfolioMember, User)
        .join(User, User.id == PortfolioMember.user_id)
        .where(PortfolioMember.portfolio_id == p.id)
        .order_by(User.name)
    )
    return [(m, u) for m, u in rows.tuples()]


async def set_member(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str | None,
    *,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    """Add, change (``role``) or remove (``None``) a portfolio member."""
    p = await service.get_portfolio(session, ctx, portfolio_id)
    _require_manage_members(ctx, p)
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.status != "active":
        raise NotFound("Person not found")
    if user.is_agent:
        raise ValidationFailed("Agents can't be portfolio members", code="agent")
    if role is not None and user.id == p.owner_id:
        raise Conflict("The owner already edits this portfolio", code="owner")
    row = await session.get(PortfolioMember, (p.id, user.id))
    before = row.role if row is not None else None
    if before == role:
        return Mutation(p, version=p.version)
    if role is None:
        assert row is not None
        await session.delete(row)
    elif row is None:
        session.add(
            PortfolioMember(
                portfolio_id=p.id, user_id=user.id, workspace_id=ctx.workspace_id, role=role
            )
        )
    else:
        row.role = role
    await session.flush()
    verb = (
        "portfolio.member_added"
        if before is None
        else "portfolio.member_removed"
        if role is None
        else "portfolio.member_updated"
    )
    act = await record_activity(
        session,
        ctx,
        entity_type="portfolio",
        entity_id=p.id,
        verb=verb,
        changes={f"member:{user.name}": (before, role)},
        undo=undo_op(
            "portfolios.member_set", portfolio_id=p.id, user_id=user.id, role=before, expect=role
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="portfolio",
        entity_id=p.id,
        data={"user_id": str(user.id), "role": role},
        channels=[f"portfolio:{p.id}", f"user:{user.id}"],
        activity_id=act.id,
    )
    return Mutation(p, act.id, version=p.version)


@undo_handler("portfolios.member_set")
async def _undo_member(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    pid, uid = uuid.UUID(str(args["portfolio_id"])), uuid.UUID(str(args["user_id"]))
    row = await session.get(PortfolioMember, (pid, uid))
    if (row.role if row is not None else None) != args.get("expect"):
        raise UndoConflict("This member was changed again since")
    await set_member(session, ctx, pid, uid, args.get("role"), record_undo=False)


# ---------------- readiness and stage moves ----------------


async def project_in_portfolio(
    session: AsyncSession, ctx: Ctx, p: Portfolio, project_id: uuid.UUID
) -> Project:
    project, _role = await get_visible_project(session, ctx, project_id)
    hit = (
        await session.execute(select(Project.id).where(Project.id == project.id, members_clause(p)))
    ).first()
    if hit is None:
        raise NotFound("That project isn't in this portfolio")
    return project


async def check_readiness(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, project_id: uuid.UUID, to: str
) -> Readiness:
    p = await service.get_portfolio(session, ctx, portfolio_id)
    if p.stage_field_id is None:
        raise ValidationFailed("This portfolio has no stage field", code="no_stage")
    project = await project_in_portfolio(session, ctx, p, project_id)
    stage = await session.get(FieldDef, p.stage_field_id)
    if stage is None or to not in {str(o.get("id")) for o in stage.options or []}:
        raise ValidationFailed("That isn't one of the stages", code="invalid_stage")
    return await readiness(session, p, project, to)


class GateNotMet(Conflict):
    """A stage move into a gated stage whose checklist isn't met (and no ``override``)."""

    def __init__(self, r: Readiness) -> None:
        super().__init__(
            f"{r.stage_label} isn't ready: missing {missing_words(r)}",
            code="gate_not_met",
            readiness={
                "stage": r.stage,
                "stage_label": r.stage_label,
                "met": False,
                "items": [
                    {"kind": i.kind, "label": i.label, "met": i.met, "ref": i.ref} for i in r.items
                ],
            },
        )
        self.readiness = r


async def move_stage(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    to: str,
    *,
    override: bool = False,
) -> Mutation[Any]:
    """A board move: set the stage field through ``set_project_field_value`` (project editors,
    one undoable activity and history row). A gate that isn't met refuses the move unless the
    editor says ``override``; the override and what was missing are recorded in the activity."""
    r = await check_readiness(session, ctx, portfolio_id, project_id, to)
    p = await service.get_portfolio(session, ctx, portfolio_id)
    assert p.stage_field_id is not None
    note: dict[str, Any] | None = None
    if not r.met:
        if not override:
            raise GateNotMet(r)
        note = {"gate_override": f"moved to {r.stage_label} without {missing_words(r)}"}
    return await set_project_field_value(session, ctx, project_id, p.stage_field_id, to, note=note)


# ---------------- bulk set, CSV, list summary ----------------


async def bulk_set_field(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    project_ids: list[uuid.UUID],
    field_id: uuid.UUID,
    value: Any,
) -> tuple[uuid.UUID, int, int]:
    """Set one project field on many rows as one batch (one undo). Rows the viewer can't edit,
    or that aren't in the portfolio, are skipped and counted. Stage moves made this way are
    still project field changes (no gate checks: the board is where gates are enforced)."""
    p = await service.get_portfolio(session, ctx, portfolio_id)
    members = set(
        (
            await session.execute(
                select(Project.id).where(
                    members_clause(p),
                    Project.id.in_(project_ids),
                    visible_projects_clause(ctx),
                )
            )
        ).scalars()
    )
    batch = uuid.uuid4()
    updated = skipped = 0
    for pid in dict.fromkeys(project_ids):
        if pid not in members:
            skipped += 1
            continue
        try:
            async with session.begin_nested():
                m = await set_project_field_value(
                    session, ctx, pid, field_id, value, batch_id=batch
                )
        except Forbidden:
            skipped += 1
            continue
        if m.activity_id is not None:
            updated += 1
    return batch, updated, skipped


async def rows_csv(session: AsyncSession, ctx: Ctx, p: Portfolio, spec: ViewSpec) -> str:
    """The view as CSV: the visible columns in order, values as the table shows them, every cell
    guarded against spreadsheet formulas (the project export's rules)."""
    import csv
    import io

    from momentum.domain.tasks.csv_export import field_text, safe_cell

    out = await portfolio_rows_v2(session, ctx, p, spec)
    fields = {f.id: f for f in out.fields}
    columns = [c for c in effective_columns(p, fields) if c["visible"]]
    people = {
        u.id: u.name
        for u in (
            await session.execute(select(User).where(User.workspace_id == ctx.workspace_id))
        ).scalars()
    }
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["label"] for c in columns])
    for r in out.rows:
        cells = []
        for c in columns:
            key = c["key"]
            if key.startswith("field:"):
                f = fields[uuid.UUID(key.removeprefix("field:"))]
                v = r["fields"].get(str(f.id))
                if f.type == "people" and isinstance(v, list):
                    v = [str(x) for x in v]
                    text = ", ".join(people.get(uuid.UUID(x), "") for x in v)
                else:
                    text = field_text(f, v, people)
            else:
                text = _cell_text(key, r)
            cells.append(safe_cell(text))
        writer.writerow(cells)
    return buf.getvalue()


def _cell_text(key: str, r: dict[str, Any]) -> str:
    v = r.get(key)
    if key == "owner":
        return str(r.get("owner_name") or "")
    if key == "stage":
        return str((r["stage"] or {}).get("label") or "")
    if key == "progress":
        return "" if r["progress"] is None else f"{round(r['progress'] * 100)}%"
    if key == "next_milestone":
        m = r["next_milestone"]
        return "" if not m else f"{m['title']} ({m['due_on'] or 'no date'})"
    if key == "latest_update":
        u = r["latest_update"]
        return "" if not u else str(u["title"])
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return str(v.isoformat())
    return str(v)


async def summaries(
    session: AsyncSession, ctx: Ctx, portfolios: list[Portfolio]
) -> dict[uuid.UUID, dict[str, Any]]:
    """For the list page: per portfolio with a stage field, the count of visible projects per
    stage and the total of its first currency column. Two queries per such portfolio."""
    from sqlalchemy import func as sa_func

    from momentum.domain.fields.models import ProjectFieldValue

    fields = await _project_fields(session, ctx)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for p in portfolios:
        stage = fields.get(p.stage_field_id) if p.stage_field_id else None
        visible = select(Project.id).where(members_clause(p), visible_projects_clause(ctx))
        counts: dict[str, int] = {}
        if stage is not None:
            counts = {
                str(v): int(n)
                for v, n in (
                    await session.execute(
                        select(ProjectFieldValue.value, sa_func.count())
                        .where(
                            ProjectFieldValue.field_id == stage.id,
                            ProjectFieldValue.project_id.in_(visible),
                        )
                        .group_by(ProjectFieldValue.value)
                    )
                ).tuples()
            }
        value_field = next(
            (
                fields[uuid.UUID(c["key"].removeprefix("field:"))]
                for c in effective_columns(p, fields)
                if c["key"].startswith("field:")
                and fields[uuid.UUID(c["key"].removeprefix("field:"))].type == "currency"
                and (c["visible"] or not p.columns)
            ),
            None,
        )
        total: float | None = None
        if value_field is not None:
            values = (
                await session.execute(
                    select(ProjectFieldValue.value).where(
                        ProjectFieldValue.field_id == value_field.id,
                        ProjectFieldValue.project_id.in_(visible),
                    )
                )
            ).scalars()
            nums = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
            total = float(sum(nums)) if nums else None
        out[p.id] = {
            "stages": [
                {
                    "option_id": str(o["id"]),
                    "label": str(o["label"]),
                    "count": counts.get(str(o["id"]), 0),
                }
                for o in (stage.options if stage is not None else None) or []
                if isinstance(o, dict)
            ],
            "value_field": value_field.name if value_field is not None else None,
            "total_value": total,
        }
    return out
