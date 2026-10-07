"""Phase 7.5 (spec §8): a short digest of a file for the readiness check and the handoff note,
read only when the person ticks "also read files".

The same parse the file tools use (``file_outline`` + ``search_in_file``): the outline, the start
of the text and the passages around the words asked about. The attachment must be visible to the
viewer (the download gate). A digest is data in the prompt, never instructions.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.file_context import attachment_handle
from momentum.core.context import Ctx
from momentum.core.storage import build_storage
from momentum.files.cache import get_or_parse
from momentum.files.model import ImageRef, TextBlock

START_CHARS = 1500
SNIPPET = 160
MAX_MATCHES = 5


async def file_digest(
    session: AsyncSession,
    ctx: Ctx,
    attachment_id: uuid.UUID,
    *,
    words: tuple[str, ...] = (),
) -> dict[str, Any]:
    h = await attachment_handle(session, ctx, attachment_id)
    parsed = await get_or_parse(
        session, h.source(), storage=build_storage(ctx.settings), settings=ctx.settings
    )
    out: dict[str, Any] = {"file": h.filename}
    if parsed.status in ("encrypted", "unsupported", "failed"):
        out["unreadable"] = parsed.status
        return out
    m = parsed.model
    text = "\n".join(b.text for b in m.blocks if isinstance(b, TextBlock))
    out["outline"] = [o.title for o in m.outline][:20]
    out["start"] = text[:START_CHARS]
    if any(isinstance(b, ImageRef) and b.scanned for b in m.blocks) and not text.strip():
        out["scanned"] = True  # an image-only page: no text to check
    matches: list[str] = []
    for w in words:
        for hit in re.finditer(re.escape(w), text, re.I):
            a = max(0, hit.start() - SNIPPET // 2)
            matches.append(" ".join(text[a : a + SNIPPET].split()))
            if len(matches) >= MAX_MATCHES:
                break
    if matches:
        out["passages"] = list(dict.fromkeys(matches))
    return out
