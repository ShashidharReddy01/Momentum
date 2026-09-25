"""S2.6.1: the text-extraction job (pdf/docx/plain text -> `attachments.text_extract`).

This is the first Procrastinate task in the codebase that touches the database — `heartbeat`
(`jobs/tasks.py`) never has. A job process has no FastAPI `app.state` to borrow a session
factory from, so it builds its own engine lazily, once per worker process, from a fresh
`Settings()` read (the same construction `create_app()` and the CLI's `uow` command each do
independently — there's no shared runtime object a job can reach into).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from momentum.core.db import create_engine, create_session_factory
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.core.telemetry import get_logger
from momentum.domain.attachments.models import Attachment
from momentum.domain.attachments.service import extract_text_from_bytes
from momentum.jobs.tasks import blueprint

log = get_logger("jobs.attachments")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        settings = Settings()
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


@blueprint.task(name="extract_text", queue="momentum_default")
async def extract_text(attachment_id: str) -> None:
    settings = Settings()
    storage = build_storage(settings)
    session_factory = _get_session_factory()
    async with session_factory() as session:
        att = await session.get(Attachment, uuid.UUID(attachment_id))
        if att is None or att.deleted_at is not None:
            return
        try:
            data = await storage.read(att.storage_key)
            text = extract_text_from_bytes(data, att.mime)
        except Exception:
            log.exception("extract_text_failed", attachment_id=attachment_id)
            att.extract_status = "failed"
            await session.commit()
            return
        att.text_extract = text
        att.extract_status = "done" if text is not None else "skipped"
        await session.commit()
