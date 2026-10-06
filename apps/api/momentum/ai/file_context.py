"""Phase 7.5 (spec §4.4, §4.7, §4.8): what Mo's file tools know about the conversation, and how
a file reference becomes a file the person can see.

A ``FileSession`` rides along a tool loop (chat, ⌘K, evals): the files the person put in the
conversation (chips from "Ask Mo about this file" and the paperclip), the task or project on
screen, and the images ``look_at`` rendered for the next model call, with the per-call and
per-conversation caps. Nothing here parses a file: that happens in the tools, through
``momentum.files.cache``, and only when Mo calls one (D1).
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import ConversationFile
from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.domain.access import visible_projects_clause
from momentum.domain.attachments import service as attachments
from momentum.domain.attachments.inventory import kind_expr, project_tasks_cte
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import TaskProject
from momentum.files.cache import FileSource
from momentum.files.kinds import kind_of
from momentum.files.render import Rendered

MAX_CANDIDATES = 8


@dataclass(frozen=True)
class FileHandle:
    """A file the actor may read: an attachment (any owner) or a conversation file."""

    id: uuid.UUID
    filename: str
    mime: str
    size: int
    storage_key: str
    workspace_id: uuid.UUID
    where: str  # "project", "task T-12", "comment on T-12", "this conversation", "portfolio"
    conversation_file: bool = False

    @property
    def kind(self) -> str:
        return kind_of(self.mime, self.filename)

    def source(self) -> FileSource:
        return FileSource(
            workspace_id=self.workspace_id,
            storage_key=self.storage_key,
            filename=self.filename,
            mime=self.mime,
            size=self.size,
            attachment_id=None if self.conversation_file else self.id,
            conversation_file_id=self.id if self.conversation_file else None,
        )

    def brief(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "name": self.filename,
            "kind": self.kind,
            "size": self.size,
            "where": self.where,
        }


@dataclass
class FileSession:
    """Per tool loop. ``pending`` holds images for the next model call (``loop.py`` sends them
    after the tool results); ``sent`` counts every image sent in this conversation so far."""

    conversation_id: uuid.UUID | None = None
    attachment_ids: list[uuid.UUID] = field(default_factory=list)  # chips: files asked about
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    pending: list[tuple[str, Rendered]] = field(default_factory=list)  # (file name, image)
    sent: int = 0
    images_this_call: int = 0

    def take_images(self) -> list[tuple[str, Rendered]]:
        out, self.pending = self.pending, []
        self.sent += len(out)
        return out


def image_part(r: Rendered) -> dict[str, object]:
    url = "data:image/jpeg;base64," + base64.b64encode(r.jpeg).decode()
    return {"type": "image_url", "image_url": {"url": url}}


def _handle(att: Attachment, where: str) -> FileHandle:
    return FileHandle(
        id=att.id,
        filename=att.filename,
        mime=att.mime,
        size=att.size_bytes,
        storage_key=att.storage_key,
        workspace_id=att.workspace_id,
        where=where,
    )


def _conv_handle(cf: ConversationFile) -> FileHandle:
    return FileHandle(
        id=cf.id,
        filename=cf.filename,
        mime=cf.mime,
        size=cf.size_bytes,
        storage_key=cf.storage_key,
        workspace_id=cf.workspace_id,
        where="this conversation",
        conversation_file=True,
    )


async def attachment_handle(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID
) -> FileHandle:
    """An attachment the actor can see (the download gate), else NotFound."""
    att = await attachments.get_visible_attachment(session, ctx, attachment_id)
    return _handle(att, await _where(session, att))


async def _where(session: AsyncSession, att: Attachment) -> str:
    from momentum.core.ids import task_key
    from momentum.domain.tasks.models import Task

    if att.project_id is not None:
        return "project"
    if att.portfolio_id is not None:
        return "portfolio"
    task_id = att.task_id
    prefix = "task"
    if task_id is None and att.comment_id is not None:
        comment = await session.get(Comment, att.comment_id)
        task_id = comment.task_id if comment else None
        prefix = "comment on"
    task = await session.get(Task, task_id) if task_id else None
    return f"{prefix} {task_key(task.number)}" if task else prefix


async def conversation_files(
    session: AsyncSession, ctx: Ctx, conversation_id: uuid.UUID | None
) -> list[FileHandle]:
    if conversation_id is None or ctx.actor.id is None:
        return []
    rows = (
        await session.execute(
            select(ConversationFile)
            .where(
                ConversationFile.conversation_id == conversation_id,
                ConversationFile.user_id == ctx.actor.id,
            )
            .order_by(ConversationFile.created_at)
        )
    ).scalars()
    return [_conv_handle(r) for r in rows]


async def handle_by_id(
    session: AsyncSession, ctx: Ctx, files: FileSession | None, file_id: uuid.UUID
) -> FileHandle:
    for h in await conversation_files(session, ctx, files.conversation_id if files else None):
        if h.id == file_id:
            return h
    return await attachment_handle(session, ctx, file_id)


async def chat_files(
    session: AsyncSession, ctx: Ctx, files: FileSession | None
) -> list[FileHandle]:
    """The files the person put in front of Mo: chips, then the conversation's own uploads.
    A chip the person can no longer see is skipped."""
    if files is None:
        return []
    out: list[FileHandle] = []
    for aid in files.attachment_ids:
        try:
            out.append(await attachment_handle(session, ctx, aid))
        except NotFound:
            continue
    out += await conversation_files(session, ctx, files.conversation_id)
    return out


async def visible_files(
    session: AsyncSession,
    ctx: Ctx,
    *,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    q: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[FileHandle]:
    """Current files the actor can see: in a project (any depth), on a task (and its comments),
    or anywhere visible (project files, tasks placed in visible projects and their comments)."""
    owning_task = func.coalesce(Attachment.task_id, Comment.task_id)
    conds = [
        Attachment.workspace_id == ctx.workspace_id,
        Attachment.deleted_at.is_(None),
        Attachment.is_current.is_(True),
        Attachment.portfolio_id.is_(None),
        or_(Comment.id.is_(None), Comment.deleted_at.is_(None)),
    ]
    if task_id is not None:
        conds.append(owning_task == task_id)
    elif project_id is not None:
        tree = project_tasks_cte(project_id)
        conds.append(or_(Attachment.project_id == project_id, owning_task.in_(select(tree.c.id))))
    visible = select(Project.id).where(visible_projects_clause(ctx))
    conds.append(
        or_(
            Attachment.project_id.in_(visible),
            owning_task.in_(select(TaskProject.task_id).where(TaskProject.project_id.in_(visible))),
        )
    )
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(Attachment.filename.ilike(f"%{escaped}%"))
    if kind:
        conds.append(kind_expr() == kind)
    rows = (
        (
            await session.execute(
                select(Attachment)
                .outerjoin(Comment, Comment.id == Attachment.comment_id)
                .where(*conds)
                .order_by(Attachment.created_at.desc(), Attachment.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    out: list[FileHandle] = []
    for att in rows:
        if task_id is not None or project_id is not None:
            # the rows above already passed the project filter; the task gate is the download
            # rule (a subtask's file is visible through its top-level task)
            try:
                out.append(await attachment_handle(session, ctx, att.id))
            except NotFound:
                continue
        else:
            out.append(_handle(att, await _where(session, att)))
    return out
