from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.errors import NotFound
from momentum.domain.access import get_visible_project
from momentum.domain.users import service
from momentum.domain.users import tokens as token_service
from momentum.domain.users.models import User
from momentum.domain.users.schemas import (
    ApiTokenCreatedOut,
    ApiTokenIn,
    ApiTokenOut,
    MeOut,
    OnboardingPatchIn,
    OnboardingStatusOut,
    ProjectViewPrefs,
    UserInviteIn,
    UserOut,
    WorkspaceOut,
)
from momentum.domain.workspace.service import ensure_default_workspace

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeOut, summary="Current user and workspace")
async def me(ctx: CtxDep, uow: UowDep) -> MeOut:
    async with uow.transaction() as session:
        user, ws = await service.get_me(session, ctx)
        return MeOut(user=UserOut.model_validate(user), workspace=WorkspaceOut.model_validate(ws))


@router.get("/users", response_model=ListOut[UserOut], summary="Workspace members (for pickers)")
async def list_users(
    ctx: CtxDep,
    uow: UowDep,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=1000),
    agents: service.AgentFilter | None = Query(
        default=None,
        description="Also list agents: the enabled ones acting on `assigned`/`mentioned`, or `all`",
    ),
) -> ListOut[UserOut]:
    async with uow.transaction() as session:
        users = await service.list_users(session, ctx, q=q, limit=limit, agents=agents)
        return ListOut(data=[UserOut.model_validate(u) for u in users])


@router.get(
    "/users/members",
    response_model=ListOut[UserOut],
    summary="Every workspace member incl. invited/disabled (admin, for the Members page)",
)
async def list_members(ctx: CtxDep, uow: UowDep) -> ListOut[UserOut]:
    async with uow.transaction() as session:
        users = await service.list_members(session, ctx)
        return ListOut(data=[UserOut.model_validate(u) for u in users])


@router.post(
    "/users/invite",
    response_model=UserOut,
    summary="Invite a member by email (admin)",
)
async def invite_user(body: UserInviteIn, ctx: CtxDep, uow: UowDep) -> UserOut:
    async with uow.transaction() as session:
        user = await service.invite_user(session, ctx, body.email, body.name, body.role)
        return UserOut.model_validate(user)


@router.get(
    "/me/onboarding",
    response_model=OnboardingStatusOut,
    summary="First-run checklist status for the Home page",
)
async def get_onboarding(ctx: CtxDep, uow: UowDep) -> OnboardingStatusOut:
    async with uow.transaction() as session:
        status = await service.get_onboarding_status(session, ctx)
        return OnboardingStatusOut(
            created_project=status.created_project,
            tried_import=status.tried_import,
            used_command_palette=status.used_command_palette,
            dismissed=status.dismissed,
        )


@router.patch(
    "/me/onboarding",
    response_model=OnboardingStatusOut,
    summary="Mark a first-run checklist step done, or dismiss the checklist",
)
async def patch_onboarding(
    body: OnboardingPatchIn, ctx: CtxDep, uow: UowDep
) -> OnboardingStatusOut:
    async with uow.transaction() as session:
        await service.mark_onboarding(
            session, ctx, used_command_palette=body.used_command_palette, dismissed=body.dismissed
        )
        status = await service.get_onboarding_status(session, ctx)
        return OnboardingStatusOut(
            created_project=status.created_project,
            tried_import=status.tried_import,
            used_command_palette=status.used_command_palette,
            dismissed=status.dismissed,
        )


@router.get(
    "/me/prefs/views/{project_id}",
    response_model=ProjectViewPrefs,
    summary="My saved list view for a project (defaults if none)",
)
async def get_view_prefs(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ProjectViewPrefs:
    async with uow.transaction() as session:
        await get_visible_project(session, ctx, project_id)
        stored = await service.get_view_prefs(session, ctx, project_id)
    try:
        return ProjectViewPrefs.model_validate(stored or {})
    except ValueError:
        return ProjectViewPrefs()  # stored by an older version: fall back to defaults


@router.put(
    "/me/prefs/views/{project_id}",
    response_model=ProjectViewPrefs,
    summary="Save my list view for a project",
)
async def put_view_prefs(
    project_id: uuid.UUID, body: ProjectViewPrefs, ctx: CtxDep, uow: UowDep
) -> ProjectViewPrefs:
    async with uow.transaction() as session:
        await get_visible_project(session, ctx, project_id)
        await service.set_view_prefs(session, ctx, project_id, body.model_dump())
    return body


class LogoutOut(BaseModel):
    redirect_url: str


@router.post("/auth/logout", response_model=LogoutOut, summary="Sign out")
async def logout(request: Request, rt: RuntimeDep) -> JSONResponse:
    base = rt.settings.base_path
    body = LogoutOut(redirect_url=rt.auth.logout_url(f"{base}/"))
    response = JSONResponse(body.model_dump())
    if rt.settings.is_dev_auth:
        from momentum.auth.dev import DevSession

        DevSession(rt.settings).clear(response)
    return response


# ---- Dev-only login (registered only when AUTH_MODE is dev or easyauth-sim) ----

# ---------- API tokens (S5.1.6) ----------


@router.get("/me/tokens", response_model=ListOut[ApiTokenOut], summary="My API tokens")
async def list_my_tokens(ctx: CtxDep, uow: UowDep) -> ListOut[ApiTokenOut]:
    assert ctx.actor.id is not None
    async with uow.transaction() as s:
        rows = await token_service.list_tokens(s, ctx, ctx.actor.id)
        return ListOut(data=[ApiTokenOut.model_validate(t) for t in rows])


@router.post(
    "/me/tokens",
    response_model=ApiTokenCreatedOut,
    status_code=201,
    summary="Create an API token for scripts; the secret is shown only in this response",
)
async def create_my_token(body: ApiTokenIn, ctx: CtxDep, uow: UowDep) -> ApiTokenCreatedOut:
    async with uow.transaction() as s:
        m, secret = await token_service.create_token(
            s, ctx, name=body.name, scopes=body.scopes, expires_in_days=body.expires_in_days
        )
        return ApiTokenCreatedOut(data=ApiTokenOut.model_validate(m.entity), secret=secret)


@router.delete(
    "/me/tokens/{token_id}",
    response_model=MutationOut[OkOut],
    summary="Revoke one of my tokens (or, for admins, an agent's)",
)
async def revoke_token(token_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await token_service.revoke_token(s, ctx, token_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


dev_router = APIRouter(prefix="/dev", tags=["dev"])


@dev_router.get("/users", response_model=list[UserOut], summary="Users for the dev login page")
async def dev_users(rt: RuntimeDep, uow: UowDep) -> list[UserOut]:
    async with uow.transaction() as session:
        ws = await ensure_default_workspace(session, rt.settings)
        users = await service.list_dev_login_users(session, ws.id)
        return [UserOut.model_validate(u) for u in users]


class DevLoginIn(BaseModel):
    user_id: uuid.UUID


@dev_router.post("/login", response_model=UserOut, summary="Dev login as a seeded user")
async def dev_login(body: DevLoginIn, rt: RuntimeDep, uow: UowDep) -> JSONResponse:
    from momentum.auth.dev import DevSession

    async with uow.transaction() as session:
        user = await session.get(User, body.user_id)
        if user is None or user.status == "disabled" or user.is_agent:
            raise NotFound()
        out = UserOut.model_validate(user)
    response = JSONResponse(out.model_dump(mode="json"))
    DevSession(rt.settings).write(response, user_id=str(user.id), email=user.email, name=user.name)
    return response
