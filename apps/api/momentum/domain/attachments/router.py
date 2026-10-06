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
from typing import Annotated
from urllib.parse import quote

import filetype
from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.errors import ValidationFailed
from momentum.core.ids import new_id
from momentum.core.storage import StorageBackend, build_storage
from momentum.domain.attachments import inventory, service
from momentum.domain.attachments.schemas import AttachmentOut
from momentum.files.kinds import FileKind

router = APIRouter(tags=["attachments"])

CHUNK_SIZE = 1024 * 1024
SNIFF_BYTES = 8192
# Previewed inline (image viewer / PDF viewer in the browser); everything else downloads.
# shown in the browser rather than downloaded: only formats that can't carry script (an SVG or an
# HTML file served from our own origin could, so they always download), and only when the type was
# recognised from the bytes, not taken from the uploader (S7.5.2)
INLINE_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "application/pdf"}
)
# a download can't run anything here even if a browser tried to render it
DOWNLOAD_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"


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
    replace_id: Annotated[uuid.UUID | None, Form()] = None,
) -> MutationOut[AttachmentOut]:
    """With ``replace_id``, the upload becomes the next version of that file (Phase 7.5)."""
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
            task_id=None if replace_id else task_id,
            replace_id=await _same_place(s, ctx, replace_id, task_id=task_id),
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
    replace_id: Annotated[uuid.UUID | None, Form()] = None,
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
            comment_id=None if replace_id else comment_id,
            replace_id=await _same_place(s, ctx, replace_id, comment_id=comment_id),
            storage_key=key,
            filename=file.filename or "file",
            mime=mime,
            size_bytes=size,
            sha256=sha256,
        )
        att_id = m.entity.id
    await _enqueue_extract(runtime, att_id)
    return MutationOut.of(m, AttachmentOut)


async def _same_place(
    session: AsyncSession,
    ctx: CtxDep,
    replace_id: uuid.UUID | None,
    *,
    task_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """A new version goes where the old one is: the file being replaced must belong to the task
    or comment the upload names."""
    if replace_id is None:
        return None
    target = await service.get_visible_attachment(session, ctx, replace_id)
    if (task_id is not None and target.task_id != task_id) or (
        comment_id is not None and target.comment_id != comment_id
    ):
        raise ValidationFailed("That file isn't attached here", code="wrong_place")
    return replace_id


@router.post(
    "/projects/{project_id}/files",
    response_model=MutationOut[AttachmentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file to a project (or a new version of one of its files)",
)
async def upload_project_file(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    file: UploadFile = File(...),
    replace_id: Annotated[uuid.UUID | None, Form()] = None,
) -> MutationOut[AttachmentOut]:
    key = f"{ctx.workspace_id}/{new_id()}"
    size, sha256, mime = await _stream_upload(
        file,
        storage=build_storage(runtime.settings),
        max_upload_mb=runtime.settings.max_upload_mb,
        key=key,
    )
    async with uow.transaction() as s:
        m = await service.upload_project_file(
            s,
            ctx,
            project_id,
            storage_key=key,
            filename=file.filename or "file",
            mime=mime,
            size_bytes=size,
            sha256=sha256,
            replace_id=replace_id,
        )
        att_id = m.entity.id
    await _enqueue_extract(runtime, att_id)
    return MutationOut.of(m, AttachmentOut)


@router.get(
    "/projects/{project_id}/files",
    response_model=inventory.ProjectFilesPage,
    summary="Every file in a project the caller can see (project, tasks, comments)",
)
async def list_project_files(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    kind: FileKind | None = None,
    source: Annotated[str | None, Query(pattern="^(upload|generated|agent|import)$")] = None,
    uploaded_by: uuid.UUID | None = None,
    where: inventory.Where = "all",
    sort: inventory.Sort = "newest",
    cursor: Annotated[str | None, Query(max_length=20)] = None,
) -> inventory.ProjectFilesPage:
    async with uow.transaction() as s:
        return await inventory.list_project_files(
            s,
            ctx,
            project_id,
            q=q,
            kind=kind,
            source=source,
            uploaded_by=uploaded_by,
            where=where,
            sort=sort,
            cursor=cursor,
        )


@router.get(
    "/attachments/{attachment_id}/versions",
    response_model=ListOut[AttachmentOut],
    summary="Every version of a file, newest first",
)
async def list_versions(
    attachment_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[AttachmentOut]:
    async with uow.transaction() as s:
        rows = await service.list_versions(s, ctx, attachment_id)
        return ListOut(data=[AttachmentOut.model_validate(r) for r in rows])


async def _enqueue_extract(runtime: RuntimeDep, attachment_id: uuid.UUID) -> None:
    job_app = runtime.extras.get("job_app")
    if job_app is None:
        return  # no worker configured (e.g. tests, worker_mode="off") — stays "pending"
    # Procrastinate 3 names blueprint tasks "<namespace>:<name>" (H64: the old "momentum." key
    # raised KeyError, so every upload to a server with a worker failed with a 500)
    task = job_app.tasks.get("momentum:extract_text") or job_app.tasks["momentum.extract_text"]
    await task.defer_async(attachment_id=str(attachment_id))


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
    sniffed = filetype.guess(data[:SNIFF_BYTES])
    inline = sniffed is not None and sniffed.mime == mime and mime in INLINE_MIMES
    return Response(
        content=data,
        media_type=mime,  # "attachment" + nosniff + the sandbox: saved, never rendered
        headers={
            "Content-Disposition": content_disposition(
                "inline" if inline else "attachment", filename
            ),
            "Content-Security-Policy": DOWNLOAD_CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


def content_disposition(kind: str, filename: str) -> str:
    """A safe header for any file name: an ASCII fallback (no quotes, backslashes or control
    characters) plus the exact name UTF-8 encoded (RFC 6266 / 5987)."""
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename)
    encoded = quote(filename, safe="")
    return f"{kind}; filename=\"{ascii_name or 'file'}\"; filename*=UTF-8''{encoded}"


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
