"""S4.2.1: forms API. ``router`` is the ordinary authenticated CRUD + internal submission;
``public_router`` is mounted at ``/api/v1/public/forms`` (excluded from CSRF, no ``CtxDep`` — see
``app.py``'s ``CSRF_EXEMPT`` and ``momentum/core/http.py``'s ``CsrfMiddleware``) and is the one
unauthenticated write path in the app.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationOut, OkOut
from momentum.domain.forms import service
from momentum.domain.forms.schemas import (
    FormIn,
    FormOut,
    FormPatchIn,
    PublicFormOut,
    SubmitFormIn,
)

router = APIRouter(tags=["forms"])
public_router = APIRouter(prefix="/public/forms", tags=["forms-public"])


@router.get("/forms", response_model=ListOut[FormOut], summary="A project's forms")
async def list_forms(ctx: CtxDep, uow: UowDep, project_id: uuid.UUID) -> ListOut[FormOut]:
    async with uow.transaction() as s:
        forms = await service.list_forms(s, ctx, project_id)
        return ListOut(data=[FormOut.model_validate(f) for f in forms])


@router.post(
    "/forms",
    response_model=MutationOut[FormOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a form (project admins)",
)
async def create_form(body: FormIn, ctx: CtxDep, uow: UowDep) -> MutationOut[FormOut]:
    async with uow.transaction() as s:
        m = await service.create_form(s, ctx, body)
        return MutationOut.of(m, FormOut)


@router.get("/forms/{form_id}", response_model=FormOut, summary="One form")
async def get_form(form_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> FormOut:
    async with uow.transaction() as s:
        return FormOut.model_validate(await service.get_form(s, ctx, form_id))


@router.patch(
    "/forms/{form_id}",
    response_model=MutationOut[FormOut],
    summary="Edit, enable or disable a form",
)
async def patch_form(
    form_id: uuid.UUID, body: FormPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FormOut]:
    async with uow.transaction() as s:
        m = await service.update_form(s, ctx, form_id, body)
        return MutationOut.of(m, FormOut)


@router.delete("/forms/{form_id}", response_model=OkOut, summary="Delete a form")
async def delete_form(form_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.delete_form(s, ctx, form_id)
    return OkOut()


@router.post(
    "/forms/{form_id}/submit",
    response_model=OkOut,
    summary="Submit a form while signed in (the internal link)",
)
async def submit_form_internal(
    form_id: uuid.UUID, body: SubmitFormIn, ctx: CtxDep, uow: UowDep
) -> OkOut:
    async with uow.transaction() as s:
        form = await service.get_form(s, ctx, form_id)
        await service.submit_form(
            s,
            ctx.settings,
            form,
            body,
            submitted_by=ctx.actor.id,
            ip_hash=None,
            rate_limited=False,
        )
    return OkOut()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@public_router.get(
    "/{token}", response_model=PublicFormOut, summary="A public form's questions (no login)"
)
async def get_public_form(token: str, uow: UowDep) -> PublicFormOut:
    async with uow.transaction() as s:
        form = await service.get_public_form(s, token)
        return await service.public_form_view(s, form)


@public_router.post(
    "/{token}/submit",
    response_model=OkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a public form (no login; rate limited)",
)
async def submit_public_form(
    token: str, body: SubmitFormIn, request: Request, uow: UowDep, rt: RuntimeDep
) -> OkOut:
    async with uow.transaction() as s:
        form = await service.get_public_form(s, token)
        ip_hash = service.hash_ip(rt.settings, _client_ip(request))
        await service.submit_form(
            s,
            rt.settings,
            form,
            body,
            submitted_by=None,
            ip_hash=ip_hash,
            rate_limited=True,
        )
    return OkOut()
