"""Phase 7.6 S76-04 (spec §6.6-§6.7): the records API. Visibility everywhere is the record's task's
(or project's); guests never see financial or personal records; corrections go through
operations with ``expected_version``."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import anyio
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListMeta, ListOut
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.storage import build_storage
from momentum.domain.attachments.models import Attachment
from momentum.domain.records import query as records_query
from momentum.domain.records import service
from momentum.domain.records.models import Record, RecordVersion
from momentum.domain.records.schemas import (
    RecordDetailOut,
    RecordOut,
    RecordPatchIn,
    RecordTypeImpl,
    RecordVersionOut,
)

router = APIRouter(tags=["records"])
MAX_PAGE = 2000


def record_impl(runtime: Any, key: str, version: int) -> RecordTypeImpl:
    """The record type's code (from the loaded packs); edits need it to validate."""
    registry = getattr(runtime, "packs", None)
    impl = registry.record_type(key, version) if registry is not None else None
    if impl is None:
        raise Conflict(
            f"The {key} record type isn't available on this server, so its records can't be"
            " changed here",
            code="record_type_unavailable",
        )
    return impl  # type: ignore[no-any-return]


async def _out(s: Any, ctx: Any, r: Record) -> RecordOut:
    row = await service.type_row(s, r.workspace_id, r.type, r.type_version)
    return RecordOut(
        id=r.id,
        type=r.type,
        type_version=r.type_version,
        type_label=row.label if row else r.type,
        classification=row.classification if row else "internal",
        project_id=r.project_id,
        task_id=r.task_id,
        source_attachment_id=r.source_attachment_id,
        source_locator=r.source_locator,
        run_id=r.run_id,
        status=r.status,
        title=r.title,
        data=r.data,
        provenance=r.provenance,
        checks=r.checks,
        decision=r.decision,
        confidence=r.confidence,
        amount=r.amount,
        currency=r.currency,
        occurred_on=r.occurred_on,
        entity_ids=list(r.entity_ids or []),
        version=r.version,
        created_via=r.created_via,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@router.get(
    "/records",
    response_model=ListOut[RecordOut],
    summary="Records you can see (by type, project, task, status, entity, text, date range)",
)
async def list_records(
    ctx: CtxDep,
    uow: UowDep,
    type: str | None = Query(default=None, max_length=60),
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    status: list[str] = Query(default_factory=list),
    entity_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=12, description="An offset"),
) -> ListOut[RecordOut]:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    async with uow.transaction() as s:
        rows, total = await service.list_records(
            s,
            ctx,
            type=type,
            project_id=project_id,
            task_id=task_id,
            status=status or None,
            entity_id=entity_id,
            q=q,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        more = offset + len(rows) < total
        return ListOut(
            data=[await _out(s, ctx, r) for r in rows],
            meta=ListMeta(next_cursor=str(offset + len(rows)) if more else None),
        )


@router.post(
    "/records/query",
    response_model=records_query.QueryResult,
    summary="Count, sum, average, min or max over records you can see (per currency for money)",
)
async def query_records(
    body: records_query.RecordQuery, ctx: CtxDep, uow: UowDep
) -> records_query.QueryResult:
    async with uow.transaction() as s:
        return await records_query.run_query(s, ctx, body)


@router.get(
    "/records/{record_id}",
    response_model=RecordDetailOut,
    summary="One record with its versions, provenance, checks, decision and duplicates",
)
async def get_record(record_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RecordDetailOut:
    async with uow.transaction() as s:
        r = await service.get_record(s, ctx, record_id)
        versions = (
            await s.execute(
                select(RecordVersion)
                .where(RecordVersion.record_id == r.id)
                .order_by(RecordVersion.version.desc())
                .limit(50)
            )
        ).scalars()
        dupes = []
        for d in await service.find_duplicates(
            s, r.workspace_id, r.type, r.identity_key, exclude=r.id
        ):
            try:
                await service.get_record(s, ctx, d.id)
            except NotFound:
                continue
            dupes.append(d.id)
        base = await _out(s, ctx, r)
        return RecordDetailOut(
            **base.model_dump(),
            versions=[
                RecordVersionOut(
                    version=v.version,
                    status=v.status,
                    changed_by=v.changed_by,
                    via=v.via,
                    change=v.change,
                    reason=v.reason,
                    created_at=v.created_at,
                )
                for v in versions
            ],
            duplicates=dupes,
        )


@router.patch(
    "/records/{record_id}",
    response_model=RecordOut,
    summary="Correct a record with operations (set, add_item, remove_item, move_item, distribute,"
    " set_status, link_entity); a stale expected_version is a 409",
)
async def patch_record(
    record_id: uuid.UUID, body: RecordPatchIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> RecordOut:
    async with uow.transaction() as s:
        current = await service.get_record(s, ctx, record_id)
        impl = record_impl(runtime, current.type, current.type_version)
        r = await service.update_record(
            s,
            ctx,
            impl,
            record_id,
            list(body.ops),
            expected_version=body.expected_version,
            reason=body.reason,
        )
        return await _out(s, ctx, r)


@router.get(
    "/records/{record_id}/pages/{page}",
    response_class=Response,
    summary="A page of the record's source file as an image (rendered once, then cached)",
)
async def record_page(
    record_id: uuid.UUID, page: int, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> Response:
    if not 1 <= page <= MAX_PAGE:
        raise ValidationFailed("No such page")
    async with uow.transaction() as s:
        r = await service.get_record(s, ctx, record_id)
        if r.source_attachment_id is None:
            raise NotFound("This record has no source file")
        att = await s.get(Attachment, r.source_attachment_id)
        if att is None or att.deleted_at is not None:
            raise NotFound("The source file is gone")
        storage_key, mime, workspace = att.storage_key, att.mime, r.workspace_id
    storage = build_storage(runtime.settings)
    cache_key = f"{workspace}/record-pages/{att.id}/{page}.jpg"
    try:
        jpeg = await storage.read(cache_key)
    except FileNotFoundError:
        data = await storage.read(storage_key)
        jpeg = await anyio.to_thread.run_sync(_render, data, mime, page)

        async def chunks() -> Any:
            yield jpeg

        await storage.save_stream(cache_key, chunks())
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


def _render(data: bytes, mime: str, page: int) -> bytes:
    from momentum.files.render import pdf_page_count, render_image, render_pdf_page

    if mime == "application/pdf":
        if page > pdf_page_count(data):
            raise NotFound("No such page")
        return render_pdf_page(data, page).jpeg
    if mime.startswith("image/") and page == 1:
        return render_image(data).jpeg
    raise NotFound("No page images for this kind of file")
