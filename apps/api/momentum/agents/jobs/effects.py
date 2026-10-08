"""Phase 7.6 S76-02 (spec §8.1): ``job.effects.*``, the only writes a pack makes directly.

Each helper checks two rules before it touches anything:
- it runs **inside a step** (so the write commits with exactly one step row and can't be applied
  twice by a replay);
- the pack's manifest **declares** the effect (``PackError("echo may not tasks.rename")``
  otherwise: a developer error, caught in tests).

Writes go through the ordinary services as the agent, in the context the job acts in (``acting_for``
the person who asked, when one did), under the job's ``request_id``, so they record activity with
undo and "Undo everything <agent> did" can reverse them. The service guards stay absolute: no
deletes, no completing others' tasks, no deciding approvals. Anything else goes through a proposal
(preview → confirm → apply), not an effect.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.packs.pack import PackError
from momentum.ai.tools.write_tools import text_doc
from momentum.core.errors import ValidationFailed
from momentum.domain.access import get_visible_task
from momentum.domain.comments.service import create_comment
from momentum.domain.fields import service as fields_service
from momentum.domain.sections.models import Section
from momentum.domain.tasks import service as tasks_service

if TYPE_CHECKING:
    from momentum.agents.jobs.job import JobState

REVIEW_SECTIONS = ("review", "in review")


def _session(state: JobState, effect: str, type_key: str | None = None) -> AsyncSession:
    if state.scope is None:
        raise PackError(f"job.effects.{effect} can only be called inside a step")
    if not state.pack.manifest.declares(effect, type_key):
        raise PackError(f"{state.pack.key} may not {effect}")
    return state.scope.session


class _Comments:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def create(self, task_id: uuid.UUID, text: str) -> uuid.UUID:
        """Comment on a task as the agent (plain text, shown with the agent's ✦ mark)."""
        s = _session(self._state, "comments.create")
        m = await create_comment(s, self._state.ctx, task_id, text_doc(text))
        return m.entity.id


class _Tasks:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def create_subtask(
        self, parent_id: uuid.UUID, title: str, *, assign_to_self: bool = True
    ) -> uuid.UUID:
        state = self._state
        s = _session(state, "tasks.create_subtask")
        m = await tasks_service.create_subtask(s, state.ctx, parent_id, title)
        if assign_to_self:
            await tasks_service.update_task(
                s, state.ctx, m.entity.id, {"assignee_id": state.agent_user_id}
            )
        return m.entity.id

    async def rename(self, task_id: uuid.UUID, title: str) -> None:
        s = _session(self._state, "tasks.rename")
        await tasks_service.update_task(s, self._state.ctx, task_id, {"title": title})

    async def set_fields(self, task_id: uuid.UUID, values: dict[str, Any]) -> None:
        """Set task fields by name (``{"Vendor": "Acme", "Status": "Checked"}``). Select fields
        take option labels (or ids); a name the task's project doesn't have is an error."""
        state = self._state
        s = _session(state, "tasks.set_fields")
        task, placement, _role = await get_visible_task(s, state.ctx, task_id)
        if placement is None:
            raise ValidationFailed("This task isn't in a project, so it has no fields")
        fields = {
            f.name.casefold(): f
            for _pf, f in await fields_service.list_project_fields(
                s, state.ctx, placement.project_id
            )
        }
        for name, value in values.items():
            field = fields.get(name.casefold())
            if field is None:
                raise ValidationFailed(f"The project has no field {name!r}")
            await fields_service.set_task_field_value(
                s, state.ctx, task.id, field.id, _option_ids(field.type, field.options, value)
            )

    async def move_to_review(self, task_id: uuid.UUID) -> None:
        """Move a task to its project's Review (or In review) section."""
        state = self._state
        s = _session(state, "tasks.move_to_review")
        task, placement, _role = await get_visible_task(s, state.ctx, task_id)
        if placement is None:
            raise ValidationFailed("This task isn't in a project")
        review = await s.scalar(
            select(Section)
            .where(
                Section.project_id == placement.project_id,
                Section.deleted_at.is_(None),
                func.lower(func.trim(Section.name)).in_(REVIEW_SECTIONS),
            )
            .order_by(Section.position)
            .limit(1)
        )
        if review is None:
            raise ValidationFailed("The project has no Review section")
        if placement.section_id != review.id:
            await tasks_service.move_tasks(s, state.ctx, [task.id], section_id=review.id)

    async def complete_own(self, task_id: uuid.UUID) -> None:
        """Complete a task the agent made and is assigned (its own subtask), never anyone
        else's."""
        state = self._state
        s = _session(state, "tasks.complete_own")
        task, _placement, _role = await get_visible_task(s, state.ctx, task_id)
        if task.assignee_id != state.agent_user_id or task.created_by != state.agent_user_id:
            raise PackError(
                f"{state.agent_name} can complete only its own subtasks, assigned to itself"
            )
        await tasks_service.set_completed(s, state.ctx, task.id, True)


class _Attachments:
    def __init__(self, state: JobState) -> None:
        self._state = state

    async def create(
        self, task_id: uuid.UUID, filename: str, data: bytes, mime: str = "text/plain"
    ) -> uuid.UUID:
        from momentum.agents.extensions import attach_file

        state = self._state
        s = _session(state, "attachments.create")
        return await attach_file(s, state.ctx, state.settings, task_id, filename, data, mime)


def _option_ids(kind: str, options: Any, value: Any) -> Any:
    if kind not in ("single_select", "multi_select") or value is None:
        return value
    by_label = {str(o.get("label", "")).casefold(): o["id"] for o in options or []}

    def one(v: Any) -> Any:
        return by_label.get(str(v).casefold(), v)

    return [one(v) for v in value] if kind == "multi_select" else one(value)


class Effects:
    """``job.effects``: comments, tasks and attachments (records, entities and skills join in
    S76-04/05)."""

    def __init__(self, state: JobState) -> None:
        self.comments = _Comments(state)
        self.tasks = _Tasks(state)
        self.attachments = _Attachments(state)
