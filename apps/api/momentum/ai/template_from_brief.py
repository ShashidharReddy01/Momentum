"""S4.3.3 "Template from description": describe a repeatable process in a sentence or two, get a
draft project template back to preview, then save it. Unlike NL → rule (S4.1.4) or Project from
brief (S3.4.6), there's no reference-resolution step: a template's tasks already point at role
*placeholders*, not real ids (`domain/templates/service.py`'s `save_project_template` does the
same for a captured project), so the model's own names go straight into the stored payload —
nothing here reads or writes the database, and nothing is created until the caller explicitly
saves the draft through ``domain.templates.service.save_template_payload``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed

MAX_BRIEF = 1000
Priority = Literal["urgent", "high", "medium", "low"]


class DraftTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    due_in_days: int | None = Field(default=None, ge=0, le=365)
    role: str | None = Field(default=None, max_length=100)
    subtasks: list[str] = Field(default_factory=list, max_length=10)
    # S6.1.3: titles of other tasks in this template that must be done before this one starts
    after: list[str] = Field(default_factory=list, max_length=5)


class DraftSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    tasks: list[DraftTask] = Field(default_factory=list, max_length=20)


class TemplateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[DraftSection] = Field(min_length=1, max_length=15)


async def draft_template(llm: LLM, ctx: Ctx, brief: str) -> TemplateDraft:
    brief = brief.strip()
    if not brief:
        raise ValidationFailed("Describe the process first")
    if len(brief) > MAX_BRIEF:
        raise ValidationFailed(f"That's too long (at most {MAX_BRIEF} characters)")
    prompt = prompts.load("template_from_brief")
    return await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'<data source="request">{safe(brief)}</data>',
        schema=TemplateDraft,
        description="Submit the draft template.",
    )


def _empty_task(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": None,
        "priority": None,
        "due_offset_days": None,
        "start_offset_days": None,
        "role_id": None,
        "field_values": {},
        "subtasks": [],
    }


def to_payload(draft: TemplateDraft) -> dict[str, Any]:
    """The draft (role *names*) → the stored payload shape (role *ids*) that
    ``domain.templates.service`` understands — the same shape a captured project's template has,
    minus fields and rules (an AI-authored template starts with neither)."""
    roles: dict[str, str] = {}

    def role_id(label: str | None) -> str | None:
        if not label or not label.strip():
            return None
        key = label.strip()
        if key not in roles:
            roles[key] = f"r{len(roles) + 1}"
        return roles[key]

    sections = []
    position = {
        t.title[:500].strip().lower(): [si, ti]
        for si, s in enumerate(draft.sections)
        for ti, t in enumerate(s.tasks)
    }
    dependencies = []
    for si, s in enumerate(draft.sections):
        for ti, t in enumerate(s.tasks):
            for title in t.after:
                blocker = position.get(title.strip().lower())
                # a title the model made up, or the task itself, is dropped rather than guessed
                if blocker is not None and blocker != [si, ti]:
                    dependencies.append({"task": [si, ti], "blocked_by": blocker})
    for s in draft.sections:
        tasks = []
        for t in s.tasks:
            task = _empty_task(t.title[:500])
            task["description"] = t.description
            task["priority"] = t.priority
            task["due_offset_days"] = t.due_in_days
            task["role_id"] = role_id(t.role)
            task["subtasks"] = [_empty_task(st) for st in t.subtasks if st.strip()]
            tasks.append(task)
        sections.append({"name": s.name, "tasks": tasks})

    return {
        "roles": [{"id": rid, "label": label} for label, rid in roles.items()],
        "fields": [],
        "sections": sections,
        "rules": [],
        "dependencies": dependencies,
    }
