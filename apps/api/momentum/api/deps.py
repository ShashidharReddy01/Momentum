"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

import structlog
from fastapi import Depends, Request

from momentum.api.runtime import MomentumRuntime
from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import Unauthenticated


def get_runtime(request: Request) -> MomentumRuntime:
    return cast(MomentumRuntime, request.app.state.momentum)


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    rt = get_runtime(request)
    uow = UnitOfWork(rt.session_factory())
    try:
        yield uow
    finally:
        await uow.close()


async def get_ctx(request: Request, uow: Annotated[UnitOfWork, Depends(get_uow)]) -> Ctx:
    from momentum.auth.tokens import check_scope, resolve

    rt = get_runtime(request)
    principal = await rt.auth.authenticate(request)
    return_to = str(request.headers.get("x-momentum-return-to") or f"{rt.settings.base_path}/")
    if principal is None:
        raise Unauthenticated(login_url=rt.auth.login_url(return_to))
    async with uow.transaction() as session:
        resolved = await resolve(session, rt.settings, principal)
    user, workspace = resolved.user, resolved.workspace
    if resolved.scopes is not None:  # an API token (S5.1.6): its scopes narrow what it may do
        check_scope(resolved.scopes, request.method, request.url.path)
    actor = Actor(
        id=user.id,
        workspace_id=workspace.id,
        role=user.role,
        is_agent=user.is_agent,
        email=user.email,
        name=user.name,
        timezone=user.timezone,
    )
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return Ctx(
        actor=actor,
        settings=rt.settings,
        request_id=request.state.request_id,
        via="api" if resolved.scopes is not None else "ui",
    )


CtxDep = Annotated[Ctx, Depends(get_ctx)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
RuntimeDep = Annotated[MomentumRuntime, Depends(get_runtime)]
