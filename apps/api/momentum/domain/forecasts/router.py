from __future__ import annotations

import uuid

from fastapi import APIRouter

from momentum.api.deps import CtxDep, UowDep
from momentum.domain.forecasts import service
from momentum.domain.forecasts.models import Forecast
from momentum.domain.forecasts.schemas import DriverOut, ForecastOut, ProjectForecastOut
from momentum.domain.projects.models import Project

router = APIRouter(tags=["forecasts"])


def forecast_out(f: Forecast, project: Project) -> ForecastOut:
    return ForecastOut(
        id=f.id,
        project_id=f.project_id,
        computed_at=f.computed_at,
        as_of=f.as_of,
        status=f.status,
        p50=f.p50,
        p80=f.p80,
        p95=f.p95,
        due_on=project.due_on,
        risk_score=f.risk_score,
        risk_level=f.risk_level,
        drivers=[DriverOut.model_validate(d) for d in f.drivers],
        inputs=f.inputs,
    )


@router.get(
    "/projects/{project_id}/forecast",
    response_model=ProjectForecastOut,
    summary="A project's latest forecast (P50/P80/P95 finish dates) and risk score",
)
async def get_forecast(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ProjectForecastOut:
    async with uow.transaction() as s:
        project, f = await service.get_forecast(s, ctx, project_id)
        return ProjectForecastOut(forecast=forecast_out(f, project) if f else None)


@router.post(
    "/projects/{project_id}/forecast",
    response_model=ProjectForecastOut,
    summary="Recompute a project's forecast now",
)
async def refresh_forecast(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ProjectForecastOut:
    async with uow.transaction() as s:
        f = await service.refresh(s, ctx, project_id)
        project = await s.get(Project, project_id)
        assert project is not None
        return ProjectForecastOut(forecast=forecast_out(f, project))
