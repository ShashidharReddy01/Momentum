from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards import role_templates, service
from momentum.domain.dashboards.models import Dashboard, DashboardWidget
from momentum.domain.dashboards.schemas import (
    DashboardDetailOut,
    DashboardIn,
    DashboardOut,
    DashboardPatchIn,
    DashboardTemplateOut,
    DrillAnyIn,
    DrillOut,
    FromTemplateIn,
    FromTemplateOut,
    MemberIn,
    MemberOut,
    PortfolioDashboardOut,
    ProjectDashboardOut,
    QueryResultOut,
    TemplatePreviewOut,
    TemplateWidgetOut,
    VizIn,
    WidgetIn,
    WidgetMoveIn,
    WidgetOut,
    WidgetPatchIn,
    WidgetQueryIn,
)
from momentum.domain.dashboards.schemas_v2 import DashboardFilters
from momentum.domain.users.models import User

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _out(d: Dashboard, editable: bool, count: int, pinned: bool = False) -> DashboardOut:
    return DashboardOut(
        id=d.id,
        name=d.name,
        description=d.description,
        scope=d.scope,
        project_id=d.project_id,
        owner_id=d.owner_id,
        version=d.version,
        can_edit=editable,
        widget_count=count,
        created_at=d.created_at,
        updated_at=d.updated_at,
        filters=service.saved_filters(d),
        portfolio_id=d.portfolio_id,
        template=d.template,
        pinned=pinned,
    )


def _widget_out(w: DashboardWidget) -> WidgetOut:
    return WidgetOut(
        id=w.id,
        kind=w.kind,
        title=w.title,
        query_spec=service.widget_spec(w),
        viz=VizIn.model_validate(w.viz),
        version=w.version,
        created_from_prompt=w.created_from_prompt,
    )


async def _detail(
    s: AsyncSession, d: Dashboard, editable: bool, pinned: bool = False
) -> DashboardDetailOut:
    await s.refresh(d)
    widgets = await service.widgets_of(s, d)
    return DashboardDetailOut(
        **_out(d, editable, len(widgets), pinned).model_dump(),
        widgets=[_widget_out(w) for w in widgets],
    )


def _view_filters(raw: str | None) -> DashboardFilters | None:
    """The viewer's own filters for one view (JSON in the URL), never saved."""
    if raw is None:
        return None
    try:
        return DashboardFilters.model_validate_json(raw)
    except ValidationError as e:
        raise ValidationFailed(f"Bad filters: {e.errors()[0].get('msg', 'invalid')}") from None


def _meta(activity_id: uuid.UUID | None, version: int | None) -> MutationMeta:
    return MutationMeta(activity_id=activity_id, version=version)


@router.get("", response_model=ListOut[DashboardOut], summary="Workspace dashboards")
async def list_dashboards(ctx: CtxDep, uow: UowDep) -> ListOut[DashboardOut]:
    async with uow.transaction() as s:
        rows = await service.list_dashboards(s, ctx)
        editable = await service.can_edit_many(s, ctx, [d for d, _ in rows])
        pinned = set(await service.pinned_ids(s, ctx))
        return ListOut(data=[_out(d, editable[d.id], n, d.id in pinned) for d, n in rows])


@router.get("/pinned", response_model=ListOut[DashboardOut], summary="Dashboards pinned to my Home")
async def pinned_dashboards(ctx: CtxDep, uow: UowDep) -> ListOut[DashboardOut]:
    async with uow.transaction() as s:
        ids = await service.pinned_ids(s, ctx)
        out = []
        for did in ids:
            d, editable = await service.get_dashboard(s, ctx, did)
            out.append(_out(d, editable, len(await service.widgets_of(s, d)), True))
        return ListOut(data=out)


@router.get(
    "/templates",
    response_model=ListOut[DashboardTemplateOut],
    summary="The role dashboard templates",
)
async def list_templates(ctx: CtxDep) -> ListOut[DashboardTemplateOut]:
    return ListOut(data=[DashboardTemplateOut(**t) for t in role_templates.catalog()])


@router.post(
    "/from-template/preview",
    response_model=TemplatePreviewOut,
    summary="Bind a role template to a portfolio and show it, with what it leaves out",
)
async def preview_template(body: FromTemplateIn, ctx: CtxDep, uow: UowDep) -> TemplatePreviewOut:
    async with uow.transaction() as s:
        b = await role_templates.bind(s, ctx, body.template, body.portfolio_id)
        return TemplatePreviewOut(
            template=b.key,
            name=(body.name or "").strip() or b.name,
            description=b.description,
            filters=b.filters,
            widgets=[
                TemplateWidgetOut(
                    kind=w.kind,
                    title=w.title,
                    query_spec=w.spec,
                    viz=VizIn.model_validate({"size": w.size}),
                )
                for w in b.widgets
            ],
            notes=b.notes,
        )


@router.post(
    "/from-template",
    response_model=MutationOut[FromTemplateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard from a role template bound to a portfolio (undoable)",
)
async def from_template(
    body: FromTemplateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FromTemplateOut]:
    async with uow.transaction() as s:
        m, notes = await service.create_from_template(
            s, ctx, body.template, body.portfolio_id, body.name, portfolio_tab=body.portfolio_tab
        )
        return MutationOut(
            data=FromTemplateOut(dashboard=await _detail(s, m.entity, True), notes=notes),
            meta=_meta(m.activity_id, m.version),
        )


@router.get(
    "/portfolio/{portfolio_id}",
    response_model=PortfolioDashboardOut,
    summary="A portfolio's Dashboard tab: its dashboard, or none yet",
)
async def portfolio_dashboard(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> PortfolioDashboardOut:
    async with uow.transaction() as s:
        d, editable = await service.portfolio_dashboard(s, ctx, portfolio_id)
        pinned = set(await service.pinned_ids(s, ctx))
        return PortfolioDashboardOut(
            dashboard=await _detail(s, d, editable, d.id in pinned) if d else None,
            can_edit=editable,
        )


@router.post(
    "",
    response_model=MutationOut[DashboardDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard (a workspace one, or a project's; starter widgets by default)",
)
async def create_dashboard(
    body: DashboardIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[DashboardDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_dashboard(s, ctx, body)
        return MutationOut(
            data=await _detail(s, m.entity, True), meta=_meta(m.activity_id, m.version)
        )


@router.post(
    "/query",
    response_model=QueryResultOut,
    summary="Run an unsaved widget spec as the viewer (previews, the starter layout)",
)
async def run_query(body: WidgetQueryIn, ctx: CtxDep, uow: UowDep) -> QueryResultOut:
    async with uow.transaction() as s:
        return await service.run_query(
            s, ctx, body.kind, body.query_spec, body.project_id, body.filters
        )


@router.post(
    "/drill",
    response_model=DrillOut,
    summary="The tasks (or projects) behind one bar, slice, point, stage or tile, as the viewer "
    "sees them",
)
async def drill(body: DrillAnyIn, ctx: CtxDep, uow: UowDep) -> DrillOut:
    async with uow.transaction() as s:
        return await service.drill(s, ctx, body, body.split_key)


@router.get(
    "/project/{project_id}",
    response_model=ProjectDashboardOut,
    summary="A project's Dashboard tab: its saved dashboard, or the starter layout",
)
async def project_dashboard(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ProjectDashboardOut:
    async with uow.transaction() as s:
        d, editable = await service.project_dashboard(s, ctx, project_id)
        return ProjectDashboardOut(
            dashboard=await _detail(s, d, editable) if d else None,
            starter=service.starter("project"),
            can_edit=editable,
        )


@router.get(
    "/widgets/{widget_id}/data",
    response_model=QueryResultOut,
    summary="A widget's numbers, computed as the viewer",
)
async def widget_data(
    widget_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    filters: str | None = Query(
        default=None,
        max_length=4000,
        description="The viewer's own dashboard filters for this view (JSON); the saved ones "
        "when absent",
    ),
) -> QueryResultOut:
    view = _view_filters(filters)
    async with uow.transaction() as s:
        return await service.widget_data(
            s, ctx, widget_id, filters=view, cache=runtime.dashboard_cache
        )


@router.patch(
    "/widgets/{widget_id}",
    response_model=MutationOut[WidgetOut],
    summary="Change a widget (kind, title, spec, size)",
)
async def update_widget(
    widget_id: uuid.UUID, body: WidgetPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[WidgetOut]:
    async with uow.transaction() as s:
        m = await service.update_widget(s, ctx, widget_id, body)
        return MutationOut(data=_widget_out(m.entity), meta=_meta(m.activity_id, m.version))


@router.delete(
    "/widgets/{widget_id}", response_model=MutationOut[OkOut], summary="Remove a widget (undoable)"
)
async def remove_widget(widget_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.remove_widget(s, ctx, widget_id)
        return MutationOut(data=OkOut(), meta=_meta(m.activity_id, m.version))


@router.post(
    "/widgets/{widget_id}/move",
    response_model=MutationOut[WidgetOut],
    summary="Reorder a widget between two neighbours",
)
async def move_widget(
    widget_id: uuid.UUID, body: WidgetMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[WidgetOut]:
    async with uow.transaction() as s:
        m = await service.move_widget(s, ctx, widget_id, body)
        return MutationOut(data=_widget_out(m.entity), meta=_meta(m.activity_id, m.version))


@router.get(
    "/{dashboard_id}", response_model=DashboardDetailOut, summary="A dashboard and its widgets"
)
async def get_dashboard(dashboard_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> DashboardDetailOut:
    async with uow.transaction() as s:
        d, editable = await service.get_dashboard(s, ctx, dashboard_id)
        return await _detail(s, d, editable, d.id in set(await service.pinned_ids(s, ctx)))


@router.patch(
    "/{dashboard_id}",
    response_model=MutationOut[DashboardDetailOut],
    summary="Rename or describe a dashboard",
)
async def update_dashboard(
    dashboard_id: uuid.UUID, body: DashboardPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[DashboardDetailOut]:
    async with uow.transaction() as s:
        m = await service.update_dashboard(s, ctx, dashboard_id, body)
        return MutationOut(
            data=await _detail(s, m.entity, True), meta=_meta(m.activity_id, m.version)
        )


@router.delete(
    "/{dashboard_id}",
    response_model=MutationOut[OkOut],
    summary="Delete a dashboard (a project's goes back to the starter layout; undoable)",
)
async def delete_dashboard(dashboard_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_dashboard(s, ctx, dashboard_id)
        return MutationOut(data=OkOut(), meta=_meta(m.activity_id, m.version))


@router.post(
    "/{dashboard_id}/widgets",
    response_model=MutationOut[WidgetOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a widget",
)
async def add_widget(
    dashboard_id: uuid.UUID, body: WidgetIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[WidgetOut]:
    async with uow.transaction() as s:
        m = await service.add_widget(s, ctx, dashboard_id, body)
        return MutationOut(data=_widget_out(m.entity), meta=_meta(m.activity_id, m.version))


@router.get(
    "/{dashboard_id}/members",
    response_model=ListOut[MemberOut],
    summary="Who besides the owner edits (or is listed on) a dashboard",
)
async def list_members(dashboard_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[MemberOut]:
    async with uow.transaction() as s:
        members = await service.list_members(s, ctx, dashboard_id)
        names = {
            u.id: u.name
            for u in (
                await s.execute(select(User).where(User.id.in_([m.user_id for m in members])))
            ).scalars()
        }
        return ListOut(
            data=[
                MemberOut(user_id=m.user_id, name=names.get(m.user_id, ""), role=m.role)
                for m in members
            ]
        )


@router.put(
    "/{dashboard_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Add a member or change their role (the owner or an admin)",
)
async def set_member(
    dashboard_id: uuid.UUID, user_id: uuid.UUID, body: MemberIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.set_member(s, ctx, dashboard_id, user_id, body.role)
        return MutationOut(data=OkOut(), meta=_meta(m.activity_id, m.version))


@router.delete(
    "/{dashboard_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Remove a member (undoable)",
)
async def remove_member(
    dashboard_id: uuid.UUID, user_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.set_member(s, ctx, dashboard_id, user_id, None)
        return MutationOut(data=OkOut(), meta=_meta(m.activity_id, m.version))


@router.put("/{dashboard_id}/pin", response_model=OkOut, summary="Pin to my Home")
async def pin(dashboard_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.pin(s, ctx, dashboard_id, True)
        return OkOut()


@router.delete("/{dashboard_id}/pin", response_model=OkOut, summary="Unpin from my Home")
async def unpin(dashboard_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.pin(s, ctx, dashboard_id, False)
        return OkOut()
