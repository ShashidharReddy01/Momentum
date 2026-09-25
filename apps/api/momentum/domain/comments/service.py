"""Comments with mentions and reactions (phase-1.md S1.4.1)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.richtext import doc_hash, plain_text, preview, sanitize_doc
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    get_visible_task,
    require_project_role,
)
from momentum.domain.comments.models import Comment, Mention, Reaction
from momentum.domain.notifications.service import notify
from momentum.domain.tasks.models import Follower, Task
from momentum.domain.users.models import User

REACTIONS = ("👍", "❤️", "🎉", "😄", "👀", "🙏", "✅", "🚀")
MAX_MENTIONS = 50


def extract_mentions(doc: dict[str, Any] | None) -> list[tuple[str, uuid.UUID]]:
    """(kind, id) of every mention node, first occurrence order, invalid ids ignored."""
    found: list[tuple[str, uuid.UUID]] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "mention":
            attrs = node.get("attrs") or {}
            kind = attrs.get("kind") or "user"
            try:
                target = uuid.UUID(str(attrs.get("id")))
            except ValueError:
                target = None
            if (
                target is not None
                and kind in ("user", "task", "project")
                and (kind, target) not in found
            ):
                found.append((kind, target))
        for child in node.get("content") or []:
            walk(child)

    if doc:
        walk(doc)
    return found[:MAX_MENTIONS]


async def _valid_mentions(
    session: AsyncSession, ctx: Ctx, mentions: list[tuple[str, uuid.UUID]]
) -> list[tuple[str, uuid.UUID]]:
    """Keep mentions of active workspace members and of tasks/projects the author can see.
    (Mentioning something doesn't reveal it: invisible targets are dropped silently.)"""
    valid: list[tuple[str, uuid.UUID]] = []
    for kind, target in mentions:
        try:
            if kind == "user":
                user = await session.get(User, target)
                if (
                    user is None
                    or user.workspace_id != ctx.workspace_id
                    or user.status == "disabled"
                ):
                    continue
            elif kind == "task":
                await get_visible_task(session, ctx, target)
            else:
                await get_visible_project(session, ctx, target)
        except NotFound:
            continue
        valid.append((kind, target))
    return valid


async def _sync_mentions(
    session: AsyncSession, ctx: Ctx, comment: Comment, targets: list[tuple[str, uuid.UUID]]
) -> list[uuid.UUID]:
    """Replace the comment's mention rows; mentioned people follow the task. Returns people who
    are newly mentioned (for notifications)."""
    before = {
        (m.target_type, m.target_id)
        for m in (
            await session.execute(
                select(Mention).where(
                    Mention.source_type == "comment", Mention.source_id == comment.id
                )
            )
        ).scalars()
    }
    await session.execute(
        delete(Mention).where(Mention.source_type == "comment", Mention.source_id == comment.id)
    )
    for kind, target in targets:
        session.add(
            Mention(
                workspace_id=ctx.workspace_id,
                source_type="comment",
                source_id=comment.id,
                target_type=kind,
                target_id=target,
            )
        )
    new_people = [t for k, t in targets if k == "user" and ("user", t) not in before]
    for user_id in new_people:
        if await session.get(Follower, (comment.task_id, user_id)) is None:
            session.add(Follower(task_id=comment.task_id, user_id=user_id))
    await session.flush()
    return new_people


def _clean_body(body: object) -> dict[str, Any]:
    doc = sanitize_doc(body)
    if doc is None:
        raise ValidationFailed("Write something first", code="empty_comment")
    return doc


async def _get_comment(
    session: AsyncSession, ctx: Ctx, comment_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Comment, Task, str]:
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.workspace_id != ctx.workspace_id:
        raise NotFound("Comment not found")
    if comment.deleted_at is not None and not include_deleted:
        raise NotFound("Comment not found")
    task, _, role = await get_visible_task(session, ctx, comment.task_id)
    return comment, task, role


def can_edit(ctx: Ctx, comment: Comment) -> bool:
    return comment.author_id is not None and comment.author_id == ctx.actor.id


def can_delete(ctx: Ctx, comment: Comment, role: str) -> bool:
    return can_edit(ctx, comment) or role == "admin" or ctx.actor.is_admin


async def reactions_for(
    session: AsyncSession, comment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[str, list[uuid.UUID]]]]:
    """emoji → user ids per comment, in first-reaction order (one query)."""
    if not comment_ids:
        return {}
    rows = await session.execute(
        select(Reaction)
        .where(Reaction.entity_type == "comment", Reaction.entity_id.in_(comment_ids))
        .order_by(Reaction.created_at, Reaction.id)
    )
    grouped: dict[uuid.UUID, dict[str, list[uuid.UUID]]] = defaultdict(dict)
    for r in rows.scalars():
        grouped[r.entity_id].setdefault(r.emoji, []).append(r.user_id)
    return {cid: list(by_emoji.items()) for cid, by_emoji in grouped.items()}


async def list_comments(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> tuple[list[Comment], str]:
    _, _, role = await get_visible_task(session, ctx, task_id)
    rows = await session.execute(
        select(Comment)
        .where(Comment.task_id == task_id, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at, Comment.id)
    )
    return list(rows.scalars()), role


async def create_comment(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, body: object
) -> Mutation[Comment]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "commenter", "comment on this task")
    doc = _clean_body(body)
    comment = Comment(
        workspace_id=ctx.workspace_id,
        task_id=task.id,
        author_id=ctx.actor.id,
        body=doc,
        body_text=plain_text(doc),
        is_ai=ctx.via == "ai",
        created_via=ctx.via,
    )
    session.add(comment)
    await session.flush()
    mentioned = await _sync_mentions(
        session, ctx, comment, await _valid_mentions(session, ctx, extract_mentions(doc))
    )
    if ctx.actor.id is not None and await session.get(Follower, (task.id, ctx.actor.id)) is None:
        session.add(Follower(task_id=task.id, user_id=ctx.actor.id))  # commenting follows the task
    act = await record_activity(
        session,
        ctx,
        entity_type="comment",
        entity_id=comment.id,
        verb="comment.created",
        changes={"task_id": (None, task.id), "body": (None, preview(doc))},
        undo=undo_op("comments.delete", comment_id=comment.id),
    )
    channels = [f"task:{task.id}", *(f"user:{u}" for u in mentioned)]
    if placement is not None:
        channels.append(f"project:{placement.project_id}")
    await emit(
        session,
        ctx,
        type="comment.created",
        entity_type="comment",
        entity_id=comment.id,
        data={"task_id": str(task.id), "mentioned_user_ids": [str(u) for u in mentioned]},
        channels=channels,
        activity_id=act.id,
    )
    snippet = preview(doc)
    for user_id in mentioned:
        await notify(
            session,
            ctx,
            user_id=user_id,
            kind="mentioned",
            entity_type="task",
            entity_id=task.id,
            title=f'You were mentioned in "{task.title}"',
            snippet=snippet,
            activity_id=act.id,
        )
    followers = (
        (await session.execute(select(Follower.user_id).where(Follower.task_id == task.id)))
        .scalars()
        .all()
    )
    # a mentioned follower already got the more specific notification above
    for user_id in set(followers) - set(mentioned):
        await notify(
            session,
            ctx,
            user_id=user_id,
            kind="commented",
            entity_type="task",
            entity_id=task.id,
            title=f'New comment on "{task.title}"',
            snippet=snippet,
            activity_id=act.id,
        )
    await session.flush()
    return Mutation(comment, act.id)


async def edit_comment(
    session: AsyncSession,
    ctx: Ctx,
    comment_id: uuid.UUID,
    body: object,
    *,
    record_undo: bool = True,
) -> Mutation[Comment]:
    comment, task, _ = await _get_comment(session, ctx, comment_id)
    if not can_edit(ctx, comment):
        raise Forbidden("Only the author can edit a comment")
    doc = _clean_body(body)
    if doc == comment.body:
        return Mutation(comment)
    old = comment.body
    comment.body = doc
    comment.body_text = plain_text(doc)
    comment.edited_at = datetime.now(UTC)
    mentioned = await _sync_mentions(
        session, ctx, comment, await _valid_mentions(session, ctx, extract_mentions(doc))
    )
    act = await record_activity(
        session,
        ctx,
        entity_type="comment",
        entity_id=comment.id,
        verb="comment.edited",
        changes={"body": (preview(old), preview(doc))},
        undo=undo_op("comments.edit", comment_id=comment.id, body=old, expect=doc_hash(doc))
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="comment.edited",
        entity_type="comment",
        entity_id=comment.id,
        data={"task_id": str(task.id), "mentioned_user_ids": [str(u) for u in mentioned]},
        channels=[f"task:{task.id}", *(f"user:{u}" for u in mentioned)],
        activity_id=act.id,
    )
    return Mutation(comment, act.id)


async def delete_comment(
    session: AsyncSession, ctx: Ctx, comment_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Comment]:
    comment, task, role = await _get_comment(session, ctx, comment_id)
    if not can_delete(ctx, comment, role):
        raise Forbidden("Only the author or a project admin can delete a comment")
    comment.deleted_at = datetime.now(UTC)
    act = await record_activity(
        session,
        ctx,
        entity_type="comment",
        entity_id=comment.id,
        verb="comment.deleted",
        changes={"task_id": (task.id, None)},
        undo=undo_op("comments.restore", comment_id=comment.id) if record_undo else None,
    )
    await emit(
        session,
        ctx,
        type="comment.deleted",
        entity_type="comment",
        entity_id=comment.id,
        data={"task_id": str(task.id)},
        channels=[f"task:{task.id}"],
        activity_id=act.id,
    )
    return Mutation(comment, act.id)


async def set_reaction(
    session: AsyncSession, ctx: Ctx, comment_id: uuid.UUID, emoji: str, active: bool
) -> Mutation[Comment]:
    comment, task, role = await _get_comment(session, ctx, comment_id)
    require_project_role(role, "commenter", "react to comments")
    if emoji not in REACTIONS:
        raise ValidationFailed("Unsupported reaction", code="invalid_reaction")
    assert ctx.actor.id is not None
    existing = (
        await session.execute(
            select(Reaction).where(
                Reaction.entity_type == "comment",
                Reaction.entity_id == comment.id,
                Reaction.user_id == ctx.actor.id,
                Reaction.emoji == emoji,
            )
        )
    ).scalar_one_or_none()
    if (existing is not None) == active:
        return Mutation(comment)
    if active:
        session.add(
            Reaction(
                workspace_id=ctx.workspace_id,
                entity_type="comment",
                entity_id=comment.id,
                user_id=ctx.actor.id,
                emoji=emoji,
            )
        )
    else:
        await session.delete(existing)
    await session.flush()
    await emit(
        session,
        ctx,
        type="reaction.added" if active else "reaction.removed",
        entity_type="comment",
        entity_id=comment.id,
        data={"task_id": str(task.id), "emoji": emoji},
        channels=[f"task:{task.id}"],
    )
    return Mutation(comment)


# ---------- undo ----------


def _cid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["comment_id"]))


@undo_handler("comments.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await delete_comment(session, ctx, _cid(args), record_undo=False)


@undo_handler("comments.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    comment, task, role = await _get_comment(session, ctx, _cid(args), include_deleted=True)
    if not can_delete(ctx, comment, role):
        raise Forbidden("Only the author or a project admin can restore a comment")
    if comment.deleted_at is None:
        raise UndoConflict("This comment isn't deleted")
    comment.deleted_at = None
    await emit(
        session,
        ctx,
        type="comment.restored",
        entity_type="comment",
        entity_id=comment.id,
        data={"task_id": str(task.id)},
        channels=[f"task:{task.id}"],
    )


@undo_handler("comments.edit")
async def _undo_edit(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    comment, _, _ = await _get_comment(session, ctx, _cid(args))
    if doc_hash(comment.body) != args.get("expect"):
        raise UndoConflict("This comment was edited again since")
    await edit_comment(session, ctx, comment.id, args["body"], record_undo=False)


# ---------- feed (S1.4.2) ----------

FEED_LIMIT = 300
# Activity that isn't worth a line in the feed (comments show as themselves; reorders are noise).
HIDDEN_VERBS = {"comment.created", "comment.edited", "comment.deleted"}
CHILD_VERBS = {"task.created", "task.completed", "task.uncompleted", "task.deleted"}


async def task_feed(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> tuple[list[Activity], list[Comment], dict[uuid.UUID, Task], str, bool]:
    """Activity of a task (and key events of its direct subtasks) plus its comments, oldest first.
    Undone changes are left out; pure reorders within a section too."""
    _, _, role = await get_visible_task(session, ctx, task_id)
    children = {
        t.id: t
        for t in (await session.execute(select(Task).where(Task.parent_id == task_id))).scalars()
    }
    query = (
        select(Activity)
        .where(
            Activity.entity_type == "task",
            Activity.undone_at.is_(None),
            (Activity.entity_id == task_id)
            | (Activity.entity_id.in_(list(children)) & Activity.verb.in_(CHILD_VERBS)),
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(FEED_LIMIT + 1)
    )
    rows = list((await session.execute(query)).scalars())
    truncated = len(rows) > FEED_LIMIT
    rows = [
        a
        for a in rows[:FEED_LIMIT]
        if a.verb not in HIDDEN_VERBS
        and not (a.verb == "task.moved" and set(a.diff) <= {"position", "parent_position"})
    ]
    rows.reverse()
    comments, _ = await list_comments(session, ctx, task_id)
    return rows, comments, children, role, truncated
