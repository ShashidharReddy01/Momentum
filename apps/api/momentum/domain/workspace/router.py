"""S5.1.2: workspace-wide settings that aren't AI policy (that's ``/ai/admin/settings``)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import MutationMeta, MutationOut
from momentum.domain.workspace import service
from momentum.domain.workspace.models import Workspace

router = APIRouter(tags=["workspace"])


class WorkspaceSettingsOut(BaseModel):
    timezone: str


class WorkspaceSettingsIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


@router.get(
    "/workspace/settings", response_model=WorkspaceSettingsOut, summary="Workspace settings"
)
async def get_settings(ctx: CtxDep, uow: UowDep) -> WorkspaceSettingsOut:
    async with uow.transaction() as s:
        ws = await s.get(Workspace, ctx.workspace_id)
        return WorkspaceSettingsOut(timezone=service.workspace_timezone(ws) if ws else "UTC")


@router.put(
    "/workspace/settings",
    response_model=MutationOut[WorkspaceSettingsOut],
    summary="Change workspace settings: the timezone agent schedules use (admins)",
)
async def put_settings(
    body: WorkspaceSettingsIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[WorkspaceSettingsOut]:
    async with uow.transaction() as s:
        m = await service.set_workspace_timezone(s, ctx, body.timezone)
    return MutationOut(
        data=WorkspaceSettingsOut(timezone=m.entity), meta=MutationMeta(activity_id=m.activity_id)
    )
