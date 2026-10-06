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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.mutation import Mutation
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    forbid_agent,
    get_visible_project,
    get_visible_task,
    require_project_role,
)
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.files.models import FileParse

# ---------- owners and access ----------


async def _portfolio_role(session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID) -> str:
    """A portfolio's files (generated reports) are visible to whoever can see the portfolio
    (spec §3.2, §5.6): every member; its editors manage them. Guests see portfolios only through
    an explicit membership (S75-05), which ``get_portfolio`` checks."""
    from momentum.domain.portfolios.service import can_edit, get_portfolio

    portfolio = await get_portfolio(session, ctx, portfolio_id)
    if ctx.actor.is_agent:
        raise NotFound("Attachment not found")
    return "admin" if await can_edit(session, ctx, portfolio) else "viewer"


@dataclass(frozen=True)
class Owner:
    """Where a file lives, resolved for the caller: the task it hangs off (task or comment
    files), or the project/portfolio it was uploaded to, with the caller's role there."""

    role: str
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    portfolio_id: uuid.UUID | None = None

    @property
    def channels(self) -> list[str]:
        if self.task_id is not None:
            return [f"task:{self.task_id}"]
        if self.project_id is not None:
            return [f"project:{self.project_id}"]
        return [f"portfolio:{self.portfolio_id}"]

    @property
    def data(self) -> dict[str, str]:
        if self.task_id is not None:
            return {"task_id": str(self.task_id)}
        if self.project_id is not None:
            return {"project_id": str(self.project_id)}
        return {"portfolio_id": str(self.portfolio_id)}


async def _owner(
    session: AsyncSession,
    ctx: Ctx,
    *,
    task_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    portfolio_id: uuid.UUID | None = None,
    not_found: str = "Attachment not found",
) -> Owner:
    try:
        if task_id is not None:
            _, _, role = await get_visible_task(session, ctx, task_id)
            return Owner(role, task_id=task_id)
        if comment_id is not None:
            comment = await session.get(Comment, comment_id)
            if comment is None or comment.workspace_id != ctx.workspace_id:
                raise NotFound(not_found)
            _, _, role = await get_visible_task(session, ctx, comment.task_id)
            return Owner(role, task_id=comment.task_id)
        if project_id is not None:
            _, role = await get_visible_project(session, ctx, project_id)
            return Owner(role, project_id=project_id)
        assert portfolio_id is not None
        return Owner(await _portfolio_role(session, ctx, portfolio_id), portfolio_id=portfolio_id)
    except NotFound as e:
        raise NotFound(not_found) from e


async def _get_attachment(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Attachment, Owner]:
    """The attachment and where it lives, for the caller. 404s rather than 403s when the caller
    can't see it, so a direct-URL guess can't be used to probe existence."""
    att = await session.get(Attachment, attachment_id)
    if att is None or att.workspace_id != ctx.workspace_id:
        raise NotFound("Attachment not found")
    if att.deleted_at is not None and not include_deleted:
        raise NotFound("Attachment not found")
    return att, await _owner(
        session,
        ctx,
        task_id=att.task_id,
        comment_id=att.comment_id,
        project_id=att.project_id,
        portfolio_id=att.portfolio_id,
    )


def _upload_role(owner: Owner) -> str:
    """Commenters may attach to a task or comment (S2.6.1); a project's or portfolio's own files
    need edit rights (spec §3.2)."""
    return "commenter" if owner.task_id is not None else "editor"


async def _recompute_current(session: AsyncSession, group: uuid.UUID) -> None:
    """Exactly the newest live version of a group is current. Called after every add, delete and
    restore, so undo in any order leaves the group consistent."""
    rows = (
        (await session.execute(select(Attachment).where(Attachment.version_group == group)))
        .scalars()
        .all()
    )
    live = [r for r in rows if r.deleted_at is None]
    newest = max(live, key=lambda r: r.version).id if live else None
    for r in rows:
        r.is_current = r.id == newest


# ---------- create, version, list ----------


async def create_attachment(
    session: AsyncSession,
    ctx: Ctx,
    *,
    task_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    portfolio_id: uuid.UUID | None = None,
    storage_key: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    replace_id: uuid.UUID | None = None,
    source: str | None = None,
    generated_spec: dict[str, Any] | None = None,
) -> Mutation[Attachment]:
    """Attach a file to exactly one owner, or (``replace_id``) add the next version of an
    existing file in the same place: the new one becomes current, the old one stays
    downloadable from the versions list, and undo removes the new version again."""
    previous: Attachment | None = None
    if replace_id is not None:
        previous, owner = await _get_attachment(session, ctx, replace_id)
        task_id, comment_id = previous.task_id, previous.comment_id
        project_id, portfolio_id = previous.project_id, previous.portfolio_id
    else:
        owners = [task_id, comment_id, project_id, portfolio_id]
        assert sum(o is not None for o in owners) == 1, "exactly one owner"
        what = (
            "Task not found"
            if task_id
            else "Comment not found"
            if comment_id
            else "Project not found"
            if project_id
            else "Portfolio not found"
        )
        owner = await _owner(
            session,
            ctx,
            task_id=task_id,
            comment_id=comment_id,
            project_id=project_id,
            portfolio_id=portfolio_id,
            not_found=what,
        )
    require_project_role(
        owner.role,
        _upload_role(owner),
        "add a new version of this file" if previous else "attach a file here",
    )
    assert ctx.actor.id is not None
    att = Attachment(
        id=new_id(),
        workspace_id=ctx.workspace_id,
        task_id=task_id,
        comment_id=comment_id,
        project_id=project_id,
        portfolio_id=portfolio_id,
        storage_key=storage_key,
        filename=filename,
        mime=mime,
        size_bytes=size_bytes,
        sha256=sha256,
        extract_status="pending",
        uploaded_by=ctx.actor.id,
        source=source or ("agent" if ctx.actor.is_agent else "upload"),
        generated_spec=generated_spec,
    )
    if previous is not None:
        top = (
            await session.execute(
                select(func.max(Attachment.version)).where(
                    Attachment.version_group == previous.version_group
                )
            )
        ).scalar_one()
        att.version_group = previous.version_group
        att.version = int(top or 0) + 1
    else:
        att.version_group = att.id
    session.add(att)
    await session.flush()
    if previous is not None:
        await _recompute_current(session, att.version_group)
    verb = "attachment.version_added" if previous else "attachment.created"
    act = await record_activity(
        session,
        ctx,
        entity_type="attachment",
        entity_id=att.id,
        verb=verb,
        changes={
            next(iter(owner.data)): (None, next(iter(owner.data.values()))),
            **({"version": (previous.version, att.version)} if previous else {}),
        },
        undo=undo_op("attachments.delete", attachment_id=att.id),
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="attachment",
        entity_id=att.id,
        data={**owner.data, "version_group": str(att.version_group), "version": att.version},
        channels=owner.channels,
        activity_id=act.id,
    )
    return Mutation(att, act.id)


async def upload_project_file(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    storage_key: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    replace_id: uuid.UUID | None = None,
) -> Mutation[Attachment]:
    """D3: a file uploaded straight to a project (needs editor). With ``replace_id`` it becomes
    the next version of that file, which must be one of this project's own files."""
    if replace_id is not None:
        target, _ = await _get_attachment(session, ctx, replace_id)
        if target.project_id != project_id:
            raise ValidationFailed(
                "That file isn't one of this project's own files", code="wrong_place"
            )
    return await create_attachment(
        session,
        ctx,
        project_id=None if replace_id else project_id,
        storage_key=storage_key,
        filename=filename,
        mime=mime,
        size_bytes=size_bytes,
        sha256=sha256,
        replace_id=replace_id,
    )


def _live_current() -> list[ColumnElement[bool]]:
    return [Attachment.deleted_at.is_(None), Attachment.is_current.is_(True)]


async def list_for_task(session: AsyncSession, ctx: Ctx, task_id: uuid.UUID) -> list[Attachment]:
    await get_visible_task(session, ctx, task_id)
    rows = await session.execute(
        select(Attachment)
        .where(Attachment.task_id == task_id, *_live_current())
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
        .where(Attachment.comment_id == comment_id, *_live_current())
        .order_by(Attachment.created_at)
    )
    return list(rows.scalars())


async def list_versions(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID
) -> list[Attachment]:
    """Every live version of a file, newest first (visibility as the file itself)."""
    att, _ = await _get_attachment(session, ctx, attachment_id)
    rows = await session.execute(
        select(Attachment)
        .where(Attachment.version_group == att.version_group, Attachment.deleted_at.is_(None))
        .order_by(Attachment.version.desc())
    )
    return list(rows.scalars())


async def get_for_download(session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID) -> Attachment:
    """The AC-critical path: the owner's visibility check gates every download, even for
    someone who knows (or guesses) the attachment id directly."""
    att, _ = await _get_attachment(session, ctx, attachment_id)
    return att


async def get_visible_attachment(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID
) -> Attachment:
    """For readers outside this module (Mo's file tools, reports): the same gate as download."""
    att, _ = await _get_attachment(session, ctx, attachment_id)
    return att


def can_delete(ctx: Ctx, att: Attachment, role: str) -> bool:
    # Mirrors comments' own `can_delete`: the uploader or a project admin, not any editor — an
    # editor on a team-visible project would otherwise be able to remove someone else's upload.
    return att.uploaded_by == ctx.actor.id or role == "admin" or ctx.actor.is_admin


async def delete_attachment(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Attachment]:
    """Soft delete. Deleting the current version promotes the previous one."""
    forbid_agent(ctx, "remove attachments")
    att, owner = await _get_attachment(session, ctx, attachment_id)
    if not can_delete(ctx, att, owner.role):
        raise Forbidden("Only the uploader or a project admin can remove an attachment")
    att.deleted_at = datetime.now(UTC)
    # the parse cache holds the file's content: it goes with the file (re-parsed after an undo)
    await session.execute(sa_delete(FileParse).where(FileParse.attachment_id == att.id))
    await session.flush()
    await _recompute_current(session, att.version_group)
    key, value = next(iter(owner.data.items()))
    act = await record_activity(
        session,
        ctx,
        entity_type="attachment",
        entity_id=att.id,
        verb="attachment.deleted",
        changes={key: (value, None)},
        undo=undo_op("attachments.restore", attachment_id=att.id) if record_undo else None,
    )
    await emit(
        session,
        ctx,
        type="attachment.deleted",
        entity_type="attachment",
        entity_id=att.id,
        data={**owner.data, "version_group": str(att.version_group)},
        channels=owner.channels,
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


async def record_text_extract(
    session: AsyncSession, attachment_id: uuid.UUID, text: str | None
) -> None:
    """Store extracted text for an attachment whose bytes are already at hand (S5.1.5: a file an
    agent attached), instead of waiting for the extraction job."""
    att = await session.get(Attachment, attachment_id)
    if att is None:
        return
    att.text_extract = text
    att.extract_status = "done" if text is not None else "skipped"


def _aid(args: dict[str, object]) -> uuid.UUID:
    return uuid.UUID(str(args["attachment_id"]))


@undo_handler("attachments.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, object]) -> None:
    await delete_attachment(session, ctx, _aid(args), record_undo=False)


@undo_handler("attachments.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, object]) -> None:
    att, owner = await _get_attachment(session, ctx, _aid(args), include_deleted=True)
    if not can_delete(ctx, att, owner.role):
        raise Forbidden("Only the uploader or a project admin can restore an attachment")
    if att.deleted_at is None:
        raise UndoConflict("This attachment isn't deleted")
    att.deleted_at = None
    await session.flush()
    await _recompute_current(session, att.version_group)
    await emit(
        session,
        ctx,
        type="attachment.restored",
        entity_type="attachment",
        entity_id=att.id,
        data={**owner.data, "version_group": str(att.version_group)},
        channels=owner.channels,
    )
