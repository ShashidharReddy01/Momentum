"""S2.6.1: attachments on tasks and comments.

Uploading is the FastAPI/router layer's job (it owns the `UploadFile` stream, the size-limit
enforcement while streaming, the sha256/MIME sniffing — see `domain/attachments/router.py`); this
module only ever receives already-resolved primitives (filename, mime, size, sha256, a storage
key the bytes are already saved under) and turns them into a row, an activity, and an undo
entry — the same split fields/tags already use between "how a value gets computed" and "what a
mutation records".

Text extraction (`text_extract`/`extract_status`) is a separate background job
(`jobs/attachments.py`), not done inline here — extracting text from a PDF or docx is slow enough
that doing it synchronously in the upload request would make every upload feel sluggish. The pure
byte-parsing logic lives in `extract_text_from_bytes` below so it's unit-testable without any job
or storage machinery; the job just wires it to the storage backend and the DB row.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_task, require_project_role
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment


async def _get_attachment(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Attachment, uuid.UUID, str]:
    """Returns (attachment, owning task id, caller's role on that task) — 404s rather than 403s
    when the caller can't see it, so a direct-URL guess can't be used to probe existence."""
    att = await session.get(Attachment, attachment_id)
    if att is None or att.workspace_id != ctx.workspace_id:
        raise NotFound("Attachment not found")
    if att.deleted_at is not None and not include_deleted:
        raise NotFound("Attachment not found")
    if att.task_id is not None:
        task_id = att.task_id
    else:
        assert att.comment_id is not None
        comment = await session.get(Comment, att.comment_id)
        if comment is None:
            raise NotFound("Attachment not found")
        task_id = comment.task_id
    task, _, role = await get_visible_task(session, ctx, task_id)
    return att, task.id, role


async def create_attachment(
    session: AsyncSession,
    ctx: Ctx,
    *,
    task_id: uuid.UUID | None,
    comment_id: uuid.UUID | None,
    storage_key: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
) -> Mutation[Attachment]:
    assert (task_id is None) != (comment_id is None), "exactly one of task_id/comment_id"
    if task_id is not None:
        _, _, role = await get_visible_task(session, ctx, task_id)
        owning_task_id = task_id
    else:
        assert comment_id is not None
        comment = await session.get(Comment, comment_id)
        if comment is None or comment.workspace_id != ctx.workspace_id:
            raise NotFound("Comment not found")
        _, _, role = await get_visible_task(session, ctx, comment.task_id)
        owning_task_id = comment.task_id
    require_project_role(role, "commenter", "attach a file to this task")
    assert ctx.actor.id is not None
    att = Attachment(
        workspace_id=ctx.workspace_id,
        task_id=task_id,
        comment_id=comment_id,
        storage_key=storage_key,
        filename=filename,
        mime=mime,
        size_bytes=size_bytes,
        sha256=sha256,
        extract_status="pending",
        uploaded_by=ctx.actor.id,
    )
    session.add(att)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="attachment",
        entity_id=att.id,
        verb="attachment.created",
        changes={"task_id": (None, owning_task_id)},
        undo=undo_op("attachments.delete", attachment_id=att.id),
    )
    await emit(
        session,
        ctx,
        type="attachment.created",
        entity_type="attachment",
        entity_id=att.id,
        data={"task_id": str(owning_task_id)},
        channels=[f"task:{owning_task_id}"],
        activity_id=act.id,
    )
    return Mutation(att, act.id)


async def list_for_task(session: AsyncSession, ctx: Ctx, task_id: uuid.UUID) -> list[Attachment]:
    await get_visible_task(session, ctx, task_id)
    rows = await session.execute(
        select(Attachment)
        .where(Attachment.task_id == task_id, Attachment.deleted_at.is_(None))
        .order_by(Attachment.created_at)
    )
    return list(rows.scalars())


async def list_for_comment(
    session: AsyncSession, ctx: Ctx, comment_id: uuid.UUID
) -> list[Attachment]:
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.workspace_id != ctx.workspace_id:
        raise NotFound("Comment not found")
    await get_visible_task(session, ctx, comment.task_id)
    rows = await session.execute(
        select(Attachment)
        .where(Attachment.comment_id == comment_id, Attachment.deleted_at.is_(None))
        .order_by(Attachment.created_at)
    )
    return list(rows.scalars())


async def get_for_download(session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID) -> Attachment:
    """The AC-critical path: a task's/comment's visibility check gates every download, even for
    someone who knows (or guesses) the attachment id directly."""
    att, _, _ = await _get_attachment(session, ctx, attachment_id)
    return att


def can_delete(ctx: Ctx, att: Attachment, role: str) -> bool:
    # Mirrors comments' own `can_delete`: the uploader or a project admin, not any editor — an
    # editor on a team-visible project would otherwise be able to remove someone else's upload.
    return att.uploaded_by == ctx.actor.id or role == "admin" or ctx.actor.is_admin


async def delete_attachment(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Attachment]:
    att, task_id, role = await _get_attachment(session, ctx, attachment_id)
    if not can_delete(ctx, att, role):
        raise Forbidden("Only the uploader or a project admin can remove an attachment")
    att.deleted_at = datetime.now(UTC)
    act = await record_activity(
        session,
        ctx,
        entity_type="attachment",
        entity_id=att.id,
        verb="attachment.deleted",
        changes={"task_id": (task_id, None)},
        undo=undo_op("attachments.restore", attachment_id=att.id) if record_undo else None,
    )
    await emit(
        session,
        ctx,
        type="attachment.deleted",
        entity_type="attachment",
        entity_id=att.id,
        data={"task_id": str(task_id)},
        channels=[f"task:{task_id}"],
        activity_id=act.id,
    )
    return Mutation(att, act.id)


def extract_text_from_bytes(data: bytes, mime: str) -> str | None:
    """Pure: bytes + declared MIME in, extracted plain text out (or None when the type isn't
    supported for extraction — `pending` becomes `skipped`, not `failed`, for those)."""
    if mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        return text or None
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document

        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        return text or None
    if mime.startswith("text/"):
        return data.decode("utf-8", errors="replace").strip() or None
    return None


# ---------- undo ----------


def _aid(args: dict[str, object]) -> uuid.UUID:
    return uuid.UUID(str(args["attachment_id"]))


@undo_handler("attachments.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, object]) -> None:
    await delete_attachment(session, ctx, _aid(args), record_undo=False)


@undo_handler("attachments.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, object]) -> None:
    att, task_id, role = await _get_attachment(session, ctx, _aid(args), include_deleted=True)
    if not can_delete(ctx, att, role):
        raise Forbidden("Only the uploader or a project admin can restore an attachment")
    if att.deleted_at is None:
        raise UndoConflict("This attachment isn't deleted")
    att.deleted_at = None
    await emit(
        session,
        ctx,
        type="attachment.restored",
        entity_type="attachment",
        entity_id=att.id,
        data={"task_id": str(task_id)},
        channels=[f"task:{task_id}"],
    )
