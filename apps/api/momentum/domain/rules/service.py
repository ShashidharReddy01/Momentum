"""S4.1.1: rule management (create, edit, enable, delete, run history). The executor that fires
rules is ``engine.py``; both write only through services.

Who may manage rules: a project's admins for its rules, workspace admins for workspace rules
(auth-and-permissions.md lists editors as "✓ (setting)"; there is no such setting yet, so the
stricter default applies). Viewing rules and their runs needs editor on the project.

Rule changes are configuration, not task data: they record activity and events, and only a
delete can be undone (H56: a deleted rule had no way back; an edit or a disable is changed back
the same way it was made).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, can
from momentum.core.undo import undo_handler, undo_op
from momentum.domain.access import (
    forbid_agent,
    get_visible_project,
    get_visible_task,
    require_project_role,
)
from momentum.domain.fields.models import FieldDef
from momentum.domain.forms.models import Form
from momentum.domain.projects.models import Project
from momentum.domain.rules import engine
from momentum.domain.rules.models import Rule, RuleAiStep, RuleRun
from momentum.domain.rules.schemas import RuleIn, RulePatchIn, RuleSpec, is_custom_field
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag
from momentum.domain.users.models import User

RUNS_PAGE = 50


def _channels(project_id: uuid.UUID | None, ctx: Ctx) -> list[str]:
    return [f"project:{project_id}"] if project_id else [f"workspace:{ctx.workspace_id}"]


async def _authorize(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None, needed: str, what: str
) -> None:
    if project_id is None:
        if not can(ctx, Action.WORKSPACE_ADMIN):
            raise Forbidden("Only workspace admins can manage workspace rules")
        return
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, needed, what)


async def authorize_manage(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID) -> Project:
    """The permission ``create_rule`` needs on a project, and the project itself. S4.1.4's
    natural-language compiler checks this before it spends a model call, and needs the project's
    own sections, people, tags and fields to resolve what the user described."""
    await _authorize(session, ctx, project_id, "admin", "manage rules")
    project, _role = await get_visible_project(session, ctx, project_id)
    return project


async def _load(
    session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID, needed: str, what: str
) -> Rule:
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.workspace_id != ctx.workspace_id or rule.deleted_at is not None:
        raise NotFound("Rule not found")
    await _authorize(session, ctx, rule.project_id, needed, what)
    return rule


async def _check_references(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None, spec: RuleSpec
) -> None:
    """Every id the rule mentions must exist. ``move_section``'s section (like the trigger's)
    must be in the rule's own project; ``add_to_project``'s section is checked against that
    action's own target project instead."""
    trigger, conditions, actions = spec.trigger, spec.conditions, spec.actions
    own_sections = {trigger.to_section} | {
        a.section_id for a in actions if a.type == "move_section"
    }
    users = {trigger.user_id} | {a.user_id for a in actions}
    tags = {a.tag_id for a in actions if a.type == "add_tag"}
    other_projects = {
        a.project_id for a in actions if a.type in ("add_to_project", "remove_from_project")
    }
    fields: set[uuid.UUID] = set()
    if trigger.field and is_custom_field(trigger.field):
        fields.add(uuid.UUID(trigger.field))
    for a in actions:
        if a.type in ("set_field", "ai_step") and a.field_id and is_custom_field(a.field_id):
            fields.add(uuid.UUID(a.field_id))
    for c in conditions:
        raw = c.value if isinstance(c.value, list) else [c.value]
        ids = {uuid.UUID(v) for v in raw if c.field in ("assignee", "tag") and isinstance(v, str)}
        (users if c.field == "assignee" else tags).update(ids)
        if is_custom_field(c.field):
            fields.add(uuid.UUID(c.field))
    for section_id in own_sections - {None}:
        section = await session.get(Section, section_id)
        if (
            section is None
            or section.deleted_at is not None
            or (project_id is not None and section.project_id != project_id)
        ):
            raise ValidationFailed("That section isn't in this project")
    if trigger.form_id is not None:
        form = await session.get(Form, trigger.form_id)
        if (
            form is None
            or form.deleted_at is not None
            or (project_id is not None and form.project_id != project_id)
        ):
            raise ValidationFailed("That form isn't in this project")
    for other_id in other_projects - {None}:
        target = await session.get(Project, other_id)
        if (
            target is None
            or target.workspace_id != ctx.workspace_id
            or target.deleted_at is not None
        ):
            raise ValidationFailed("Unknown project in the rule")
    for a in actions:
        if a.type == "add_to_project" and a.section_id is not None:
            section = await session.get(Section, a.section_id)
            if (
                section is None
                or section.deleted_at is not None
                or section.project_id != a.project_id
            ):
                raise ValidationFailed("That section isn't in the target project")
    for user_id in users - {None}:
        user = await session.get(User, user_id)
        if user is None or user.workspace_id != ctx.workspace_id or user.status != "active":
            raise ValidationFailed("Unknown person in the rule")
    for tag_id in tags - {None}:
        tag = await session.get(Tag, tag_id)
        if tag is None or tag.workspace_id != ctx.workspace_id:
            raise ValidationFailed("Unknown tag in the rule")
    for field_id in fields:
        field = await session.get(FieldDef, field_id)
        if field is None or field.workspace_id != ctx.workspace_id or field.deleted_at is not None:
            raise ValidationFailed("Unknown field in the rule")


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json", exclude_unset=True)


async def list_rules(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None) -> list[Rule]:
    """A project's rules (or the workspace's when ``project_id`` is null), oldest first."""
    await _authorize(session, ctx, project_id, "editor", "see rules")
    stmt = select(Rule).where(Rule.workspace_id == ctx.workspace_id, Rule.deleted_at.is_(None))
    stmt = stmt.where(Rule.project_id == project_id if project_id else Rule.project_id.is_(None))
    return list((await session.execute(stmt.order_by(Rule.created_at, Rule.id))).scalars())


async def get_rule(session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID) -> Rule:
    return await _load(session, ctx, rule_id, "editor", "see this rule")


async def list_runs(
    session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID, *, limit: int = RUNS_PAGE
) -> list[tuple[RuleRun, list[RuleAiStep]]]:
    """A rule's recent runs, newest first, each with the AI steps it queued (S4.1.5: a step
    outlives its run, so its own status is what the history shows)."""
    rule = await _load(session, ctx, rule_id, "editor", "see this rule's runs")
    rows = await session.execute(
        select(RuleRun)
        .where(RuleRun.rule_id == rule.id)
        .order_by(RuleRun.started_at.desc(), RuleRun.id.desc())
        .limit(limit)
    )
    runs = list(rows.scalars())
    steps: dict[uuid.UUID, list[RuleAiStep]] = {}
    if runs:
        found = await session.execute(
            select(RuleAiStep)
            .where(RuleAiStep.rule_run_id.in_([r.id for r in runs]))
            .order_by(RuleAiStep.created_at, RuleAiStep.id)
        )
        for step in found.scalars():
            if step.rule_run_id is not None:
                steps.setdefault(step.rule_run_id, []).append(step)
    return [(r, steps.get(r.id, [])) for r in runs]


async def create_rule(session: AsyncSession, ctx: Ctx, data: RuleIn) -> Mutation[Rule]:
    if ctx.actor.id is None:
        raise Forbidden("Rules need a person to act as")
    await _authorize(session, ctx, data.project_id, "admin", "manage rules")
    await _check_references(session, ctx, data.project_id, data)
    rule = Rule(
        workspace_id=ctx.workspace_id,
        project_id=data.project_id,
        name=data.name,
        enabled=data.enabled,
        trigger=_dump(data.trigger),
        conditions=[_dump(c) for c in data.conditions],
        actions=[_dump(a) for a in data.actions],
        created_from_prompt=data.created_from_prompt,
        created_by=ctx.actor.id,
    )
    session.add(rule)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="rule",
        entity_id=rule.id,
        verb="rule.created",
        changes={"name": (None, rule.name)},
    )
    await emit(
        session,
        ctx,
        type="rule.created",
        entity_type="rule",
        entity_id=rule.id,
        data={"project_id": str(rule.project_id) if rule.project_id else None},
        channels=_channels(rule.project_id, ctx),
        activity_id=act.id,
    )
    return Mutation(rule, act.id, version=rule.version)


async def update_rule(
    session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID, data: RulePatchIn
) -> Mutation[Rule]:
    rule = await _load(session, ctx, rule_id, "admin", "manage rules")
    if data.expected_version is not None and data.expected_version != rule.version:
        raise VersionConflict("This rule was changed by someone else", version=rule.version)
    sent = data.model_fields_set
    spec = RuleSpec.model_validate(
        {
            "trigger": _dump(data.trigger) if "trigger" in sent else rule.trigger,
            "conditions": [_dump(c) for c in data.conditions or []]
            if "conditions" in sent
            else rule.conditions,
            "actions": [_dump(a) for a in data.actions or []]
            if "actions" in sent
            else rule.actions,
        }
    )
    if sent & {"trigger", "conditions", "actions"}:
        await _check_references(session, ctx, rule.project_id, spec)
    new: dict[str, Any] = {
        "trigger": _dump(spec.trigger),
        "conditions": [_dump(c) for c in spec.conditions],
        "actions": [_dump(a) for a in spec.actions],
    }
    if data.name is not None:
        new["name"] = data.name
    if data.enabled is not None:
        new["enabled"] = data.enabled
    changes: Diff = {}
    for key, value in new.items():
        if getattr(rule, key) != value:
            changes[key] = (getattr(rule, key), value)
            setattr(rule, key, value)
    if not changes:
        return Mutation(rule, version=rule.version)
    rule.version += 1
    rule.updated_at = datetime.now(UTC)
    act = await record_activity(
        session, ctx, entity_type="rule", entity_id=rule.id, verb="rule.updated", changes=changes
    )
    await emit(
        session,
        ctx,
        type="rule.updated",
        entity_type="rule",
        entity_id=rule.id,
        data={"changes": sorted(changes), "version": rule.version},
        channels=_channels(rule.project_id, ctx),
        activity_id=act.id,
    )
    return Mutation(rule, act.id, version=rule.version)


async def test_run_rule(
    session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID, task_id: uuid.UUID
) -> engine.TestRunResult:
    """Preview a rule's actions against a chosen task without persisting anything (S4.1.3's
    "test run"). Same permission as editing the rule: this runs the rule's actions for real
    (rolled back afterward), so it's not something a viewer of the rule should be able to
    trigger."""
    rule = await _load(session, ctx, rule_id, "admin", "test this rule")
    task, _placement, _role = await get_visible_task(session, ctx, task_id)
    return await engine.test_run(session, ctx.settings, rule, task)


async def delete_rule(session: AsyncSession, ctx: Ctx, rule_id: uuid.UUID) -> Mutation[Rule]:
    """Soft delete: the run history stays."""
    forbid_agent(ctx, "delete rules")
    rule = await _load(session, ctx, rule_id, "admin", "manage rules")
    rule.deleted_at = datetime.now(UTC)
    rule.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="rule",
        entity_id=rule.id,
        verb="rule.deleted",
        undo=undo_op("rules.restore", rule_id=rule.id),
    )
    await emit(
        session,
        ctx,
        type="rule.deleted",
        entity_type="rule",
        entity_id=rule.id,
        data={"project_id": str(rule.project_id) if rule.project_id else None},
        channels=_channels(rule.project_id, ctx),
        activity_id=act.id,
    )
    return Mutation(rule, act.id, version=rule.version)


@undo_handler("rules.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    rule = await session.get(Rule, uuid.UUID(str(args["rule_id"])))
    if rule is None or rule.workspace_id != ctx.workspace_id:
        raise NotFound("Rule not found")
    await _authorize(session, ctx, rule.project_id, "admin", "manage rules")
    if rule.deleted_at is None:
        return
    rule.deleted_at = None
    rule.version += 1
    rule.updated_at = datetime.now(UTC)
    act = await record_activity(
        session, ctx, entity_type="rule", entity_id=rule.id, verb="rule.restored"
    )
    await emit(
        session,
        ctx,
        type="rule.restored",
        entity_type="rule",
        entity_id=rule.id,
        data={"project_id": str(rule.project_id) if rule.project_id else None},
        channels=_channels(rule.project_id, ctx),
        activity_id=act.id,
    )
