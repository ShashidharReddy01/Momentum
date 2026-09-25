"""S2.6.1: attachment upload/download/list/delete.

Uploads and downloads are the one place in the API that talks to `UploadFile`/streamed bytes
directly rather than a Pydantic body, so the streaming (size-limit enforcement while reading,
sha256, MIME sniffing) lives here rather than in `domain/attachments/service.py` — see that
module's own docstring for why.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import filetype
from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import Response

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.errors import ValidationFailed
from momentum.core.ids import new_id
from momentum.core.storage import StorageBackend, build_storage
from momentum.domain.attachments import service
from momentum.domain.attachments.schemas import AttachmentOut

router = APIRouter(tags=["attachments"])

CHUNK_SIZE = 1024 * 1024
SNIFF_BYTES = 8192
# Previewed inline (image viewer / PDF viewer in the browser); everything else downloads.
INLINE_MIME_PREFIXES = ("image/",)
INLINE_MIMES = ("application/pdf",)


async def _stream_upload(
    file: UploadFile, *, storage: StorageBackend, max_upload_mb: int, key: str
) -> tuple[int, str, str]:
    max_bytes = max_upload_mb * 1024 * 1024
    size = 0
    sha = hashlib.sha256()
    sniff_buf = bytearray()

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal size
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValidationFailed(
                    f"File exceeds the {max_upload_mb} MB limit", code="file_too_large"
                )
            sha.update(chunk)
            if len(sniff_buf) < SNIFF_BYTES:
                sniff_buf.extend(chunk[: SNIFF_BYTES - len(sniff_buf)])
            yield chunk

    try:
        await storage.save_stream(key, chunks())
    except Exception:
        await storage.delete(key)
        raise
    if size == 0:
        await storage.delete(key)
        raise ValidationFailed("The file is empty", code="empty_file")
    kind = filetype.guess(bytes(sniff_buf))
    mime = kind.mime if kind is not None else (file.content_type or "application/octet-stream")
    return size, sha.hexdigest(), mime


@router.post(
    "/tasks/{task_id}/attachments",
    response_model=MutationOut[AttachmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to a task",
)
async def upload_task_attachment(
    task_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    file: UploadFile = File(...),
) -> MutationOut[AttachmentOut]:
    key = f"{ctx.workspace_id}/{new_id()}"
    size, sha256, mime = await _stream_upload(
        file,
        storage=build_storage(runtime.settings),
        max_upload_mb=runtime.settings.max_upload_mb,
        key=key,
    )
    async with uow.transaction() as s:
        m = await service.create_attachment(
            s,
            ctx,
            task_id=task_id,
            comment_id=None,
            storage_key=key,
            filename=file.filename or "file",
            mime=mime,
            size_bytes=size,
            sha256=sha256,
        )
        att_id = m.entity.id
    await _enqueue_extract(runtime, att_id)
    return MutationOut.of(m, AttachmentOut)


@router.post(
    "/comments/{comment_id}/attachments",
    response_model=MutationOut[AttachmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to a comment",
)
async def upload_comment_attachment(
    comment_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    file: UploadFile = File(...),
) -> MutationOut[AttachmentOut]:
    key = f"{ctx.workspace_id}/{new_id()}"
    size, sha256, mime = await _stream_upload(
        file,
        storage=build_storage(runtime.settings),
        max_upload_mb=runtime.settings.max_upload_mb,
        key=key,
    )
    async with uow.transaction() as s:
        m = await service.create_attachment(
            s,
            ctx,
            task_id=None,
            comment_id=comment_id,
            storage_key=key,
            filename=file.filename or "file",
            mime=mime,
            size_bytes=size,
            sha256=sha256,
        )
        att_id = m.entity.id
    await _enqueue_extract(runtime, att_id)
    return MutationOut.of(m, AttachmentOut)


async def _enqueue_extract(runtime: RuntimeDep, attachment_id: uuid.UUID) -> None:
    job_app = runtime.extras.get("job_app")
    if job_app is None:
        return  # no worker configured (e.g. tests, worker_mode="off") — stays "pending"
    await job_app.tasks["momentum.extract_text"].defer_async(attachment_id=str(attachment_id))


@router.get(
    "/tasks/{task_id}/attachments", response_model=ListOut[AttachmentOut], summary="A task's files"
)
async def list_task_attachments(
    task_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[AttachmentOut]:
    async with uow.transaction() as s:
        rows = await service.list_for_task(s, ctx, task_id)
        return ListOut(data=[AttachmentOut.model_validate(r) for r in rows])


@router.get(
    "/comments/{comment_id}/attachments",
    response_model=ListOut[AttachmentOut],
    summary="A comment's files",
)
async def list_comment_attachments(
    comment_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[AttachmentOut]:
    async with uow.transaction() as s:
        rows = await service.list_for_comment(s, ctx, comment_id)
        return ListOut(data=[AttachmentOut.model_validate(r) for r in rows])


@router.get(
    "/attachments/{attachment_id}/download",
    summary="Download a file (task/comment visibility gated)",
)
async def download_attachment(
    attachment_id: uuid.UUID, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> Response:
    async with uow.transaction() as s:
        att = await service.get_for_download(s, ctx, attachment_id)
        filename, mime, key = att.filename, att.mime, att.storage_key
    storage = build_storage(runtime.settings)
    data = await storage.read(key)
    inline = mime.startswith(INLINE_MIME_PREFIXES) or mime in INLINE_MIMES
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.delete(
    "/attachments/{attachment_id}",
    response_model=MutationOut[OkOut],
    summary="Remove an attachment",
)
async def delete_attachment(
    attachment_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_attachment(s, ctx, attachment_id)
        return MutationOut(data=OkOut(ok=True), meta=MutationMeta(activity_id=m.activity_id))
