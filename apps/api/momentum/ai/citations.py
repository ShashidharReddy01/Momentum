"""Citations in Mo's answers (S3.3.1): resolved as the reader by ``domain/references.py``
(the same resolution status updates use), so a made-up or private key never becomes a link."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import ConversationFile
from momentum.core.context import Ctx
from momentum.domain.references import CITE, MAX_CITATIONS, Citation, find_refs
from momentum.domain.references import resolve as resolve_refs

__all__ = ["CITE", "MAX_CITATIONS", "Citation", "find_refs", "resolve"]


async def resolve(
    session: AsyncSession, ctx: Ctx, text: str, *, conversation_id: uuid.UUID | None = None
) -> list[Citation]:
    """As ``references.resolve``, plus (Phase 7.5) a file cited from the reader's own
    conversation files, which only they can see."""
    out = await resolve_refs(session, ctx, text)
    if conversation_id is None or ctx.actor.id is None:
        return out
    fixed: list[Citation] = []
    for c in out:
        if c.type == "file" and not c.valid and c.title:
            cf = (
                await session.execute(
                    select(ConversationFile)
                    .where(
                        ConversationFile.conversation_id == conversation_id,
                        ConversationFile.user_id == ctx.actor.id,
                        func.lower(ConversationFile.filename) == c.title.lower(),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if cf is not None:
                c = Citation(c.ref, "file", True, None, c.key, cf.filename)
        fixed.append(c)
    return fixed
