"""SQL visibility for AI retrieval and context (ai-architecture §5).

Built only from ``domain/access.py``'s existing ``visible_projects_clause`` (that module's rules
need human approval to change). A task is visible when it is placed in a visible project, or is
a (sub-)subtask of one: the recursive walk covers subtasks at any depth, which Phase 2's bulk
endpoints (top-level only) didn't need. Tasks visible to someone only personally (assignee /
follower without project access) are not included: the same disclosed gap as every bulk listing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from momentum.core.context import Ctx
from momentum.domain.access import visible_projects_clause
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject


def visible_project_ids(ctx: Ctx) -> Select[tuple[uuid.UUID]]:
    return select(Project.id).where(visible_projects_clause(ctx), Project.is_template.is_(False))


def visible_task_ids(ctx: Ctx) -> Select[tuple[uuid.UUID]]:
    """Ids of live tasks the caller can see through a project, subtasks included."""
    top = (
        select(Task.id)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .where(
            Task.workspace_id == ctx.workspace_id,
            Task.deleted_at.is_(None),
            TaskProject.project_id.in_(visible_project_ids(ctx)),
        )
        .cte(
            f"visible_tasks_{uuid.uuid4().hex[:8]}", recursive=True
        )  # unique: one query may hold several
    )
    child = aliased(Task)
    tree = top.union(
        select(child.id).where(child.parent_id == top.c.id, child.deleted_at.is_(None))
    )
    return select(tree.c.id)


def visible_entity_clause(ctx: Ctx, entity_type: Any, entity_id: Any) -> ColumnElement[bool]:
    """``(entity_type, entity_id)`` pairs the caller may retrieve: tasks, comments and
    attachments on visible tasks, and visible projects. Deleted content never matches."""
    tasks = visible_task_ids(ctx)
    return or_(
        and_(entity_type == "task", entity_id.in_(tasks)),
        and_(
            entity_type == "comment",
            entity_id.in_(
                select(Comment.id).where(Comment.task_id.in_(tasks), Comment.deleted_at.is_(None))
            ),
        ),
        and_(
            entity_type == "attachment",
            entity_id.in_(
                select(Attachment.id).where(
                    Attachment.task_id.in_(tasks), Attachment.deleted_at.is_(None)
                )
            ),
        ),
        and_(entity_type == "project", entity_id.in_(visible_project_ids(ctx))),
    )
