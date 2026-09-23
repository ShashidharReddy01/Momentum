from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.core.errors import NotFound
from momentum.domain.users import service
from momentum.domain.users.models import User
from momentum.domain.users.schemas import MeOut, UserOut, WorkspaceOut
from momentum.domain.workspace.service import ensure_default_workspace

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeOut, summary="Current user and workspace")
async def me(ctx: CtxDep, uow: UowDep) -> MeOut:
    async with uow.transaction() as session:
        user, ws = await service.get_me(session, ctx)
        return MeOut(user=UserOut.model_validate(user), workspace=WorkspaceOut.model_validate(ws))


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
