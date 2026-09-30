from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Query

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import MutationMeta, MutationOut
from momentum.core.context import Ctx
from momentum.core.mutation import Mutation
from momentum.domain.workload import service
from momentum.domain.workload.schemas import (
    HoursIn,
    HoursOut,
    PersonLoadOut,
    WeekLoadOut,
    WorkloadOut,
    WorkloadTaskOut,
)

router = APIRouter(prefix="/workload", tags=["workload"])


def _person(ctx: Ctx, p: service.PersonLoad) -> PersonLoadOut:
    u = p.user
    return PersonLoadOut(
        user_id=u.id if u else None,
        name=u.name if u else "Unassigned",
        avatar_url=u.avatar_url if u else None,
        weekly_minutes=p.weekly_minutes,
        hours_source=p.hours_source,
        can_edit=u is not None
        and not ctx.actor.is_agent
        and (ctx.actor.is_admin or ctx.actor.id == u.id),
        no_date=p.no_date,
        hidden=p.hidden,
        weeks=[
            WeekLoadOut(
                week_start=w.week_start,
                capacity_minutes=w.capacity_minutes,
                override=w.override,
                planned_minutes=round(w.planned_minutes),
                task_count=w.task_count,
                unestimated=w.unestimated,
            )
            for w in p.weeks.values()
        ],
    )


@router.get("", response_model=WorkloadOut, summary="Who is carrying what, week by week")
async def get_workload(
    ctx: CtxDep,
    uow: UowDep,
    start: date | None = Query(default=None, description="A day in the first week (default today)"),
    weeks: int = Query(default=6, ge=1, le=service.MAX_WEEKS),
    project_id: uuid.UUID | None = Query(default=None, description="Only this project's work"),
) -> WorkloadOut:
    async with uow.transaction() as s:
        w = await service.workload(
            s, ctx, start or datetime.now(UTC).date(), weeks, project_id=project_id
        )
        return WorkloadOut(
            start=w.start,
            weeks=w.weeks,
            default_minutes=w.default_minutes,
            default_source=w.default_source,
            can_admin=ctx.actor.is_admin and not ctx.actor.is_agent,
            people=[_person(ctx, p) for p in w.people],
            unassigned=_person(ctx, w.unassigned),
            tasks=[
                WorkloadTaskOut(
                    id=t.task.id,
                    number=t.task.number,
                    title=t.task.title,
                    assignee_id=t.task.assignee_id,
                    start_on=t.task.start_on,
                    due_on=t.task.due_on,
                    estimate_minutes=t.task.estimate_minutes,
                    project_id=t.project_id,
                    project_name=t.project_name,
                    overdue=t.overdue,
                    version=t.task.version,
                    weeks={k.isoformat(): round(v) for k, v in t.weeks.items()},
                )
                for t in w.tasks
            ],
        )


def _out(m: Mutation[float | None]) -> MutationOut[HoursOut]:
    return MutationOut(data=HoursOut(hours=m.entity), meta=MutationMeta(activity_id=m.activity_id))


@router.put(
    "/people/{user_id}/hours",
    response_model=MutationOut[HoursOut],
    summary="A person's usual weekly hours (themselves or an admin)",
)
async def put_hours(
    user_id: uuid.UUID, body: HoursIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[HoursOut]:
    async with uow.transaction() as s:
        return _out(await service.set_weekly_hours(s, ctx, user_id, body.hours))


@router.put(
    "/people/{user_id}/weeks/{week_start}",
    response_model=MutationOut[HoursOut],
    summary="A person's hours for one week, e.g. time off (themselves or an admin)",
)
async def put_week(
    user_id: uuid.UUID, week_start: date, body: HoursIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[HoursOut]:
    async with uow.transaction() as s:
        return _out(await service.set_week(s, ctx, user_id, week_start, body.hours))


@router.put(
    "/settings",
    response_model=MutationOut[HoursOut],
    summary="The workspace's default weekly hours (admins)",
)
async def put_default(body: HoursIn, ctx: CtxDep, uow: UowDep) -> MutationOut[HoursOut]:
    async with uow.transaction() as s:
        return _out(await service.set_default_hours(s, ctx, body.hours))
