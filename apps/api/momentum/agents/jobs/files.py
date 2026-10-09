"""Phase 7.6 S76-09: ``job.files``, a job's reads of the files on its task (an invoice agent's
input). Listing is a recorded step (a replay sees the same files even if someone attaches another
meanwhile); reading a file's bytes happens inside a step and isn't stored (attachments are
immutable once uploaded, so a replay reads the same bytes), and only for files the agent can
see."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.packs.pack import PackError
from momentum.domain.attachments import service as attachments

if TYPE_CHECKING:
    from momentum.agents.jobs.job import JobState


class FileRef(BaseModel):
    """A file on the job's task, as a job sees it."""

    id: uuid.UUID
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    task_id: uuid.UUID | None
    source: str


class JobFiles:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def list(self, key: str, task_id: uuid.UUID | None = None) -> list[FileRef]:
        """The current version of every file on ``task_id`` (default: the job's task), oldest
        first."""
        state = self._state
        target = task_id or state.task_id
        if target is None:
            raise PackError("This job has no task, so it has no files")

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[FileRef]:
            rows = await attachments.list_for_task(s, state.ctx, target)
            return [
                FileRef(
                    id=a.id,
                    filename=a.filename,
                    mime=a.mime,
                    size_bytes=a.size_bytes,
                    sha256=a.sha256,
                    task_id=a.task_id,
                    source=a.source,
                )
                for a in rows
            ]

        return cast(
            list[FileRef], await state.run_step(key, "step", body, TypeAdapter(list[FileRef]))
        )

    async def read(self, file_id: uuid.UUID) -> bytes:
        """A file's bytes, inside a step; only a file the agent can see."""
        state = self._state
        if state.scope is None:
            raise PackError("job.files.read can only be called inside a step")
        att = await attachments.get_visible_attachment(state.scope.session, state.ctx, file_id)
        return await state.storage.read(att.storage_key)
