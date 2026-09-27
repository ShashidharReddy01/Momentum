"""S4.1.4 "NL → rule": one sentence ("when a task moves to Review, assign it to Mei") → a
validated rule draft for the rule builder to show, prefilled and editable. Nothing is saved
here: the client posts the draft to ``POST /rules`` like any hand-built rule (one write path),
with ``created_from_prompt`` set to what the user typed.

The model works in **names** and the server resolves them to ids inside the rule's own project
(the same scope ``domain/rules/service.py`` validates against), because ids must exist there and
a model shouldn't be trusted to copy uuids. Anything the server can't resolve — an unknown or
ambiguous section, person, tag, project or field — becomes a question back to the user instead
of a guess, as does a phrase the rule engine can't express (Slack, AI steps, schedules) or one
the model itself found unclear.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.breakdown import match_person, project_people
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_project
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.access import visible_projects_clause
from momentum.domain.fields.service import list_project_fields
from momentum.domain.projects.models import Project
from momentum.domain.rules.schemas import MAX_ACTIONS, MAX_CONDITIONS, RuleIn
from momentum.domain.rules.service import authorize_manage
from momentum.domain.sections.service import list_sections
from momentum.domain.tags.service import list_tags
from momentum.domain.users.models import User

MAX_TEXT = 500
# Other projects listed for add_to_project/remove_from_project. A workspace with more than
# this many visible projects shows the first few alphabetically; naming one that isn't listed
# still works, because the server resolves the name itself.
OTHER_PROJECTS = 40

# The trigger, condition and action vocabularies the model may use. They repeat
# ``domain/rules/schemas.py`` on purpose — as literals they become an enum in the tool schema,
# which is what makes the model pick a real type (and get one repair attempt when it doesn't).
# ``test_ai_nl_rule.py`` fails if they drift from the schemas or from the prompt.
TriggerType = Literal[
    "task.added",
    "task.moved",
    "task.field_changed",
    "task.completed",
    "task.assigned",
    "task.due_approaching",
]
ActionType = Literal[
    "assign",
    "add_comment",
    "move_section",
    "mark_complete",
    "set_field",
    "add_to_project",
    "remove_from_project",
    "add_tag",
    "create_subtasks",
    "set_due_relative",
    "notify_user",
]
Op = Literal["eq", "neq", "in", "empty", "not_empty", "gt", "lt"]

TASK_FIELDS = {
    "priority": "priority",
    "due_on": "due_on",
    "due date": "due_on",
    "due": "due_on",
    "start_on": "start_on",
    "start date": "start_on",
    "start": "start_on",
}
CONDITION_ONLY = {"assignee": "assignee", "assigned to": "assignee", "tag": "tag", "tags": "tag"}
ME = {"me", "myself", "i", "the person asking"}


class DraftTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TriggerType
    section: str | None = Field(default=None, max_length=200, description="task.moved: its name")
    field: str | None = Field(default=None, max_length=200, description="task.field_changed")
    to: Any = Field(default=None, description="task.field_changed: the new value, if named")
    person: str | None = Field(default=None, max_length=200, description="task.assigned")


class DraftCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=200)
    op: Op
    value: Any = None


class DraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ActionType
    person: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=2000)
    section: str | None = Field(default=None, max_length=200)
    field: str | None = Field(default=None, max_length=200)
    value: Any = None
    project: str | None = Field(default=None, max_length=200)
    tag: str | None = Field(default=None, max_length=200)
    titles: list[str] | None = Field(default=None, max_length=20)
    days: int | None = Field(default=None, ge=-365, le=365)


class RuleDraft(BaseModel):
    """What the model submits: a rule in names, or only a question."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=200)
    trigger: DraftTrigger | None = None
    conditions: list[DraftCondition] = Field(default_factory=list, max_length=MAX_CONDITIONS)
    actions: list[DraftAction] = Field(default_factory=list, max_length=MAX_ACTIONS)
    question: str | None = Field(
        default=None, max_length=500, description="Ask instead of guessing; leave the rule empty"
    )


@dataclass
class CompiledRule:
    """Either ``rule`` (validated, with a readable sentence) or ``question``, never both."""

    rule: RuleIn | None = None
    named: dict[str, Any] | None = None  # the same rule with names instead of ids (for evals)
    sentence: str | None = None
    question: str | None = None
    notes: list[str] = dc_field(default_factory=list)


class _Ask(Exception):
    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


@dataclass
class _Refs:
    """What a rule on this project may point at, by name."""

    project: Project
    sections: list[tuple[uuid.UUID, str]]
    people: list[User]
    tags: list[tuple[uuid.UUID, str]]
    fields: list[tuple[uuid.UUID, str, str]]  # id, name, kind
    others: list[str]  # other projects the user can see, by name (add_to/remove_from_project)

    @property
    def person_options(self) -> list[tuple[uuid.UUID, str]]:
        return [(u.id, u.name) for u in self.people]


async def load_refs(session: AsyncSession, ctx: Ctx, project: Project) -> _Refs:
    attached = await list_project_fields(session, ctx, project.id)
    others = await session.execute(
        select(Project.name)
        .where(
            visible_projects_clause(ctx),
            Project.is_template.is_(False),
            Project.id != project.id,
        )
        .order_by(func.lower(Project.name))
        .limit(OTHER_PROJECTS)
    )
    return _Refs(
        project=project,
        sections=[(s.id, s.name) for s in await list_sections(session, project.id)],
        people=await project_people(session, project),
        tags=[(t.id, t.name) for t in await list_tags(session, ctx)],
        fields=[(f.id, f.name, f.type) for _pf, f in attached],
        others=list(others.scalars()),
    )


def reference_block(refs: _Refs) -> str:
    """The names the model may use, as prompt data (never instructions)."""
    fields = ", ".join(f"{safe(n)} ({k})" for _i, n, k in refs.fields) or "none"
    return "\n".join(
        [
            '<data source="project">',
            f"Project: {safe(refs.project.name)}",
            f"Sections: {', '.join(safe(n) for _i, n in refs.sections) or 'none'}",
            f"People: {', '.join(safe(u.name) for u in refs.people) or 'none'}",
            f"Tags: {', '.join(safe(n) for _i, n in refs.tags) or 'none'}",
            f"Custom fields: {fields}",
            f"Other projects: {', '.join(safe(n) for n in refs.others) or 'none'}",
            "</data>",
        ]
    )


def _pick(kind: str, value: str, options: list[tuple[uuid.UUID, str]]) -> tuple[uuid.UUID, str]:
    v = value.strip().lower()
    exact = [o for o in options if o[1].lower() == v]
    hits = exact or [o for o in options if v and (o[1].lower().startswith(v) or v in o[1].lower())]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        names = ", ".join(n for _i, n in hits[:5])
        raise _Ask(
            f"“{value}” could be more than one {kind} here ({names}). Which one do you mean?"
        )
    known = ", ".join(n for _i, n in options[:10]) or "none"
    raise _Ask(f"There's no {kind} called “{value}” here. The {kind}s are: {known}.")


def _person(refs: _Refs, ctx: Ctx, value: str) -> tuple[uuid.UUID, str]:
    """A person on this project, by name, first name or email (``match_person`` never guesses
    between two matches — an unmatched or ambiguous name becomes a question)."""
    if value.strip().lower() in ME and ctx.actor.id is not None:
        return ctx.actor.id, ctx.actor.name or "me"
    match = match_person(value, refs.people)
    if match is None:
        return _pick("person", value, refs.person_options)
    return match.id, match.name


def _field(refs: _Refs, value: str, *, condition: bool) -> tuple[str, str]:
    """A field reference → (stored id, display name). Task fields keep their own name."""
    v = value.strip().lower()
    if v in TASK_FIELDS:
        return TASK_FIELDS[v], TASK_FIELDS[v]
    if condition and v in CONDITION_ONLY:
        return CONDITION_ONLY[v], CONDITION_ONLY[v]
    fid, name = _pick("field", value, [(i, n) for i, n, _k in refs.fields])
    return str(fid), name


def _priority(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _resolve_trigger(
    t: DraftTrigger, refs: _Refs, ctx: Ctx
) -> tuple[dict[str, Any], dict[str, Any]]:
    spec: dict[str, Any] = {"type": t.type}
    named: dict[str, Any] = {"type": t.type}
    if t.type == "task.moved":
        if not t.section:
            raise _Ask("Which section should a task move into for the rule to run?")
        sid, name = _pick("section", t.section, refs.sections)
        spec["to_section"], named["to_section"] = str(sid), name
    elif t.type == "task.field_changed":
        if not t.field:
            raise _Ask("Which field should the rule watch for changes?")
        fid, name = _field(refs, t.field, condition=False)
        spec["field"], named["field"] = fid, name
        if t.to is not None:
            value = _priority(t.to) if fid == "priority" else t.to
            spec["to"], named["to"] = value, value
    elif t.type == "task.assigned" and t.person:
        uid, name = _person(refs, ctx, t.person)
        spec["user_id"], named["user_id"] = str(uid), name
    return spec, named


def _resolve_condition(
    c: DraftCondition, refs: _Refs, ctx: Ctx
) -> tuple[dict[str, Any], dict[str, Any]]:
    fid, display = _field(refs, c.field, condition=True)
    spec: dict[str, Any] = {"field": fid, "op": c.op}
    named: dict[str, Any] = {"field": display, "op": c.op}
    if c.op in ("empty", "not_empty"):
        return spec, named
    if c.value is None:
        raise _Ask(f"What should {display} be compared with?")
    if fid == "assignee":
        pairs = [_person(refs, ctx, str(v)) for v in _values(c.value)]
        ids: list[Any] = [str(i) for i, _n in pairs]
        labels: list[Any] = [n for _i, n in pairs]
    elif fid == "tag":
        pairs = [_pick("tag", str(v), refs.tags) for v in _values(c.value)]
        ids = [str(i) for i, _n in pairs]
        labels = [n for _i, n in pairs]
    else:
        ids = labels = [_priority(v) if fid == "priority" else v for v in _values(c.value)]
    spec["value"] = ids if c.op == "in" else ids[0]
    named["value"] = labels if c.op == "in" else labels[0]
    return spec, named


async def _resolve_action(
    a: DraftAction, refs: _Refs, ctx: Ctx, tc: ToolContext
) -> tuple[dict[str, Any], dict[str, Any]]:
    spec: dict[str, Any] = {"type": a.type}
    named: dict[str, Any] = {"type": a.type}

    def person(value: str) -> None:
        uid, name = _person(refs, ctx, value)
        spec["user_id"], named["user_id"] = str(uid), name

    async def other_project() -> None:
        if not a.project:
            raise _Ask("Which project should the task be added to or removed from?")
        try:
            target, _role = await resolve_project(tc, a.project)
        except ToolError as e:
            raise _Ask(f"I couldn't find the project “{a.project}”: {e.message}") from None
        if target.id == refs.project.id:
            raise _Ask(f"“{a.project}” is this project. Which other project do you mean?")
        spec["project_id"], named["project_id"] = str(target.id), target.name

    if a.type == "assign":
        if a.person:
            person(a.person)
        else:
            spec["user_id"] = named["user_id"] = None  # "unassign it"
    elif a.type in ("add_comment", "notify_user"):
        if not (a.text or "").strip():
            raise _Ask("What should the comment or notification say?")
        spec["text"] = named["text"] = a.text
        if a.type == "notify_user":
            if not a.person:
                raise _Ask("Who should be notified?")
            person(a.person)
    elif a.type == "move_section":
        if not a.section:
            raise _Ask("Which section should the task move to?")
        sid, name = _pick("section", a.section, refs.sections)
        spec["section_id"], named["section_id"] = str(sid), name
    elif a.type == "set_field":
        if not a.field:
            raise _Ask("Which field should be set?")
        fid, display = _field(refs, a.field, condition=False)
        if fid in ("due_on", "start_on"):
            raise _Ask(
                "A rule can only set the due date relative to when it runs "
                "(for example “due in 3 days”). How many days should it be?"
            )
        spec["field_id"], named["field_id"] = fid, display
        if a.value is None:
            raise _Ask(f"What should {display} be set to?")
        spec["value"] = named["value"] = _priority(a.value) if fid == "priority" else a.value
    elif a.type in ("add_to_project", "remove_from_project"):
        await other_project()
    elif a.type == "add_tag":
        if not a.tag:
            raise _Ask("Which tag should be added?")
        tid, name = _pick("tag", a.tag, refs.tags)
        spec["tag_id"], named["tag_id"] = str(tid), name
    elif a.type == "create_subtasks":
        titles = [t.strip() for t in a.titles or [] if t.strip()]
        if not titles:
            raise _Ask("Which subtasks should be created?")
        spec["titles"] = named["titles"] = titles
    elif a.type == "set_due_relative":
        if a.days is None:
            raise _Ask("How many days from when the rule runs should the due date be?")
        spec["days"] = named["days"] = a.days
    return spec, named


def _sentence(named: dict[str, Any]) -> str:
    """A readable sentence for the draft, e.g. "When a task moves to Review, if priority is
    high, then assign to Mei Chen and add tag Escalated." (the builder shows its own once the
    draft is loaded; this is what the API returns for the confirmation step)."""
    parts = [f"When {_trigger_words(named['trigger'])}"]
    if named["conditions"]:
        parts.append("if " + " and ".join(_condition_words(c) for c in named["conditions"]))
    parts.append("then " + " and ".join(_action_words(a) for a in named["actions"]))
    return f"{', '.join(parts)}."


def _trigger_words(t: dict[str, Any]) -> str:
    kind = t["type"]
    if kind == "task.added":
        return "a task is added to this project"
    if kind == "task.moved":
        return f"a task moves to {t['to_section']}"
    if kind == "task.field_changed":
        field = str(t["field"]).replace("_", " ")
        return f"{field} changes to {t['to']}" if "to" in t else f"{field} changes"
    if kind == "task.completed":
        return "a task is completed"
    if kind == "task.assigned":
        return f"a task is assigned to {t['user_id']}" if "user_id" in t else "a task is assigned"
    return "a task's due date is tomorrow"


def _condition_words(c: dict[str, Any]) -> str:
    labels = {
        "eq": "is",
        "neq": "is not",
        "in": "is one of",
        "gt": "is after",
        "lt": "is before",
        "empty": "is empty",
        "not_empty": "is not empty",
    }
    field = str(c["field"]).replace("_", " ")
    if c["op"] in ("empty", "not_empty"):
        return f"{field} {labels[c['op']]}"
    value = ", ".join(str(v) for v in _values(c["value"]))
    return f"{field} {labels[c['op']]} {value}"


def _action_words(a: dict[str, Any]) -> str:
    kind = a["type"]
    if kind == "assign":
        return f"assign to {a['user_id']}" if a.get("user_id") else "unassign it"
    if kind == "add_comment":
        return f"comment “{a['text']}”"
    if kind == "move_section":
        return f"move to {a['section_id']}"
    if kind == "mark_complete":
        return "mark it complete"
    if kind == "set_field":
        return f"set {str(a['field_id']).replace('_', ' ')} to {a['value']}"
    if kind == "add_to_project":
        return f"add it to {a['project_id']}"
    if kind == "remove_from_project":
        return f"remove it from {a['project_id']}"
    if kind == "add_tag":
        return f"add tag {a['tag_id']}"
    if kind == "create_subtasks":
        return "create subtasks: " + ", ".join(a["titles"])
    if kind == "set_due_relative":
        days = a["days"]
        return f"set the due date {abs(days)} day{'' if abs(days) == 1 else 's'} " + (
            "from then" if days >= 0 else "earlier"
        )
    return f"notify {a['user_id']}: “{a['text']}”"


async def compile_rule(
    session: AsyncSession, llm: LLM, ctx: Ctx, project_id: uuid.UUID, text: str
) -> CompiledRule:
    """One sentence → a validated rule draft for ``project_id``, or a question back."""
    text = text.strip()
    if not text:
        raise ValidationFailed("Describe the rule first")
    if len(text) > MAX_TEXT:
        raise ValidationFailed(f"That's too long (at most {MAX_TEXT} characters)")
    project = await authorize_manage(session, ctx, project_id)
    refs = await load_refs(session, ctx, project)
    prompt = prompts.load("nl_rule")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'{reference_block(refs)}\n<data source="request">{safe(text)}</data>',
        schema=RuleDraft,
        description="Submit the rule, or a question to ask back.",
    )
    if draft.question and not (draft.trigger and draft.actions):
        return CompiledRule(question=draft.question.strip())
    if draft.trigger is None or not draft.actions:
        return CompiledRule(
            question="I couldn't tell what should happen, or when. Can you say it as "
            "“when <something happens>, <do this>”?"
        )
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    try:
        trigger, named_trigger = _resolve_trigger(draft.trigger, refs, ctx)
        conditions = [_resolve_condition(c, refs, ctx) for c in draft.conditions]
        actions = [await _resolve_action(a, refs, ctx, tc) for a in draft.actions]
    except _Ask as ask:
        return CompiledRule(question=ask.question)
    spec = {
        "trigger": trigger,
        "conditions": [c for c, _n in conditions],
        "actions": [a for a, _n in actions],
    }
    named = {
        "trigger": named_trigger,
        "conditions": [n for _c, n in conditions],
        "actions": [n for _a, n in actions],
    }
    try:
        rule = RuleIn.model_validate(
            {
                **spec,
                "name": (draft.name.strip() or text)[:200],
                "project_id": str(project_id),
                "created_from_prompt": text[:2000],
            }
        )
    except ValidationError as e:
        detail = str(e.errors()[0].get("msg", "")).removeprefix("Value error, ")
        return CompiledRule(
            question=f"That doesn't make a valid rule ({detail}). Can you rephrase it?"
        )
    return CompiledRule(rule=rule, named=named, sentence=_sentence(named))
