"""S3.2.1 smart quick-add, the AI half: when the browser's local parser (``@person #project
!priority``, dates, "every …") leaves text that still looks structured ("for Ana by end of next
week"), the ``fast`` alias extracts the fields, and the server resolves names to people and
projects the user can see. Nothing is created here: the client shows the result for the user to
accept, and creates the task through the normal endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_person, resolve_project
from momentum.core.context import Ctx
from momentum.domain.access import ROLE_RANK

Priority = Literal["urgent", "high", "medium", "low"]


class RecurrenceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    freq: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=99)
    by_weekday: list[int] | None = Field(default=None, description="0 = Monday … 6 = Sunday")
    workdays_only: bool = False


class Extraction(BaseModel):
    """What the model submits (names as written; the server resolves them)."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    assignee: str | None = Field(default=None, max_length=200)
    project: str | None = Field(default=None, max_length=200)
    due_on: date | None = None
    priority: Priority | None = None
    recurrence: RecurrenceRule | None = None


class Named(BaseModel):
    id: uuid.UUID
    name: str


class QuickAddParseOut(BaseModel):
    title: str
    assignee: Named | None = None
    project: Named | None = None
    due_on: date | None = None
    priority: Priority | None = None
    recurrence: RecurrenceRule | None = None
    unresolved: list[str] = Field(
        default_factory=list, description="Names Mo read but couldn't match, for the user to fix"
    )


async def parse(
    session: AsyncSession, llm: LLM, ctx: Ctx, text: str, *, now: datetime
) -> QuickAddParseOut:
    prompt = prompts.load("quick_add")
    local = now.astimezone(ZoneInfo(ctx.actor.timezone))
    system = prompt.render(
        today=local.date().isoformat(), weekday=local.strftime("%A"), tz=ctx.actor.timezone
    )
    out = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=system,
        user=f'<data source="quick_add">{safe(text)}</data>',
        schema=Extraction,
        description="Submit the task fields read from the text.",
    )
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    result = QuickAddParseOut(
        title=" ".join(out.title.split()),
        due_on=out.due_on,
        priority=out.priority,
        recurrence=out.recurrence,
    )
    if out.assignee:
        try:
            person = await resolve_person(tc, out.assignee)
            result.assignee = Named(id=person.id, name=person.name)
        except ToolError as e:
            result.unresolved.append(f"Person “{out.assignee}”: {e.message}")
    if out.project:
        try:
            project, role = await resolve_project(tc, out.project)
            if ROLE_RANK[role] >= ROLE_RANK["editor"]:
                result.project = Named(id=project.id, name=project.name)
            else:
                result.unresolved.append(f"Project “{project.name}”: you can't add tasks there")
        except ToolError as e:
            result.unresolved.append(f"Project “{out.project}”: {e.message}")
    return result
