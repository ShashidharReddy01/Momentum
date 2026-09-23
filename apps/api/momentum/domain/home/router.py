from __future__ import annotations

from fastapi import APIRouter

from momentum.api.deps import CtxDep, UowDep
from momentum.domain.home import service
from momentum.domain.home.schemas import HomeCounts, HomeOut, HomeProjectOut
from momentum.domain.mytasks.router import my_task_rows

router = APIRouter(tags=["home"])


@router.get("/home", response_model=HomeOut, summary="Home page data in one round trip")
async def get_home(ctx: CtxDep, uow: UowDep) -> HomeOut:
    async with uow.transaction() as s:
        h = await service.home(s, ctx)
        return HomeOut(
            priorities=await my_task_rows(s, h.priorities),
            counts=HomeCounts(open=h.open, due_today=h.due_today, overdue=h.overdue),
            recent_projects=[
                HomeProjectOut(
                    id=r.project.id,
                    name=r.project.name,
                    color=r.project.color,
                    team_id=r.project.team_id,
                    team_name=r.team_name,
                    open_count=r.open_count,
                    overdue_count=r.overdue_count,
                    last_active_at=r.last_active_at,
                )
                for r in h.recent
            ],
            waiting=await my_task_rows(s, [(t, None) for t in h.waiting]),
            waiting_total=h.waiting_total,
            has_projects=h.has_projects,
        )
