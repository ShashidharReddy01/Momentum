"""Phase 7.6 S76-03 (spec §5): reading and answering agents' questions. Thread replies are
interpreted in ``agents/router.py`` (it needs the model)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut
from momentum.domain.asks import service
from momentum.domain.asks.schemas import AnswerIn, AskOut

router = APIRouter(tags=["asks"])


@router.get(
    "/asks",
    response_model=ListOut[AskOut],
    summary="Agents' questions: mine (default) or all I can see; open ones by default",
)
async def list_asks(
    ctx: CtxDep,
    uow: UowDep,
    mine: bool = Query(default=True),
    status: Literal["open", "answered", "expired", "cancelled", "all"] = Query(default="open"),
) -> ListOut[AskOut]:
    async with uow.transaction() as s:
        rows = await service.list_asks(
            s, ctx, mine=mine, status=None if status == "all" else status
        )
        return ListOut(data=[await service.ask_out(s, ctx, a) for a in rows])


@router.get("/asks/{ask_id}", response_model=AskOut, summary="One question (for its card)")
async def get_ask(ask_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> AskOut:
    async with uow.transaction() as s:
        return await service.ask_out(s, ctx, await service.get_ask(s, ctx, ask_id))


@router.post(
    "/asks/{ask_id}/answer",
    response_model=AskOut,
    summary="Answer a question (only the people it's for; never guests); undoable until the"
    " agent uses the answer",
)
async def answer_ask(ask_id: uuid.UUID, body: AnswerIn, ctx: CtxDep, uow: UowDep) -> AskOut:
    async with uow.transaction() as s:
        ask = await service.answer_ask(s, ctx, ask_id, body.value, via=body.via)
        return await service.ask_out(s, ctx, ask)
