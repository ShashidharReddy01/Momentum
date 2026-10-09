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

from pydantic import BaseModel
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
    """``job.effects``: comments, tasks, attachments, records, entities and skills."""

    def __init__(self, state: JobState) -> None:
        self.comments = _Comments(state)
        self.tasks = _Tasks(state)
        self.attachments = _Attachments(state)
        self.records = _Records(state)
        self.entities = _Entities(state)
        self.skills = _Skills(state)


class _Records:
    """``job.effects.records``: create and update records of the types the pack declares
    (``records.create: [invoice]``), as the agent, validated on every write."""

    def __init__(self, state: JobState) -> None:
        self._state = state

    async def _project(self, s: AsyncSession, task_id: uuid.UUID | None) -> uuid.UUID:
        state = self._state
        if task_id is not None:
            _task, placement, _role = await get_visible_task(s, state.ctx, task_id)
            if placement is not None:
                return placement.project_id
        if state.project_id is not None:
            return state.project_id
        raise ValidationFailed("A record lives in a project; this job has none")

    async def create(
        self,
        type: str,
        data: dict[str, Any] | Any,
        *,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        provenance: dict[str, Any] | None = None,
        checks: list[dict[str, Any]] | None = None,
        decision: dict[str, Any] | None = None,
        confidence: float | None = None,
        status: str = "draft",
        source_attachment_id: uuid.UUID | None = None,
        source_sha256: str | None = None,
        source_locator: str | None = None,
    ) -> uuid.UUID:
        from momentum.domain.records.service import create_record

        state = self._state
        s = _session(state, "records.create", type)
        impl = state.pack.record_type(type)
        task = task_id or state.task_id
        record = await create_record(
            s,
            state.ctx,
            impl,
            project_id=project_id or await self._project(s, task),
            task_id=task,
            data=data.model_dump(mode="json") if hasattr(data, "model_dump") else data,
            provenance=provenance,
            checks=checks,
            decision=decision,
            confidence=confidence,
            status=status,
            source_attachment_id=source_attachment_id,
            source_sha256=source_sha256,
            source_locator=source_locator,
            run_id=state.run_id,
        )
        return record.id

    async def update(
        self,
        record_id: uuid.UUID,
        ops: list[dict[str, Any]],
        *,
        expected_version: int,
        reason: str | None = None,
        checks: list[dict[str, Any]] | None = None,
        decision: dict[str, Any] | None = None,
        confidence: float | None = None,
    ) -> int:
        """Apply correction operations (and/or new checks, decision, confidence); returns the
        new version."""
        from pydantic import TypeAdapter

        from momentum.domain.records.models import Record
        from momentum.domain.records.schemas import Op
        from momentum.domain.records.service import update_record

        state = self._state
        if state.scope is None:
            raise PackError("job.effects.records.update can only be called inside a step")
        current = await state.scope.session.get(Record, record_id)
        if current is None:
            raise ValidationFailed("No such record")
        s = _session(state, "records.update", current.type)
        impl = state.pack.record_type(current.type, current.type_version)
        record = await update_record(
            s,
            state.ctx,
            impl,
            record_id,
            TypeAdapter(list[Op]).validate_python(ops),
            expected_version=expected_version,
            reason=reason,
            checks=checks,
            decision=decision,
            confidence=confidence,
        )
        return record.version


class BankSeen(BaseModel):
    changed: bool  # a different account than the one on file
    last4: str


class SkillProposal(BaseModel):
    id: uuid.UUID
    status: str  # proposed, or rejected when the scrubber refused it
    note: str | None = None


class _Entities:
    """``job.effects.entities``: vendors and other entities of the types the pack declares."""

    def __init__(self, state: JobState) -> None:
        self._state = state

    async def create(
        self,
        type: str,
        name: str,
        *,
        aliases: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        from momentum.domain.entities.service import create_entity

        state = self._state
        s = _session(state, "entities.create", type)
        e = await create_entity(
            s,
            state.ctx,
            state.pack.entity_type(type),
            pack_key=state.pack.key,
            name=name,
            aliases=aliases,
            attributes=attributes,
        )
        return e.id

    async def _type(self, s: AsyncSession, entity_id: uuid.UUID) -> str:
        from momentum.domain.entities.service import get_entity

        return (await get_entity(s, self._state.ctx, entity_id)).type

    async def update(
        self,
        entity_id: uuid.UUID,
        *,
        name: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        from momentum.domain.entities.service import update_entity

        state = self._state
        if state.scope is None:
            raise PackError("job.effects.entities.update can only be called inside a step")
        type_ = await self._type(state.scope.session, entity_id)
        s = _session(state, "entities.update", type_)
        await update_entity(
            s, state.ctx, state.pack.entity_type(type_), entity_id, name=name, attributes=attributes
        )

    async def add_alias(self, entity_id: uuid.UUID, alias: str) -> None:
        from momentum.domain.entities.service import add_alias

        state = self._state
        if state.scope is None:
            raise PackError("job.effects.entities.add_alias can only be called inside a step")
        s = _session(state, "entities.update", await self._type(state.scope.session, entity_id))
        await add_alias(s, state.ctx, entity_id, alias)

    async def set_bank(self, entity_id: uuid.UUID, account: str) -> BankSeen:
        """Record the bank account seen for an entity (only a fingerprint and the last four
        digits are kept); says whether it differs from the one on file."""
        from momentum.domain.entities.service import set_bank

        state = self._state
        if state.scope is None:
            raise PackError("job.effects.entities.set_bank can only be called inside a step")
        s = _session(state, "entities.update", await self._type(state.scope.session, entity_id))
        changed, last4 = await set_bank(s, state.ctx, entity_id, account)
        return BankSeen(changed=changed, last4=last4)


class _Skills:
    """``job.effects.skills``: proposing what was learned (``skills.propose: [hint, rule]``)."""

    def __init__(self, state: JobState) -> None:
        self._state = state

    async def propose(
        self,
        kind: str,
        content: dict[str, Any],
        *,
        scope: str = "workspace",
        scope_id: uuid.UUID | None = None,
        field: str | None = None,
        provenance: dict[str, Any] | None = None,
        record_values: Any = None,
    ) -> SkillProposal:
        """Propose a skill for review. Text carrying a value from ``record_values``, an email, a
        bank or card number… is refused (kept as rejected, with the reason). A pack with a
        ``tryout`` capability gets a child job to try the skill out."""
        from momentum.agents.jobs.engine import create_child
        from momentum.domain.skills.service import propose

        state = self._state
        s = _session(state, "skills.propose", kind)
        skill = await propose(
            s,
            state.ctx,
            pack_key=state.pack.key,
            scope_type=scope,
            scope_id=scope_id,
            kind=kind,
            content=content,
            field=field,
            provenance={"run_id": str(state.run_id), **(provenance or {})},
            record_values=record_values,
        )
        if skill.status == "proposed" and "tryout" in state.pack.capabilities:
            await create_child(
                s,
                state,
                "tryout",
                {"skill_id": str(skill.id)},
                title="Try out a proposed skill",
                key=f"tryout:{skill.id}",
                task=None,
            )
        return SkillProposal(id=skill.id, status=skill.status, note=skill.decision_note)

    async def record_tryout(self, skill_id: uuid.UUID, result: dict[str, Any]) -> None:
        """A tryout's results (``{status, before, after, regressions}``) for the reviewers."""
        from momentum.domain.skills.models import Skill
        from momentum.domain.skills.service import set_tryout

        state = self._state
        if state.scope is None:
            raise PackError("job.effects.skills.record_tryout can only be called inside a step")
        skill = await state.scope.session.get(Skill, skill_id)
        if skill is None or skill.pack_key != state.pack.key:
            raise ValidationFailed("No such skill for this pack")
        _session(state, "skills.propose", skill.kind)
        await set_tryout(state.scope.session, skill_id, result)
