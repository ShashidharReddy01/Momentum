from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from momentum.api.deps import CtxDep, UowDep
from momentum.domain.search import service
from momentum.domain.search.schemas import ALL_TYPES, SearchResultsOut, SearchType

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResultsOut,
    summary="Global search across tasks, projects, people, and comments",
)
async def global_search(
    ctx: CtxDep,
    uow: UowDep,
    q: str = Query(default="", max_length=200),
    type: str | None = Query(
        default=None, description="Comma-separated: task,project,person,comment"
    ),
    project_id: uuid.UUID | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    completed: bool | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=50),
) -> SearchResultsOut:
    types: tuple[SearchType, ...] = ALL_TYPES
    if type:
        wanted = {t.strip() for t in type.split(",") if t.strip()}
        types = tuple(t for t in ALL_TYPES if t in wanted)
    async with uow.transaction() as s:
        return await service.search(
            s,
            ctx,
            q,
            types=types,
            project_id=str(project_id) if project_id else None,
            assignee_id=str(assignee_id) if assignee_id else None,
            completed=completed,
            limit=limit,
        )
