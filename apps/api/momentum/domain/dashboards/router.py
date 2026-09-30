from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.domain.dashboards import service
from momentum.domain.dashboards.models import Dashboard, DashboardWidget
from momentum.domain.dashboards.schemas import (
    DashboardDetailOut,
    DashboardIn,
    DashboardOut,
    DashboardPatchIn,
    DrillIn,
    DrillOut,
    ProjectDashboardOut,
    QueryResultOut,
    VizIn,
    WidgetIn,
    WidgetMoveIn,
    WidgetOut,
    WidgetPatchIn,
    WidgetQueryIn,
)

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _out(d: Dashboard, editable: bool, count: int) -> DashboardOut:
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
    )


def _widget_out(w: DashboardWidget) -> WidgetOut:
    return WidgetOut(
        id=w.id,
        kind=w.kind,
        title=w.title,
        query_spec=service.widget_spec(w),
        viz=VizIn.model_validate(w.viz),
        version=w.version,
    )


async def _detail(s: AsyncSession, d: Dashboard, editable: bool) -> DashboardDetailOut:
    await s.refresh(d)
    widgets = await service.widgets_of(s, d)
    return DashboardDetailOut(
        **_out(d, editable, len(widgets)).model_dump(),
        widgets=[_widget_out(w) for w in widgets],
    )


def _meta(activity_id: uuid.UUID | None, version: int | None) -> MutationMeta:
    return MutationMeta(activity_id=activity_id, version=version)


@router.get("", response_model=ListOut[DashboardOut], summary="Workspace dashboards")
async def list_dashboards(ctx: CtxDep, uow: UowDep) -> ListOut[DashboardOut]:
    async with uow.transaction() as s:
        rows = await service.list_dashboards(s, ctx)
        return ListOut(
            data=[_out(d, ctx.actor.is_admin or d.owner_id == ctx.actor.id, n) for d, n in rows]
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
        return await service.run_query(s, ctx, body.kind, body.query_spec, body.project_id)


@router.post(
    "/drill",
    response_model=DrillOut,
    summary="The tasks behind one bar, slice, point or tile, as the viewer sees them",
)
async def drill(body: DrillIn, ctx: CtxDep, uow: UowDep) -> DrillOut:
    async with uow.transaction() as s:
        return await service.drill(s, ctx, body)


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
async def widget_data(widget_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> QueryResultOut:
    async with uow.transaction() as s:
        return await service.widget_data(s, ctx, widget_id)


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
        return await _detail(s, d, editable)


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
