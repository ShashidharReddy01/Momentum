"""S4.3.1 project templates: "Save as template" walks a project's sections, tasks and subtasks
into a JSON payload (dates relative to a reference date, assignees replaced by roles, the
project's attached fields and rules); "New from template" replays that payload into a brand new
project. Everything is written through the same services every other caller uses (one write
path): ``domain.projects.service.create_project``, ``domain.tasks.service.create_task`` /
``create_subtask`` / ``update_task``, ``domain.fields.service.attach_field`` /
``set_task_field_value``, ``domain.rules.service.create_rule``.

Task templates (S4.3.2) share this table (``kind="task"``, ``project_id`` set) but are built and
replayed by that slice's own functions below the project-template ones.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import DomainError, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, can
from momentum.domain.access import forbid_agent, get_visible_project, require_project_role
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.project_values import project_field_values, set_project_field_value
from momentum.domain.fields.service import (
    attach_field,
    list_project_field_values,
    list_project_fields,
    set_task_field_value,
    validate_value,
)
from momentum.domain.projects.schemas import ProjectCreateIn
from momentum.domain.projects.service import create_project
from momentum.domain.rules.models import Rule
from momentum.domain.rules.schemas import RuleIn
from momentum.domain.rules.service import create_rule, list_rules
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import create_section, rename_section
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import (
    add_dependency,
    create_subtask,
    create_task,
    update_task,
)
from momentum.domain.templates.models import Template
from momentum.domain.templates.schemas import (
    NewProjectFromTemplateIn,
    NewTaskFromTemplateIn,
    SaveProjectTemplateIn,
    SaveTaskTemplateIn,
)
from momentum.domain.users.models import User


def _channels(project_id: uuid.UUID | None) -> list[str]:
    return [f"project:{project_id}"] if project_id else []


async def _load(session: AsyncSession, ctx: Ctx, template_id: uuid.UUID) -> Template:
    t = await session.get(Template, template_id)
    if t is None or t.workspace_id != ctx.workspace_id or t.deleted_at is not None:
        raise NotFound("Template not found")
    return t


async def list_templates(
    session: AsyncSession, ctx: Ctx, kind: str, project_id: uuid.UUID | None = None
) -> list[Template]:
    """Any workspace member can browse project templates — they're a starting point for a new
    project, not sensitive data of their own (the project they were built from stays under its
    own permissions). Task templates are scoped to one project (S4.3.2: "per-project"), so
    ``project_id`` filters those down to what that project's own viewers should see."""
    stmt = select(Template).where(
        Template.workspace_id == ctx.workspace_id,
        Template.kind == kind,
        Template.deleted_at.is_(None),
    )
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)
        stmt = stmt.where(Template.project_id == project_id)
    rows = await session.execute(stmt.order_by(Template.name))
    return list(rows.scalars())


async def get_template(session: AsyncSession, ctx: Ctx, template_id: uuid.UUID) -> Template:
    return await _load(session, ctx, template_id)


async def delete_template(session: AsyncSession, ctx: Ctx, template_id: uuid.UUID) -> None:
    forbid_agent(ctx, "delete templates")
    t = await _load(session, ctx, template_id)
    allowed = t.created_by == ctx.actor.id
    if not allowed and t.kind == "task" and t.project_id is not None:
        _, role = await get_visible_project(session, ctx, t.project_id)
        allowed = role == "admin"
    elif not allowed:
        allowed = ctx.actor.is_admin
    if not allowed:
        raise Forbidden("Only the template's creator or an admin can delete it")
    t.deleted_at = datetime.now(UTC)
    await session.flush()


# ---------------- save as template ----------------


class _Roles:
    def __init__(self) -> None:
        self.by_user: dict[uuid.UUID, str] = {}
        self.labels: dict[str, str] = {}

    def for_user(self, user: User | None) -> str | None:
        if user is None:
            return None
        role = self.by_user.get(user.id)
        if role is None:
            role = f"r{len(self.by_user) + 1}"
            self.by_user[user.id] = role
            self.labels[role] = user.name
        return role

    def as_list(self) -> list[dict[str, str]]:
        return [{"id": rid, "label": label} for rid, label in self.labels.items()]


def _offset(reference: date | None, day: date | None) -> int | None:
    if day is None:
        return None
    if reference is None:
        return 0
    return (day - reference).days


async def _capture_task(
    session: AsyncSession,
    task: Task,
    roles: _Roles,
    users: dict[uuid.UUID, User],
    field_values: dict[uuid.UUID, dict[str, Any]],
    reference: date | None,
) -> dict[str, Any]:
    children = list(
        (
            await session.execute(
                select(Task)
                .where(Task.parent_id == task.id, Task.deleted_at.is_(None))
                .order_by(Task.parent_position)
            )
        ).scalars()
    )
    return {
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "due_offset_days": _offset(reference, task.due_on),
        "start_offset_days": _offset(reference, task.start_on),
        "role_id": roles.for_user(users.get(task.assignee_id) if task.assignee_id else None),
        "field_values": field_values.get(task.id, {}),
        "subtasks": [
            await _capture_task(session, child, roles, users, field_values, reference)
            for child in children
        ],
    }


def _remap_user(value: Any, roles: _Roles, users: dict[uuid.UUID, User]) -> Any:
    if value is None:
        return None
    try:
        uid = uuid.UUID(str(value))
    except ValueError:
        return value
    return roles.for_user(users.get(uid))


def _capture_rule(
    rule: Rule, section_index: dict[uuid.UUID, int], roles: _Roles, users: dict[uuid.UUID, User]
) -> dict[str, Any]:
    trigger = dict(rule.trigger)
    if trigger.get("to_section"):
        trigger["section_index"] = section_index.get(uuid.UUID(str(trigger.pop("to_section"))))
    if "user_id" in trigger:
        trigger["role_id"] = _remap_user(trigger.pop("user_id"), roles, users)
    actions = []
    for a in rule.actions:
        a = dict(a)
        if a.get("type") == "move_section" and a.get("section_id"):
            a["section_index"] = section_index.get(uuid.UUID(str(a.pop("section_id"))))
        if "user_id" in a:
            a["role_id"] = _remap_user(a.pop("user_id"), roles, users)
        actions.append(a)
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "trigger": trigger,
        "conditions": list(rule.conditions),
        "actions": actions,
    }


async def save_project_template(
    session: AsyncSession, ctx: Ctx, data: SaveProjectTemplateIn
) -> Mutation[Template]:
    if ctx.actor.id is None:
        raise Forbidden("Templates need a person to act as")
    project, role = await get_visible_project(session, ctx, data.project_id)
    require_project_role(role, "admin", "save this project as a template")

    sections = list(
        (
            await session.execute(
                select(Section)
                .where(Section.project_id == project.id, Section.deleted_at.is_(None))
                .order_by(Section.position)
            )
        ).scalars()
    )
    section_index = {s.id: i for i, s in enumerate(sections)}

    top_level = list(
        (
            await session.execute(
                select(Task, TaskProject.section_id, TaskProject.position)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == project.id,
                    Task.parent_id.is_(None),
                    Task.deleted_at.is_(None),
                )
                .order_by(TaskProject.section_id, TaskProject.position)
            )
        ).all()
    )
    by_section: dict[uuid.UUID, list[Task]] = {s.id: [] for s in sections}
    for task, section_id, _pos in top_level:
        by_section.setdefault(section_id, []).append(task)

    all_dates = [d for t, _s, _p in top_level for d in (t.due_on, t.start_on) if d is not None]
    reference = min(all_dates) if all_dates else None

    assignee_ids = {t.assignee_id for t, _s, _p in top_level if t.assignee_id}
    users = (
        {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(assignee_ids)))
            ).scalars()
        }
        if assignee_ids
        else {}
    )
    values = await list_project_field_values(session, ctx, project.id)
    field_values: dict[uuid.UUID, dict[str, Any]] = {}
    for v in values:
        field_values.setdefault(v.task_id, {})[str(v.field_id)] = v.value

    roles = _Roles()
    sections_payload = []
    position: dict[uuid.UUID, list[int]] = {}  # task id -> [section index, task index]
    for si, section in enumerate(sections):
        for ti, t in enumerate(by_section.get(section.id, [])):
            position[t.id] = [si, ti]
    for section in sections:
        tasks_payload = [
            await _capture_task(session, t, roles, users, field_values, reference)
            for t in by_section.get(section.id, [])
        ]
        sections_payload.append({"name": section.name, "tasks": tasks_payload})

    fields = [pf.field_id for pf, _f in await list_project_fields(session, ctx, project.id)]
    rules = await list_rules(session, ctx, project.id)
    # rule user references also need capturing before we know every assignee: gather them too
    for r in rules:
        for uid_str in [r.trigger.get("user_id")] + [a.get("user_id") for a in r.actions]:
            if uid_str:
                uid = uuid.UUID(str(uid_str))
                if uid not in users:
                    u = await session.get(User, uid)
                    if u is not None:
                        users[uid] = u
    rules_payload = [_capture_rule(r, section_index, roles, users) for r in rules]

    # S6.1.3: "B waits on A" between two of the project's top-level tasks, by position
    dependencies = (
        [
            {"task": position[task_id], "blocked_by": position[blocker_id]}
            for task_id, blocker_id in (
                await session.execute(
                    select(TaskDependency.task_id, TaskDependency.depends_on_id)
                    .where(
                        TaskDependency.task_id.in_(position.keys()),
                        TaskDependency.depends_on_id.in_(position.keys()),
                    )
                    .order_by(TaskDependency.created_at)
                )
            ).all()
        ]
        if position
        else []
    )

    # Phase 7.5: the project's own field values become the new projects' defaults
    project_defaults = {
        str(v.field_id): v.value for v in await project_field_values(session, ctx, project.id)
    }
    payload = {
        "roles": roles.as_list(),
        "fields": [str(f) for f in fields],
        "project_field_defaults": project_defaults,
        "sections": sections_payload,
        "rules": rules_payload,
        "dependencies": dependencies,
    }
    template = Template(
        workspace_id=ctx.workspace_id,
        project_id=None,
        kind="project",
        name=data.name,
        description=data.description,
        payload=payload,
        created_by=ctx.actor.id,
    )
    session.add(template)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="template",
        entity_id=template.id,
        verb="template.created",
        changes={"name": (None, template.name)},
    )
    await emit(
        session,
        ctx,
        type="template.created",
        entity_type="template",
        entity_id=template.id,
        data={"kind": "project"},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(template, act.id, version=1)


async def save_template_payload(
    session: AsyncSession, ctx: Ctx, name: str, description: str | None, payload: dict[str, Any]
) -> Mutation[Template]:
    """S4.3.3: persist an already-built project-template payload (from
    ``ai.template_from_brief.to_payload``) directly — there's no source project to walk, so this
    skips straight to the same row `save_project_template` ends with. Same bar as creating a
    project (`Action.PROJECT_CREATE`): a template only ever produces a new project, never touches
    an existing one, so anyone who could create a project by hand can save one as a shortcut."""
    if ctx.actor.id is None:
        raise Forbidden("Templates need a person to act as")
    if not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You don't have permission to create projects, so not templates either")
    template = Template(
        workspace_id=ctx.workspace_id,
        project_id=None,
        kind="project",
        name=name,
        description=description,
        payload=payload,
        created_by=ctx.actor.id,
    )
    session.add(template)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="template",
        entity_id=template.id,
        verb="template.created",
        changes={"name": (None, template.name)},
    )
    await emit(
        session,
        ctx,
        type="template.created",
        entity_type="template",
        entity_id=template.id,
        data={"kind": "project"},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    return Mutation(template, act.id, version=1)


# ---------------- new from template ----------------


async def _instantiate_task(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    spec: dict[str, Any],
    start_date: date,
    role_map: dict[str, uuid.UUID],
    fields_by_id: dict[uuid.UUID, FieldDef],
    parent_id: uuid.UUID | None,
) -> uuid.UUID:
    due_days = spec.get("due_offset_days")
    start_days = spec.get("start_offset_days")
    due_on = start_date + timedelta(days=int(due_days)) if due_days is not None else None
    role_id = spec.get("role_id")
    assignee_id = role_map.get(role_id) if role_id else None
    title = str(spec["title"])[:500] or "Untitled"

    if parent_id is None:
        m = await create_task(
            session,
            ctx,
            project_id,
            title,
            section_id=section_id,
            assignee_id=assignee_id,
            due_on=due_on,
            priority=spec.get("priority"),
        )
        task_id = m.entity[0].id
    else:
        m2 = await create_subtask(session, ctx, parent_id, title)
        task_id = m2.entity.id
        patch: dict[str, Any] = {}
        if assignee_id is not None:
            patch["assignee_id"] = str(assignee_id)
        if due_on is not None:
            patch["due_on"] = due_on.isoformat()
        if spec.get("priority"):
            patch["priority"] = spec["priority"]
        if patch:
            await update_task(session, ctx, task_id, patch)

    patch2: dict[str, Any] = {}
    if start_days is not None:
        patch2["start_on"] = (start_date + timedelta(days=int(start_days))).isoformat()
    if spec.get("description"):
        patch2["description"] = spec["description"]
    if patch2:
        await update_task(session, ctx, task_id, patch2)

    for field_id_str, value in (spec.get("field_values") or {}).items():
        field = fields_by_id.get(uuid.UUID(field_id_str))
        if field is None or value is None:
            continue
        try:
            clean = validate_value(field, value)
        except ValidationFailed:
            continue
        await set_task_field_value(session, ctx, task_id, field.id, clean)

    for sub in spec.get("subtasks") or []:
        await _instantiate_task(
            session, ctx, project_id, section_id, sub, start_date, role_map, fields_by_id, task_id
        )
    return task_id


async def create_project_from_template(
    session: AsyncSession, ctx: Ctx, template_id: uuid.UUID, data: NewProjectFromTemplateIn
) -> Mutation[Any]:
    if ctx.actor.id is None:
        raise Forbidden("Templates need a person to act as")
    template = await get_template(session, ctx, template_id)
    if template.kind != "project":
        raise ValidationFailed("That isn't a project template")
    payload = template.payload
    role_map = {rm.role_id: rm.user_id for rm in data.role_mapping if rm.user_id is not None}

    m = await create_project(
        session,
        ctx,
        ProjectCreateIn(
            team_id=data.team_id, name=data.name, privacy=data.privacy, color=data.color
        ),
    )
    project = m.entity
    # Phase 7.5: lineage, so a rule portfolio can include "every project made from this template"
    project.template_id = template.id
    for fid, value in (payload.get("project_field_defaults") or {}).items():
        try:
            await set_project_field_value(session, ctx, project.id, uuid.UUID(fid), value)
        except (DomainError, ValueError):
            continue  # a field deleted or changed since the template was saved: skip it

    sections_payload = payload.get("sections") or []
    default = (
        (
            await session.execute(
                select(Section).where(
                    Section.project_id == project.id, Section.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )
    section_ids: list[uuid.UUID] = []
    prev_id: uuid.UUID | None = None
    for i, s in enumerate(sections_payload):
        if i == 0 and default is not None:
            await rename_section(session, ctx, default.id, s["name"])
            section_ids.append(default.id)
            prev_id = default.id
        else:
            sm = await create_section(session, ctx, project.id, s["name"], after_id=prev_id)
            section_ids.append(sm.entity.id)
            prev_id = sm.entity.id

    field_ids = [uuid.UUID(f) for f in payload.get("fields") or []]
    fields_by_id: dict[uuid.UUID, FieldDef] = {}
    for fid in field_ids:
        field = await session.get(FieldDef, fid)
        if field is None or field.deleted_at is not None:
            continue
        fields_by_id[fid] = field
        # Already attached, or no longer attachable; the field values still get written.
        with contextlib.suppress(DomainError):
            await attach_field(session, ctx, project.id, fid, None, None)

    created: dict[tuple[int, int], uuid.UUID] = {}
    for si, (section_id, s) in enumerate(zip(section_ids, sections_payload, strict=True)):
        for ti, t in enumerate(s.get("tasks") or []):
            created[(si, ti)] = await _instantiate_task(
                session,
                ctx,
                project.id,
                section_id,
                t,
                data.start_date,
                role_map,
                fields_by_id,
                None,
            )

    # S6.1.3: replay "waits on" links through the one write path (cycle check included); a link
    # that no longer resolves (an older or hand-edited payload) is skipped, not fatal
    for dep in payload.get("dependencies") or []:
        try:
            task_id = created.get((int(dep["task"][0]), int(dep["task"][1])))
            blocker_id = created.get((int(dep["blocked_by"][0]), int(dep["blocked_by"][1])))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if task_id is None or blocker_id is None or task_id == blocker_id:
            continue
        with contextlib.suppress(DomainError):
            await add_dependency(session, ctx, task_id, blocker_id)

    for r in payload.get("rules") or []:
        trigger = dict(r["trigger"])
        idx = trigger.pop("section_index", None)
        if idx is not None and idx < len(section_ids):
            trigger["to_section"] = str(section_ids[idx])
        role_id = trigger.pop("role_id", None)
        if role_id is not None and role_id in role_map:
            trigger["user_id"] = str(role_map[role_id])
        actions = []
        for a in r["actions"]:
            a = dict(a)
            idx = a.pop("section_index", None)
            if idx is not None and idx < len(section_ids):
                a["section_id"] = str(section_ids[idx])
            role_id = a.pop("role_id", None)
            if role_id is not None and role_id in role_map:
                a["user_id"] = str(role_map[role_id])
            actions.append(a)
        try:
            rule_in = RuleIn(
                name=r["name"],
                enabled=r["enabled"],
                project_id=project.id,
                trigger=trigger,
                conditions=r.get("conditions") or [],
                actions=actions,
            )
            await create_rule(session, ctx, rule_in)
        except (DomainError, ValueError):
            # A reference this rule needs no longer resolves; skip it, not the whole template.
            continue

    return m


# ---------------- task templates (S4.3.2) ----------------


def _text_doc(text: str) -> dict[str, Any]:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in lines
            if line
        ],
    }


async def save_task_template(
    session: AsyncSession, ctx: Ctx, data: SaveTaskTemplateIn
) -> Mutation[Template]:
    if ctx.actor.id is None:
        raise Forbidden("Templates need a person to act as")
    _, role = await get_visible_project(session, ctx, data.project_id)
    require_project_role(role, "editor", "save a task template")
    payload = {
        "title": data.title,
        "description": data.description,
        "subtasks": list(data.subtasks),
        "field_values": dict(data.field_values),
    }
    template = Template(
        workspace_id=ctx.workspace_id,
        project_id=data.project_id,
        kind="task",
        name=data.name,
        description=None,
        payload=payload,
        created_by=ctx.actor.id,
    )
    session.add(template)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="template",
        entity_id=template.id,
        verb="template.created",
        changes={"name": (None, template.name)},
    )
    await emit(
        session,
        ctx,
        type="template.created",
        entity_type="template",
        entity_id=template.id,
        data={"kind": "task", "project_id": str(data.project_id)},
        channels=_channels(data.project_id),
        activity_id=act.id,
    )
    return Mutation(template, act.id, version=1)


async def create_task_from_template(
    session: AsyncSession, ctx: Ctx, template_id: uuid.UUID, data: NewTaskFromTemplateIn
) -> Mutation[tuple[Task, TaskProject]]:
    template = await get_template(session, ctx, template_id)
    if template.kind != "task" or template.project_id is None:
        raise ValidationFailed("That isn't a task template")
    payload = template.payload
    title = (data.title or payload["title"])[:500]

    m = await create_task(
        session,
        ctx,
        template.project_id,
        title,
        section_id=data.section_id,
        assignee_id=data.assignee_id,
        due_on=data.due_on,
    )
    task = m.entity[0]
    if payload.get("description"):
        await update_task(session, ctx, task.id, {"description": _text_doc(payload["description"])})
    for field_id_str, value in (payload.get("field_values") or {}).items():
        field = await session.get(FieldDef, uuid.UUID(field_id_str))
        if field is None or field.deleted_at is not None or value is None:
            continue
        try:
            clean = validate_value(field, value)
        except ValidationFailed:
            continue
        await set_task_field_value(session, ctx, task.id, field.id, clean)
    for subtask_title in payload.get("subtasks") or []:
        await create_subtask(session, ctx, task.id, subtask_title)
    return m
