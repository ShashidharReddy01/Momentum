"""Phase 7.6 S76-04 (spec §6.5-§6.6): ``job.records``, a job's reads of records, each a recorded
step (reads between steps would make a replay take a different path)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.packs.pack import PackError
from momentum.domain.records import query as records_query
from momentum.domain.records import service as records_service
from momentum.domain.records.models import Record

if TYPE_CHECKING:
    from momentum.agents.jobs.job import JobState


class RecordView(BaseModel):
    """A record as a job sees it."""

    id: uuid.UUID
    type: str
    type_version: int
    status: str
    title: str
    version: int
    data: dict[str, Any]
    checks: list[dict[str, Any]]
    decision: dict[str, Any] | None
    amount: Decimal | None
    currency: str | None
    occurred_on: date | None
    task_id: uuid.UUID | None
    identity_key: str | None
    confidence: float | None = None


def _view(r: Record) -> RecordView:
    return RecordView(
        id=r.id,
        type=r.type,
        type_version=r.type_version,
        status=r.status,
        title=r.title,
        version=r.version,
        data=r.data,
        checks=r.checks,
        decision=r.decision,
        amount=r.amount,
        currency=r.currency,
        occurred_on=r.occurred_on,
        task_id=r.task_id,
        identity_key=r.identity_key,
        confidence=float(r.confidence) if r.confidence is not None else None,
    )


class Similar(BaseModel):
    record: RecordView
    similarity: float


class JobRecords:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def get(self, key: str, record_id: uuid.UUID) -> RecordView:
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> RecordView:
            return _view(await records_service.get_record(s, state.ctx, record_id))

        return cast(RecordView, await state.run_step(key, "step", body, TypeAdapter(RecordView)))

    async def by_source(self, key: str, sha256: str) -> list[RecordView]:
        """S76-09: live records made from a file with this content (any type), oldest first —
        the same file processed before."""
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[RecordView]:
            from sqlalchemy import select

            rows = await s.execute(
                select(Record)
                .where(
                    Record.workspace_id == state.workspace_id,
                    Record.source_sha256 == sha256,
                    Record.deleted_at.is_(None),
                    Record.status.notin_(("void", "superseded")),
                )
                .order_by(Record.created_at)
            )
            return [_view(r) for r in rows.scalars()]

        return cast(
            list[RecordView],
            await state.run_step(key, "step", body, TypeAdapter(list[RecordView])),
        )

    async def find_duplicates(
        self,
        key: str,
        type: str,
        data: dict[str, Any],
        *,
        exclude: uuid.UUID | None = None,
    ) -> list[RecordView]:
        """Live records of ``type`` with the same identity as ``data``, anywhere in the
        workspace (duplicates are a workspace question, spec §6.5)."""
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[RecordView]:
            row = await records_service.type_row(s, state.workspace_id, type)
            if row is None:
                return []
            identity = records_service.identity_of(row.display, data)
            rows = await records_service.find_duplicates(
                s, state.workspace_id, type, identity, exclude=exclude
            )
            return [_view(r) for r in rows]

        return cast(
            list[RecordView],
            await state.run_step(key, "step", body, TypeAdapter(list[RecordView])),
        )

    async def find_similar(
        self,
        key: str,
        type: str,
        data: dict[str, Any],
        *,
        amount: Decimal | None = None,
        occurred_on: date | None = None,
        window_days: int = 30,
        exclude: uuid.UUID | None = None,
    ) -> list[Similar]:
        state = self._state

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[Similar]:
            row = await records_service.type_row(s, state.workspace_id, type)
            if row is None:
                return []
            identity = records_service.identity_of(row.display, data)
            found = await records_service.find_similar(
                s,
                state.workspace_id,
                type,
                identity,
                amount=amount,
                occurred_on=occurred_on,
                window_days=window_days,
                exclude=exclude,
            )
            return [Similar(record=_view(r), similarity=sim) for r, sim in found]

        return cast(
            list[Similar], await state.run_step(key, "step", body, TypeAdapter(list[Similar]))
        )

    async def load(self, record_ids: Sequence[uuid.UUID]) -> list[RecordView]:
        """S76-10: these records (the ones this job can see), read inside a pack step (e.g. to
        build a file from them in the same step)."""
        from momentum.domain.records.service import visible

        state = self._state
        if state.scope is None:
            raise PackError("job.records.load can only be called inside a step")
        s = state.scope.session
        rows = (
            await s.execute(
                select(Record).where(await visible(s, state.ctx), Record.id.in_(list(record_ids)))
            )
        ).scalars()
        return [_view(r) for r in rows]

    async def export(
        self, record_ids: Sequence[uuid.UUID], *, title: str, fmt: str = "xlsx"
    ) -> bytes:
        """S76-10: an export of these records (the ``records_export`` sheets: a Records sheet and
        one per list), as ``xlsx`` or ``csv`` bytes, e.g. a batch's catalogue to attach. Called
        inside a pack step (the bytes are never kept in a step); only records this job can
        see."""
        from momentum.domain.records.service import visible
        from momentum.reports.builders.records import add_records
        from momentum.reports.document import ReportDocument
        from momentum.reports.generate import render

        state = self._state
        if state.scope is None:
            raise PackError("job.records.export can only be called inside a step")
        s = state.scope.session
        rows = list(
            (
                await s.execute(
                    select(Record)
                    .where(await visible(s, state.ctx), Record.id.in_(list(record_ids)))
                    .order_by(Record.created_at)
                )
            ).scalars()
        )
        doc = ReportDocument(
            title=title,
            subtitle=f"{len(rows)} record{'s' if len(rows) != 1 else ''}",
            generated_at=datetime.now(UTC),
            generated_by=state.agent_name,
            scope_note="",
        )
        for t in sorted({r.type for r in rows}):
            row = await records_query.type_display(s, state.ctx, t)
            add_records(doc, row.label, row.display, [r for r in rows if r.type == t])
        return render(doc, "csv" if fmt == "csv" else "xlsx")

    async def query(self, key: str, q: dict[str, Any]) -> records_query.QueryResult:
        """A ``RecordQuery`` run as the job (its visibility)."""
        state = self._state
        parsed = records_query.RecordQuery.model_validate(q)

        async def body(s: AsyncSession, _meta: dict[str, Any]) -> records_query.QueryResult:
            return await records_query.run_query(s, state.ctx, parsed)

        return cast(
            records_query.QueryResult,
            await state.run_step(key, "step", body, TypeAdapter(records_query.QueryResult)),
        )
