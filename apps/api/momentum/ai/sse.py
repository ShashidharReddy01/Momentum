"""Server-sent events for AI runs (api-conventions §8).

The run executes as a task writing events to a queue while the response streams them, so the
client sees tool activity as it happens. It gets its **own** unit of work: FastAPI finishes
``yield`` dependencies before a streaming body is sent, so the request's session can't be used.
Failures end the stream with one ``error`` event carrying a failure kind, never gateway text.
A client that disconnects cancels the run (its transaction rolls back).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.errors import AIDisabled, AIUnavailable, BudgetExceeded
from momentum.ai.loop import Emit
from momentum.api.runtime import MomentumRuntime
from momentum.core.db import UnitOfWork
from momentum.core.errors import DomainError
from momentum.core.telemetry import get_logger

log = get_logger("ai.sse")
Work = Callable[[AsyncSession, Emit], Awaitable[None]]


def format_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def _error(e: BaseException) -> dict[str, Any]:
    if isinstance(e, AIUnavailable):
        return {"reason": e.reason, "message": "Mo is unavailable right now. Try again shortly."}
    if isinstance(e, AIDisabled):
        return {"reason": "disabled", "message": "AI is turned off for this workspace."}
    if isinstance(e, BudgetExceeded):
        return {"reason": "budget", "message": "This month's AI budget is used up."}
    if isinstance(e, DomainError):
        return {"reason": e.code, "message": e.detail}
    return {"reason": "internal", "message": "Something went wrong."}


def stream(rt: MomentumRuntime, work: Work) -> StreamingResponse:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str, data: dict[str, Any]) -> None:
        await queue.put(format_event(event, data))

    async def run() -> None:
        uow = UnitOfWork(rt.session_factory())
        try:
            async with uow.transaction() as session:
                await work(session, emit)
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            if not isinstance(e, DomainError):
                log.exception("ai_stream_failed")
            await queue.put(format_event("error", _error(e)))
        finally:
            await uow.close()
            await queue.put(None)

    async def body() -> AsyncIterator[str]:
        task = asyncio.create_task(run())
        try:
            while (chunk := await queue.get()) is not None:
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
