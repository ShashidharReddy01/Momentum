from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.mutation import Mutation
from momentum.domain.attachments.router import content_disposition
from momentum.domain.fields.schemas import FieldValueOut
from momentum.domain.portfolios import lifecycle, service
from momentum.domain.portfolios.gates import Readiness
from momentum.domain.portfolios.models import Portfolio, PortfolioView
from momentum.domain.portfolios.rows import ViewSpec
from momentum.domain.portfolios.rows import portfolio_rows_v2 as rows_v2
from momentum.domain.portfolios.schemas import (
    BulkSetFieldIn,
    BulkSetFieldOut,
    ColumnOut,
    ConvertIn,
    GateItemOut,
    PortfolioConfigIn,
    PortfolioDetailOut,
    PortfolioGroupOut,
    PortfolioIn,
    PortfolioItemIn,
    PortfolioMemberIn,
    PortfolioMemberOut,
    PortfolioOut,
    PortfolioPatchIn,
    PortfolioProjectRow,
    PortfolioRowOut,
    PortfolioRowsOut,
    PortfolioStatusDraftOut,
    PortfolioSummaryOut,
    PortfolioViewIn,
    PortfolioViewOut,
    PortfolioViewPatchIn,
    ReadinessOut,
    StageMoveIn,
    ViewFiltersIn,
)
from momentum.domain.status_updates.router import update_out
from momentum.domain.status_updates.schemas import StatusUpdateIn, StatusUpdateOut

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


async def _out(s: AsyncSession, ctx: Ctx, p: Portfolio, count: int) -> PortfolioOut:
    role = await service.role_of(s, ctx, p)
    return PortfolioOut(
        id=p.id,
        name=p.name,
        description=p.description,
        owner_id=p.owner_id,
        status=p.status,
        version=p.version,
        can_edit=role in ("owner", "admin", "editor"),
        project_count=count,
        created_at=p.created_at,
        kind=p.kind,
        rule=p.rule,
        stage_field_id=p.stage_field_id,
        stage_targets=p.stage_targets or {},
        stage_gates=p.stage_gates or {},
        columns=p.columns or [],
        my_role=role,
    )


async def _detail(s: AsyncSession, ctx: Ctx, p: Portfolio) -> PortfolioDetailOut:
    rows, hidden = await service.portfolio_rows(s, ctx, p)
    return PortfolioDetailOut(
        **(await _out(s, ctx, p, len(rows))).model_dump(),
        projects=[
            PortfolioProjectRow(
                id=x.id,
                name=x.name,
                color=x.color,
                owner_id=x.owner_id,
                status=x.status,
                start_on=x.start_on,
                due_on=x.due_on,
                **facts,
            )
            for x, facts in rows
        ],
        hidden_projects=hidden,
    )


def _meta(m: Mutation[Portfolio]) -> MutationMeta:
    return MutationMeta(activity_id=m.activity_id, version=m.version)


@router.get("", response_model=ListOut[PortfolioOut], summary="Portfolios in this workspace")
async def list_portfolios(
    ctx: CtxDep,
    uow: UowDep,
    summaries: Annotated[
        bool, Query(description="Add each one's count per stage and total value (list page)")
    ] = False,
) -> ListOut[PortfolioOut]:
    async with uow.transaction() as s:
        rows = await service.list_portfolios(s, ctx)
        extra = await lifecycle.summaries(s, ctx, [p for p, _n in rows]) if summaries else {}
        out = []
        for p, n in rows:
            item = await _out(s, ctx, p, n)
            if p.id in extra:
                item.summary = PortfolioSummaryOut(portfolio_id=p.id, **extra[p.id])
            out.append(item)
        return ListOut(data=out)


@router.post(
    "",
    response_model=MutationOut[PortfolioDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a portfolio",
)
async def create_portfolio(
    body: PortfolioIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_portfolio(s, ctx, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get(
    "/{portfolio_id}", response_model=PortfolioDetailOut, summary="A portfolio and its projects"
)
async def get_portfolio(portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> PortfolioDetailOut:
    async with uow.transaction() as s:
        return await _detail(s, ctx, await service.get_portfolio(s, ctx, portfolio_id))


@router.patch(
    "/{portfolio_id}", response_model=MutationOut[PortfolioDetailOut], summary="Rename or describe"
)
async def update_portfolio(
    portfolio_id: uuid.UUID, body: PortfolioPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.update_portfolio(s, ctx, portfolio_id, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete("/{portfolio_id}", response_model=MutationOut[OkOut], summary="Delete (undoable)")
async def delete_portfolio(portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_portfolio(s, ctx, portfolio_id)
        return MutationOut(data=OkOut(), meta=_meta(m))


@router.post(
    "/{portfolio_id}/projects",
    response_model=MutationOut[PortfolioDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a project you can see",
)
async def add_project(
    portfolio_id: uuid.UUID, body: PortfolioItemIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.add_project(s, ctx, portfolio_id, body.project_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete(
    "/{portfolio_id}/projects/{project_id}",
    response_model=MutationOut[PortfolioDetailOut],
    summary="Remove a project",
)
async def remove_project(
    portfolio_id: uuid.UUID, project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.remove_project(s, ctx, portfolio_id, project_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get(
    "/{portfolio_id}/status-draft",
    response_model=PortfolioStatusDraftOut,
    summary="A check-in drafted from the projects' statuses (nothing is saved)",
)
async def status_draft(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> PortfolioStatusDraftOut:
    async with uow.transaction() as s:
        return PortfolioStatusDraftOut(draft=await service.draft_status(s, ctx, portfolio_id))


@router.get(
    "/{portfolio_id}/status-updates",
    response_model=ListOut[StatusUpdateOut],
    summary="A portfolio's status updates, newest first",
)
async def list_statuses(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        rows = await service.list_statuses(s, ctx, portfolio_id)
        return ListOut(data=[await update_out(s, ctx, u) for u in rows])


@router.post(
    "/{portfolio_id}/status-updates",
    response_model=MutationOut[StatusUpdateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Post a portfolio check-in (sets its status; undoable)",
)
async def post_status(
    portfolio_id: uuid.UUID, body: StatusUpdateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        m = await service.post_status(s, ctx, portfolio_id, body)
        await s.refresh(m.entity)
        return MutationOut(
            data=await update_out(s, ctx, m.entity),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


# ---------------- Phase 7.5: portfolio v2 (spec §5.2-§5.6) ----------------


def _sort_param(sort: str | None) -> list[dict[str, Any]]:
    """``key:dir,key:dir`` → [{key, dir}]."""
    out = []
    for part in (sort or "").split(","):
        part = part.strip()
        key, direction = part, "asc"
        if part.endswith((":asc", ":desc")):  # keys may hold a colon (field:<id>)
            key, _, direction = part.rpartition(":")
        if key:
            out.append({"key": key, "dir": "desc" if direction == "desc" else "asc"})
    return out


@router.get(
    "/{portfolio_id}/rows",
    response_model=PortfolioRowsOut,
    summary="The portfolio's rows with every column, filtered, grouped and sorted on the server",
)
async def portfolio_rows(
    portfolio_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    view_id: uuid.UUID | None = None,
    filters: Annotated[str | None, Query(max_length=4000, description="JSON filters")] = None,
    group_by: Annotated[str | None, Query(max_length=80)] = None,
    sort: Annotated[str | None, Query(max_length=400, description="key:asc,key:desc")] = None,
) -> PortfolioRowsOut:
    async with uow.transaction() as s:
        p = await service.get_portfolio(s, ctx, portfolio_id)
        spec = ViewSpec()
        if view_id is not None:
            v = await lifecycle.get_view(s, ctx, p, view_id)
            spec = ViewSpec(dict(v.filters or {}), v.group_by, list(v.sort or []))
        if filters is not None:
            try:
                parsed = ViewFiltersIn.model_validate(json.loads(filters))
            except (ValueError, ValidationError) as e:
                raise ValidationFailed("filters must be a JSON object of view filters") from e
            spec.filters = parsed.model_dump(mode="json", exclude_defaults=True)
        if group_by is not None:
            spec.group_by = group_by or None
        if sort is not None:
            spec.sort = _sort_param(sort)
        out = await rows_v2(s, ctx, p, spec)
        fields = {f.id: f for f in out.fields}
        return PortfolioRowsOut(
            columns=[ColumnOut(**c) for c in lifecycle.effective_columns(p, fields)],
            rows=[PortfolioRowOut.model_validate(r) for r in out.rows],
            groups=[
                PortfolioGroupOut(
                    key=g.key, label=g.label, project_ids=g.project_ids, rollup=g.rollup
                )
                for g in out.groups
            ]
            if out.groups is not None
            else None,
            hidden_projects=out.hidden,
            view_id=view_id,
        )


@router.patch(
    "/{portfolio_id}/settings",
    response_model=MutationOut[PortfolioDetailOut],
    summary="Rule, stage field, stage targets and gates, columns (editors; undoable)",
)
async def configure(
    portfolio_id: uuid.UUID, body: PortfolioConfigIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await lifecycle.configure(s, ctx, portfolio_id, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.post(
    "/{portfolio_id}/convert",
    response_model=MutationOut[PortfolioDetailOut],
    summary="Convert manual ↔ rule (undoable)",
)
async def convert(
    portfolio_id: uuid.UUID, body: ConvertIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await lifecycle.convert(s, ctx, portfolio_id, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


def _view_out(v: PortfolioView) -> PortfolioViewOut:
    return PortfolioViewOut(
        id=v.id,
        name=v.name,
        owner_id=v.owner_id,
        shared=v.owner_id is None,
        layout=v.layout,
        filters=v.filters or {},
        group_by=v.group_by,
        sort=v.sort or [],
        updated_at=v.updated_at,
    )


@router.get(
    "/{portfolio_id}/views",
    response_model=ListOut[PortfolioViewOut],
    summary="Shared views and your own",
)
async def list_views(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[PortfolioViewOut]:
    async with uow.transaction() as s:
        return ListOut(
            data=[_view_out(v) for v in await lifecycle.list_views(s, ctx, portfolio_id)]
        )


@router.post(
    "/{portfolio_id}/views",
    response_model=MutationOut[PortfolioViewOut],
    status_code=status.HTTP_201_CREATED,
    summary="Save a view (personal, or shared for editors)",
)
async def create_view(
    portfolio_id: uuid.UUID, body: PortfolioViewIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioViewOut]:
    async with uow.transaction() as s:
        m = await lifecycle.create_view(s, ctx, portfolio_id, body)
        await s.refresh(m.entity)
        return MutationOut(data=_view_out(m.entity), meta=MutationMeta(activity_id=m.activity_id))


@router.patch(
    "/{portfolio_id}/views/{view_id}",
    response_model=MutationOut[PortfolioViewOut],
    summary="Change a view",
)
async def update_view(
    portfolio_id: uuid.UUID,
    view_id: uuid.UUID,
    body: PortfolioViewPatchIn,
    ctx: CtxDep,
    uow: UowDep,
) -> MutationOut[PortfolioViewOut]:
    async with uow.transaction() as s:
        m = await lifecycle.update_view(s, ctx, portfolio_id, view_id, body)
        await s.refresh(m.entity)
        return MutationOut(data=_view_out(m.entity), meta=MutationMeta(activity_id=m.activity_id))


@router.delete(
    "/{portfolio_id}/views/{view_id}",
    response_model=MutationOut[OkOut],
    summary="Delete a view (undoable)",
)
async def delete_view(
    portfolio_id: uuid.UUID, view_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await lifecycle.delete_view(s, ctx, portfolio_id, view_id)
        return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.get(
    "/{portfolio_id}/members",
    response_model=ListOut[PortfolioMemberOut],
    summary="Who edits or views this portfolio besides its owner",
)
async def list_members(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[PortfolioMemberOut]:
    async with uow.transaction() as s:
        rows = await lifecycle.list_members(s, ctx, portfolio_id)
        return ListOut(
            data=[PortfolioMemberOut(user_id=u.id, name=u.name, role=m.role) for m, u in rows]
        )


@router.put(
    "/{portfolio_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Add a member or change their role (owner or admin; undoable)",
)
async def set_member(
    portfolio_id: uuid.UUID, user_id: uuid.UUID, body: PortfolioMemberIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await lifecycle.set_member(s, ctx, portfolio_id, user_id, body.role)
        return MutationOut(data=OkOut(), meta=_meta(m))


@router.delete(
    "/{portfolio_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Remove a member (owner or admin; undoable)",
)
async def remove_member(
    portfolio_id: uuid.UUID, user_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await lifecycle.set_member(s, ctx, portfolio_id, user_id, None)
        return MutationOut(data=OkOut(), meta=_meta(m))


def _readiness_out(r: Readiness) -> ReadinessOut:
    return ReadinessOut(
        stage=r.stage,
        stage_label=r.stage_label,
        met=r.met,
        items=[GateItemOut(kind=i.kind, label=i.label, met=i.met, ref=i.ref) for i in r.items],
    )


@router.get(
    "/{portfolio_id}/projects/{project_id}/readiness",
    response_model=ReadinessOut,
    summary="The stage gate checklist for moving a project into a stage",
)
async def project_readiness(
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    to: Annotated[str, Query(min_length=1, max_length=64)],
) -> ReadinessOut:
    async with uow.transaction() as s:
        return _readiness_out(await lifecycle.check_readiness(s, ctx, portfolio_id, project_id, to))


@router.post(
    "/{portfolio_id}/projects/{project_id}/stage",
    response_model=MutationOut[FieldValueOut],
    summary="Move a project to a stage (a board move; 409 gate_not_met unless override)",
    responses={409: {"description": "The gate isn't met: the body has the checklist"}},
)
async def move_stage(
    portfolio_id: uuid.UUID, project_id: uuid.UUID, body: StageMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FieldValueOut]:
    async with uow.transaction() as s:
        m = await lifecycle.move_stage(
            s, ctx, portfolio_id, project_id, body.to, override=body.override
        )
        p = await service.get_portfolio(s, ctx, portfolio_id)
        return MutationOut(
            data=FieldValueOut(field_id=p.stage_field_id, value=body.to),
            meta=MutationMeta(activity_id=m.activity_id),
        )


def _spec(
    filters: str | None, group_by: str | None, sort: str | None, base: ViewSpec | None = None
) -> ViewSpec:
    spec = base or ViewSpec()
    if filters is not None:
        try:
            parsed = ViewFiltersIn.model_validate(json.loads(filters))
        except (ValueError, ValidationError) as e:
            raise ValidationFailed("filters must be a JSON object of view filters") from e
        spec.filters = parsed.model_dump(mode="json", exclude_defaults=True)
    if group_by is not None:
        spec.group_by = group_by or None
    if sort is not None:
        spec.sort = _sort_param(sort)
    return spec


@router.post(
    "/{portfolio_id}/bulk-set-field",
    response_model=MutationOut[BulkSetFieldOut],
    summary="Set one project field on many rows (one undo: the batch)",
)
async def bulk_set_field(
    portfolio_id: uuid.UUID, body: BulkSetFieldIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[BulkSetFieldOut]:
    async with uow.transaction() as s:
        batch, updated, skipped = await lifecycle.bulk_set_field(
            s, ctx, portfolio_id, body.project_ids, body.field_id, body.value
        )
        return MutationOut(
            data=BulkSetFieldOut(updated=updated, skipped=skipped),
            meta=MutationMeta(batch_id=batch if updated else None),
        )


@router.get(
    "/{portfolio_id}/export/csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
    summary="The view as CSV (visible columns, as the table shows them)",
)
async def export_csv(
    portfolio_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    view_id: uuid.UUID | None = None,
    filters: Annotated[str | None, Query(max_length=4000)] = None,
    group_by: Annotated[str | None, Query(max_length=80)] = None,
    sort: Annotated[str | None, Query(max_length=400)] = None,
) -> Response:
    async with uow.transaction() as s:
        p = await service.get_portfolio(s, ctx, portfolio_id)
        base = None
        if view_id is not None:
            v = await lifecycle.get_view(s, ctx, p, view_id)
            base = ViewSpec(dict(v.filters or {}), v.group_by, list(v.sort or []))
        text = await lifecycle.rows_csv(s, ctx, p, _spec(filters, group_by, sort, base))
        name = p.name
    return Response(
        content="\ufeff" + text,  # a BOM so Excel reads UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition("attachment", f"{name}.csv")},
    )
