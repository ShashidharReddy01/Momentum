"""Phase 7.5 (spec §3.2): a project's file inventory.

Every current, live file the caller can see in a project, listed once: the project's own files,
files on every task and subtask placed in it (any depth, hidden under a deleted ancestor) and
files on those tasks' live comments. Filtering, sorting and paging are all SQL; a file's kind is
computed in SQL from the same table as ``files/kinds.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import ColumnElement, String, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.files.kinds import FILE_KINDS, FileKind, extensions_of

Where = Literal["project", "tasks", "comments", "all"]
Sort = Literal["newest", "name", "size"]
PAGE = 50


class FileLocation(BaseModel):
    type: Literal["project", "task", "comment", "portfolio"]
    task_id: uuid.UUID | None = None
    task_key: str | None = None
    task_title: str | None = None
    comment_id: uuid.UUID | None = None


class ProjectFileOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime: str
    kind: FileKind
    size_bytes: int
    uploaded_by: uuid.UUID
    uploaded_by_name: str
    created_at: datetime
    version: int
    versions_count: int
    version_group: uuid.UUID
    source: str
    ai_drafted: bool
    location: FileLocation


class ProjectFilesPage(BaseModel):
    data: list[ProjectFileOut]
    next_cursor: str | None
    total: int


def kind_expr() -> ColumnElement[str]:
    """``files.kinds.kind_of`` in SQL: the extension first, then the MIME type."""
    ext = func.lower(func.substring(Attachment.filename, r"\.([^.]+)$"))
    by_ext = [(ext.in_(extensions_of(k)), literal(k)) for k in FILE_KINDS if k != "other"]
    by_mime = [
        (Attachment.mime.like("application/pdf%"), literal("pdf")),
        (Attachment.mime.like("image/%"), literal("image")),
        (Attachment.mime.like("%wordprocessingml%"), literal("document")),
        (Attachment.mime.like("application/msword%"), literal("document")),
        (Attachment.mime.like("%spreadsheetml%"), literal("spreadsheet")),
        (Attachment.mime.like("application/vnd.ms-excel%"), literal("spreadsheet")),
        (Attachment.mime.like("text/csv%"), literal("spreadsheet")),
        (Attachment.mime.like("%presentationml%"), literal("presentation")),
        (Attachment.mime.like("message/rfc822%"), literal("email")),
        (Attachment.mime.like("application/zip%"), literal("archive")),
        (Attachment.mime.like("text/%"), literal("text")),
    ]
    return cast(case(*by_ext, *by_mime, else_=literal("other")), String)


def project_tasks_cte(project_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Live tasks of a project at any depth: top-level tasks placed in it, then their subtasks
    (a deleted task hides everything under it)."""
    roots = (
        select(Task.id)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .where(
            TaskProject.project_id == project_id,
            Task.parent_id.is_(None),
            Task.deleted_at.is_(None),
        )
        .cte("project_tasks", recursive=True)
    )
    child = aliased(Task)
    return roots.union_all(
        select(child.id).where(child.parent_id == roots.c.id, child.deleted_at.is_(None))
    )


async def list_project_files(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    q: str | None = None,
    kind: FileKind | None = None,
    source: str | None = None,
    uploaded_by: uuid.UUID | None = None,
    where: Where = "all",
    sort: Sort = "newest",
    cursor: str | None = None,
    limit: int = PAGE,
) -> ProjectFilesPage:
    await get_visible_project(session, ctx, project_id)
    tree = project_tasks_cte(project_id)
    live_comments = select(Comment.id).where(
        Comment.task_id.in_(select(tree.c.id)), Comment.deleted_at.is_(None)
    )
    places: list[ColumnElement[bool]] = []
    if where in ("project", "all"):
        places.append(Attachment.project_id == project_id)
    if where in ("tasks", "all"):
        places.append(Attachment.task_id.in_(select(tree.c.id)))
    if where in ("comments", "all"):
        places.append(Attachment.comment_id.in_(live_comments))
    kind_col = kind_expr().label("kind")
    conds: list[ColumnElement[bool]] = [
        Attachment.workspace_id == ctx.workspace_id,
        Attachment.deleted_at.is_(None),
        Attachment.is_current.is_(True),
        or_(*places),
    ]
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        conds.append(or_(Attachment.filename.ilike(like), Attachment.text_extract.ilike(like)))
    if kind is not None:
        conds.append(kind_expr() == kind)
    if source is not None:
        conds.append(Attachment.source == source)
    if uploaded_by is not None:
        conds.append(Attachment.uploaded_by == uploaded_by)

    other = aliased(Attachment)
    versions = (
        select(func.count(other.id))
        .where(other.version_group == Attachment.version_group, other.deleted_at.is_(None))
        .scalar_subquery()
    )
    comment = aliased(Comment)
    owning_task = aliased(Task)
    orders: dict[str, list[Any]] = {
        "newest": [Attachment.created_at.desc(), Attachment.id.desc()],
        "name": [func.lower(Attachment.filename), Attachment.id],
        "size": [Attachment.size_bytes.desc(), Attachment.id],
    }
    order = orders[sort]
    try:
        offset = int(cursor) if cursor else 0
    except ValueError as e:
        raise ValidationFailed("Bad cursor", code="bad_cursor") from e
    offset = max(offset, 0)
    total = (
        await session.execute(select(func.count()).select_from(Attachment).where(*conds))
    ).scalar_one()
    rows = (
        await session.execute(
            select(Attachment, kind_col, versions.label("n"), User.name, owning_task, comment.id)
            .join(User, User.id == Attachment.uploaded_by)
            .outerjoin(comment, comment.id == Attachment.comment_id)
            .outerjoin(
                owning_task, owning_task.id == func.coalesce(Attachment.task_id, comment.task_id)
            )
            .where(*conds)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    out: list[ProjectFileOut] = []
    for att, k, n, uploader, task, comment_id in rows:
        if att.project_id is not None:
            loc = FileLocation(type="project")
        else:
            loc = FileLocation(
                type="comment" if comment_id is not None else "task",
                task_id=task.id if task else None,
                task_key=task_key(task.number) if task else None,
                task_title=task.title if task else None,
                comment_id=comment_id,
            )
        out.append(
            ProjectFileOut(
                id=att.id,
                filename=att.filename,
                mime=att.mime,
                kind=k,
                size_bytes=att.size_bytes,
                uploaded_by=att.uploaded_by,
                uploaded_by_name=uploader,
                created_at=att.created_at,
                version=att.version,
                versions_count=int(n),
                version_group=att.version_group,
                source=att.source,
                ai_drafted=bool((att.generated_spec or {}).get("ai_drafted")),
                location=loc,
            )
        )
    nxt = offset + len(rows)
    return ProjectFilesPage(data=out, next_cursor=str(nxt) if nxt < total else None, total=total)
