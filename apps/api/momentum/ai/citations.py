"""Citations in Mo's answers (S3.3.1): ``[T-123]`` for tasks, ``[P:Project name]`` for projects.

The model is told to cite what it mentions, but its output is never trusted: every reference is
resolved here **as the asking user**. Only a task or project that exists and that the user can
see becomes a link (``valid``); anything else stays plain text in the UI, flagged as unverified.
So a hallucinated key, or a key of something private, never turns into a working link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.domain.access import get_visible_task, visible_projects_clause
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task

CITE = re.compile(r"\[(T-(\d{1,9}))\]|\[P:([^\]\n]{1,200})\]")
MAX_CITATIONS = 40


@dataclass(frozen=True)
class Citation:
    ref: str  # exactly as written: "[T-12]" or "[P:Website Revamp]"
    type: str  # "task" | "project"
    valid: bool
    id: str | None = None
    key: str | None = None
    title: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "type": self.type,
            "valid": self.valid,
            "id": self.id,
            "key": self.key,
            "title": self.title,
        }


def find_refs(text: str) -> list[str]:
    """Distinct references in order of first appearance."""
    seen: dict[str, None] = {}
    for m in CITE.finditer(text):
        seen.setdefault(m.group(0), None)
    return list(seen)[:MAX_CITATIONS]


async def resolve(session: AsyncSession, ctx: Ctx, text: str) -> list[Citation]:
    out: list[Citation] = []
    for ref in find_refs(text):
        m = CITE.fullmatch(ref)
        assert m is not None
        if m.group(1):
            out.append(await _task(session, ctx, ref, m.group(1), int(m.group(2))))
        else:
            out.append(await _project(session, ctx, ref, m.group(3).strip()))
    return out


async def _task(session: AsyncSession, ctx: Ctx, ref: str, key: str, number: int) -> Citation:
    task_id = (
        await session.execute(
            select(Task.id).where(Task.workspace_id == ctx.workspace_id, Task.number == number)
        )
    ).scalar_one_or_none()
    if task_id is not None:
        try:
            task, _, _ = await get_visible_task(session, ctx, task_id)
            return Citation(ref, "task", True, str(task.id), key, task.title)
        except NotFound:
            pass
    return Citation(ref, "task", False, key=key)


async def _project(session: AsyncSession, ctx: Ctx, ref: str, name: str) -> Citation:
    project = (
        (
            await session.execute(
                select(Project)
                .where(
                    Project.workspace_id == ctx.workspace_id,
                    Project.deleted_at.is_(None),
                    func.lower(Project.name) == name.lower(),
                    visible_projects_clause(ctx),
                )
                .order_by(Project.created_at)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if project is None:
        return Citation(ref, "project", False, title=name)
    return Citation(ref, "project", True, str(project.id), title=project.name)
