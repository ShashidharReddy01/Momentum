"""Phase 7.5 (spec §8): the handoff note, offered after a stage change ("Draft handoff to
Implementation"), never written on its own.

The facts are read as the person: the project brief, its project fields, milestones, open work
(overdue, blocked, waiting on the customer), recent comments, the people on it and, only when
"also read files" is ticked, a digest of the project's latest files. Mo writes the handoff in
sections (what was sold, scope and out of scope, commitments and dates, contacts, open risks,
what's waiting on whom); an item is kept only if it cites a task, milestone, field, person or
file from the facts and every number in it is in the facts. Nothing is stored: the preview is
posted as a project status update (marked as Mo's draft) after the person confirms.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.file_digest import file_digest
from momentum.ai.grounding import data_block, grounded, match_cites, numbers_in
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext
from momentum.ai.tools.fields import project_fields_view
from momentum.ai.visibility import visible_task_ids
from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.projects.service import project_members
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User
from momentum.reports.data import blockers as blocking_counts
from momentum.reports.data import project_tasks, today_for, waiting_on_customer

SECTIONS = ("sold", "scope", "out_of_scope", "commitments", "contacts", "risks", "waiting")
SECTION_TITLES = {
    "sold": "What was sold",
    "scope": "Scope",
    "out_of_scope": "Out of scope",
    "commitments": "Commitments and dates",
    "contacts": "Contacts",
    "risks": "Open risks",
    "waiting": "Waiting on",
}
MAX_COMMENTS = 12
MAX_FILES = 3
BRIEF_CHARS = 1500


class HandoffItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=400)
    cites: list[str] = Field(default_factory=list, max_length=8)


class HandoffDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sold: list[HandoffItemDraft] = Field(default_factory=list, max_length=6)
    scope: list[HandoffItemDraft] = Field(default_factory=list, max_length=8)
    out_of_scope: list[HandoffItemDraft] = Field(default_factory=list, max_length=6)
    commitments: list[HandoffItemDraft] = Field(default_factory=list, max_length=8)
    contacts: list[HandoffItemDraft] = Field(default_factory=list, max_length=6)
    risks: list[HandoffItemDraft] = Field(default_factory=list, max_length=6)
    waiting: list[HandoffItemDraft] = Field(default_factory=list, max_length=6)


@dataclass
class HandoffItem:
    text: str
    cites: list[str]


@dataclass
class Handoff:
    project_id: uuid.UUID
    project: str
    to_stage: str | None
    sections: dict[str, list[HandoffItem]] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    files_read: list[str] = field(default_factory=list)
    status: str = "on_track"

    def text(self) -> str:
        lines: list[str] = []
        for key in SECTIONS:
            items = self.sections.get(key) or []
            if items:
                lines.append(f"{SECTION_TITLES[key]}:")
                lines += [f"- {i.text}" for i in items]
        return "\n".join(lines)

    def status_update(self) -> StatusUpdateIn:
        """The note as a project status update, for the preview the person confirms."""
        summary_keys = ("sold", "scope", "out_of_scope", "contacts")
        summary: list[str] = []
        for key in summary_keys:
            got = self.sections.get(key) or []
            if got:
                summary.append(f"{SECTION_TITLES[key]}: " + " ".join(i.text for i in got))
        to = f" to {self.to_stage}" if self.to_stage else ""

        def items(*keys: str) -> list[StatusItem]:
            return [StatusItem(text=i.text[:500]) for k in keys for i in self.sections.get(k) or []]

        return StatusUpdateIn(
            status=self.status,
            title=f"Handoff{to}: {self.project}"[:200],
            summary="\n\n".join(summary)[:4000],
            sections=StatusSections(blockers=items("risks", "waiting"), next=items("commitments")),
            generated_by_ai=True,
        )


def citables(facts: dict[str, Any]) -> list[str]:
    out: list[str] = [facts["project"]]
    for f in facts.get("fields") or []:
        out.append(f["field"])
    for m in facts.get("milestones") or []:
        out.append(m["title"])
    for key in ("overdue", "blocked", "waiting_on_customer", "open"):
        for t in facts.get(key) or []:
            out += [t["key"], t["title"]]
    for c in facts.get("recent_comments") or []:
        out.append(c["task"])
    for p in facts.get("people") or []:
        out.append(p["name"])
    for d in facts.get("files") or []:
        out.append(d["file"])
    return list(dict.fromkeys(x for x in out if x))


def keep(draft: HandoffDraft, facts: dict[str, Any]) -> dict[str, list[HandoffItem]]:
    allowed = citables(facts)
    known = numbers_in(facts)
    out: dict[str, list[HandoffItem]] = {}
    for key in SECTIONS:
        kept = []
        for item in getattr(draft, key):
            text = " ".join(item.text.split())
            cites = match_cites(item.cites, allowed)
            if cites and grounded(text, known):
                kept.append(HandoffItem(text, cites))
        if kept:
            out[key] = kept
    return out


def _task(t: Any, today: date) -> dict[str, Any]:
    out = {"key": t.key, "title": t.title}
    if t.assignee:
        out["assignee"] = t.assignee
    if t.due_on:
        out["due_on"] = t.due_on.isoformat()
    return out


async def gather(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    to_stage: str | None = None,
    read_files: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """The handoff's facts as the person (and the files read)."""
    project, _role = await get_visible_project(session, ctx, project_id)
    today = today_for(ctx)
    tasks = await project_tasks(session, [project.id], {project.id: project.name})
    ids = [t.id for t in tasks]
    waiting = await waiting_on_customer(session, ctx, ids)
    open_ids = [t.id for t in tasks if not t.done]
    blocked_by = await blocking_counts(session, open_ids)
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    fields = [
        {"field": f["name"], "value": f["value"]}
        for f in await project_fields_view(tc, project.id)
        if f.get("value") not in (None, "", [])
    ]
    owner = await session.get(User, project.owner_id) if project.owner_id else None
    people = [
        {"name": u.name, "role": role} for u, role in await project_members(session, project.id)
    ]
    if owner is not None and owner.name not in {p["name"] for p in people}:
        people.insert(0, {"name": owner.name, "role": "owner"})
    facts: dict[str, Any] = {
        "project": project.name,
        "owner": owner.name if owner else None,
        "to_stage": to_stage,
        "due_on": project.due_on.isoformat() if project.due_on else None,
        "brief": (project.brief_text or "")[:BRIEF_CHARS] or None,
        "fields": fields,
        "milestones": [
            {
                "title": t.title,
                "due_on": t.due_on.isoformat() if t.due_on else None,
                "done": t.done,
            }
            for t in tasks
            if t.type == "milestone"
        ][:20],
        "overdue": [_task(t, today) for t in tasks if t.overdue(today)][:10],
        "waiting_on_customer": [_task(t, today) for t in tasks if t.id in waiting][:10],
        "blocked": [_task(t, today) for t in tasks if not t.done and t.id in blocked_by][:10],
        "open": [_task(t, today) for t in tasks if not t.done and t.type != "milestone"][:15],
        "people": people[:15],
    }
    comments = (
        await session.execute(
            select(Comment.body_text, Comment.created_at, Task.number, User.name)
            .join(Task, Task.id == Comment.task_id)
            .outerjoin(User, User.id == Comment.author_id)
            .where(
                Comment.task_id.in_(ids or [uuid.uuid4()]),
                Comment.task_id.in_(visible_task_ids(ctx)),
                Comment.deleted_at.is_(None),
            )
            .order_by(Comment.created_at.desc())
            .limit(MAX_COMMENTS)
        )
    ).all()
    facts["recent_comments"] = [
        {
            "task": task_key(num),
            "by": name or "someone",
            "on": at.date().isoformat(),
            "text": " ".join((body or "").split())[:240],
        }
        for body, at, num, name in comments
    ]
    files_read: list[str] = []
    if read_files:
        recent = (
            await session.execute(
                select(Attachment.id)
                .where(
                    Attachment.project_id == project.id,
                    Attachment.deleted_at.is_(None),
                    Attachment.is_current.is_(True),
                )
                .order_by(Attachment.created_at.desc())
                .limit(MAX_FILES)
            )
        ).scalars()
        digests = []
        for aid in recent:
            try:
                d = await file_digest(session, ctx, aid, words=("scope", "deliver", "out of scope"))
            except NotFound:
                continue
            if not d.get("unreadable"):
                digests.append(d)
            files_read.append(d["file"])
        facts["files"] = digests
    return {k: v for k, v in facts.items() if v not in (None, [])}, files_read


async def draft_handoff(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    to_stage: str | None = None,
    read_files: bool = False,
) -> Handoff:
    facts, files_read = await gather(
        session, ctx, project_id, to_stage=to_stage, read_files=read_files
    )
    project, _ = await get_visible_project(session, ctx, project_id)
    prompt = prompts.load("handoff")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=data_block(
            "project_facts", facts, citables(facts), project=project.name, to=to_stage or ""
        ),
        schema=HandoffDraft,
        description="Submit the handoff note.",
    )
    return Handoff(
        project_id=project.id,
        project=project.name,
        to_stage=to_stage,
        sections=keep(draft, facts),
        facts=facts,
        files_read=files_read,
        status=project.status
        if project.status in ("on_track", "at_risk", "off_track")
        else "on_track",
    )
