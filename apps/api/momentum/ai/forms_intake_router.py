"""S4.2.2 conversational intake API. Lives in ``momentum.ai`` (not ``domain.forms``) because it
calls the LLM, and domain must not depend on AI (import-linter contract). ``router`` is the
authenticated internal link; ``public_router`` mirrors ``domain/forms/router.py``'s public forms
router (no ``CtxDep``, mounted under the CSRF-exempt ``/api/v1/public/`` prefix).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from momentum.ai.conversational_intake import converse
from momentum.ai.router import require_llm
from momentum.api.deps import CtxDep, RuntimeDep, UowDep, client_ip
from momentum.api.schemas import OkOut
from momentum.core.context import Actor, Ctx
from momentum.core.errors import NotFound
from momentum.domain.forms import service
from momentum.domain.forms.models import Form
from momentum.domain.forms.schemas import ConverseIn, ConverseSubmitIn, ConverseTurnOut

router = APIRouter(tags=["forms-intake"])
public_router = APIRouter(prefix="/public/forms", tags=["forms-intake-public"])


def _require_conversational(form: Form) -> None:
    if not form.conversational:
        raise NotFound("This form doesn't offer a conversational link")


@router.post(
    "/forms/{form_id}/converse",
    response_model=ConverseTurnOut,
    summary="One turn of the conversational intake (internal link)",
)
async def converse_internal(
    form_id: uuid.UUID, body: ConverseIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ConverseTurnOut:
    llm = require_llm(rt)
    ai_ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        form = await service.get_form_to_submit(s, ai_ctx, form_id)
        _require_conversational(form)
        return await converse(s, llm, ai_ctx, form, body.history)


@router.post(
    "/forms/{form_id}/converse/submit",
    response_model=OkOut,
    summary="Confirm and submit a conversational intake (internal link)",
)
async def converse_submit_internal(
    form_id: uuid.UUID, body: ConverseSubmitIn, ctx: CtxDep, uow: UowDep
) -> OkOut:
    async with uow.transaction() as s:
        form = await service.get_form_to_submit(s, ctx, form_id)
        _require_conversational(form)
        await service.submit_conversational(
            s,
            ctx.settings,
            form,
            body.answers,
            body.history,
            submitted_by=ctx.actor.id,
            ip_hash=None,
            rate_limited=False,
        )
    return OkOut()


@public_router.post(
    "/{token}/converse",
    response_model=ConverseTurnOut,
    summary="One turn of the conversational intake (public link; rate limited)",
)
async def converse_public(
    token: str, body: ConverseIn, request: Request, uow: UowDep, rt: RuntimeDep
) -> ConverseTurnOut:
    llm = require_llm(rt)
    async with uow.transaction() as s:
        form = await service.get_public_form(s, token)
        _require_conversational(form)
        ip_hash = service.hash_ip(rt.settings, client_ip(request, rt.settings.trusted_proxy_hops))
        await service.rate_limit_turn(s, rt.settings, form.id, ip_hash)
        ai_ctx = Ctx(
            actor=Actor(id=None, workspace_id=form.workspace_id), settings=rt.settings, via="ai"
        )
        return await converse(s, llm, ai_ctx, form, body.history)


@public_router.post(
    "/{token}/converse/submit",
    response_model=OkOut,
    summary="Confirm and submit a conversational intake (public link; rate limited)",
)
async def converse_submit_public(
    token: str, body: ConverseSubmitIn, request: Request, uow: UowDep, rt: RuntimeDep
) -> OkOut:
    async with uow.transaction() as s:
        form = await service.get_public_form(s, token)
        _require_conversational(form)
        ip_hash = service.hash_ip(rt.settings, client_ip(request, rt.settings.trusted_proxy_hops))
        await service.submit_conversational(
            s,
            rt.settings,
            form,
            body.answers,
            body.history,
            submitted_by=None,
            ip_hash=ip_hash,
            rate_limited=True,
        )
    return OkOut()
