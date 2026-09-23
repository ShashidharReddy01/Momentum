from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.core.ids import task_key
from momentum.domain.access import visible_projects_clause
from momentum.domain.comments import service
from momentum.domain.comments.models import Comment
from momentum.domain.comments.schemas import (
    CommentIn,
    CommentOut,
    MentionProject,
    MentionSearchOut,
    MentionTask,
    MentionUser,
    ReactionIn,
    ReactionOut,
)
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

router = APIRouter(tags=["comments"])


async def _out(s: AsyncSession, ctx: Ctx, comments: list[Comment], role: str) -> list[CommentOut]:
    reactions = await service.reactions_for(s, [c.id for c in comments])
    return [
        CommentOut(
            id=c.id,
            task_id=c.task_id,
            author_id=c.author_id,
            body=c.body,
            is_ai=c.is_ai,
            created_at=c.created_at,
            edited_at=c.edited_at,
            reactions=[ReactionOut(emoji=e, user_ids=u) for e, u in reactions.get(c.id, [])],
            can_edit=service.can_edit(ctx, c),
            can_delete=service.can_delete(ctx, c, role),
        )
        for c in comments
    ]


async def _one(s: AsyncSession, ctx: Ctx, comment_id: uuid.UUID) -> CommentOut:
    comment, _, role = await service._get_comment(s, ctx, comment_id)
    await s.flush()
    await s.refresh(comment)
    return (await _out(s, ctx, [comment], role))[0]


@router.get("/tasks/{task_id}/comments", response_model=ListOut[CommentOut], summary="Comments")
async def list_comments(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[CommentOut]:
    async with uow.transaction() as s:
        comments, role = await service.list_comments(s, ctx, task_id)
        return ListOut(data=await _out(s, ctx, comments, role))


@router.post(
    "/tasks/{task_id}/comments",
    response_model=MutationOut[CommentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a task",
)
async def create_comment(
    task_id: uuid.UUID, body: CommentIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[CommentOut]:
    async with uow.transaction() as s:
        m = await service.create_comment(s, ctx, task_id, body.body)
        return MutationOut(
            data=await _one(s, ctx, m.entity.id), meta=MutationMeta(activity_id=m.activity_id)
        )


@router.patch(
    "/comments/{comment_id}", response_model=MutationOut[CommentOut], summary="Edit a comment"
)
async def edit_comment(
    comment_id: uuid.UUID, body: CommentIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[CommentOut]:
    async with uow.transaction() as s:
        m = await service.edit_comment(s, ctx, comment_id, body.body)
        return MutationOut(
            data=await _one(s, ctx, comment_id), meta=MutationMeta(activity_id=m.activity_id)
        )


@router.delete(
    "/comments/{comment_id}", response_model=MutationOut[OkOut], summary="Delete a comment"
)
async def delete_comment(comment_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_comment(s, ctx, comment_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.post(
    "/comments/{comment_id}/reactions",
    response_model=MutationOut[CommentOut],
    summary="Add or remove a reaction",
)
async def react(
    comment_id: uuid.UUID, body: ReactionIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[CommentOut]:
    async with uow.transaction() as s:
        await service.set_reaction(s, ctx, comment_id, body.emoji, body.active)
        return MutationOut(data=await _one(s, ctx, comment_id), meta=MutationMeta())


@router.get(
    "/mentions/search",
    response_model=MentionSearchOut,
    summary="People, tasks, projects to @mention",
)
async def mention_search(
    ctx: CtxDep, uow: UowDep, q: str = Query(default="", max_length=100)
) -> MentionSearchOut:
    """Only what the caller can see; a few of each kind."""
    like = f"%{q.strip()}%"
    async with uow.transaction() as s:
        users = (
            await s.execute(
                select(User)
                .where(
                    User.workspace_id == ctx.workspace_id,
                    User.status != "disabled",
                    (User.name.ilike(like)) | (User.email.ilike(like)),
                )
                .order_by(func.lower(User.name))
                .limit(6)
            )
        ).scalars()
        projects = (
            await s.execute(
                select(Project)
                .where(visible_projects_clause(ctx), Project.name.ilike(like))
                .order_by(func.lower(Project.name))
                .limit(4)
            )
        ).scalars()
        tasks = (
            await s.execute(
                select(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .join(Project, Project.id == TaskProject.project_id)
                .where(
                    visible_projects_clause(ctx),
                    Task.deleted_at.is_(None),
                    Task.title.ilike(like),
                )
                .order_by(Task.completed_at.is_not(None), func.lower(Task.title))
                .limit(5)
            )
        ).scalars()
        return MentionSearchOut(
            users=[MentionUser(id=u.id, name=u.name, email=u.email) for u in users],
            tasks=[MentionTask(id=t.id, title=t.title, key=task_key(t.number)) for t in tasks],
            projects=[MentionProject(id=p.id, name=p.name, color=p.color) for p in projects],
        )
