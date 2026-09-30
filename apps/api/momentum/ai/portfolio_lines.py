"""S6.2.2: one line per project in a portfolio table (the ✦ column), from facts computed in code.

The model sees only the numbers the table already shows (status, done/total, overdue, due date,
the latest update's title) and writes a sentence per project. A line is kept only if every number
in it appears in that project's facts; otherwise, and for any project the model skipped or when
the gateway is down, the line is the plain facts sentence built here. So a line can be terse, but
never invents a figure. Nothing is stored.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.domain.status_updates.service import STATUS_LABELS

NUMBER = re.compile(r"\d+")
MAX_PROJECTS = 40


@dataclass
class ProjectFacts:
    id: uuid.UUID
    name: str
    status: str | None
    total: int
    done: int
    overdue: int
    due_on: date | None
    latest_update: str | None

    def sentence(self, today: date) -> str:
        """The plain line: what the table knows, in words."""
        if not self.total:
            parts = ["No tasks yet"]
        else:
            parts = [f"{round(100 * self.done / self.total)}% done ({self.done} of {self.total})"]
            if self.overdue:
                parts.append(f"{self.overdue} overdue")
        if self.due_on:
            days = (self.due_on - today).days
            parts.append(
                f"due {self.due_on.isoformat()}"
                + (f", {-days} days late" if days < 0 else f", {days} days left")
            )
        if not self.status:
            parts.append("no status yet")
        return "; ".join(parts)

    def facts(self, today: date) -> str:
        status = STATUS_LABELS.get(self.status or "", "no status yet")
        latest = f'; latest update: "{safe(self.latest_update)}"' if self.latest_update else ""
        return f"{status}; {self.sentence(today)}{latest}"


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=200)


class Lines(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[Line] = Field(default_factory=list, max_length=MAX_PROJECTS)


@dataclass
class ProjectLine:
    project_id: uuid.UUID
    text: str
    ai: bool


def _grounded(text: str, facts: str) -> bool:
    known = set(NUMBER.findall(facts))
    return all(n in known for n in NUMBER.findall(text))


async def lines_for(
    llm: LLM | None, ctx: Ctx, projects: list[ProjectFacts], today: date
) -> list[ProjectLine]:
    projects = projects[:MAX_PROJECTS]
    plain = {p.id: p.sentence(today) for p in projects}
    written: dict[uuid.UUID, str] = {}
    if llm is not None and projects:
        prompt = prompts.load("portfolio_lines")
        facts = "\n".join(f"{i}. {p.facts(today)}" for i, p in enumerate(projects, 1))
        try:
            out = await extract(
                llm,
                ctx,
                prompt=prompt,
                system=prompt.body,
                user=f'<data source="portfolio_projects">\n{facts}\n</data>',
                schema=Lines,
                description="Submit one line per project.",
            )
        except AIUnavailable:
            out = Lines()
        for line in out.lines:
            if 1 <= line.project <= len(projects):
                p = projects[line.project - 1]
                text = " ".join(line.text.split())[:160]
                if text and _grounded(text, p.facts(today)):
                    written[p.id] = text
    return [ProjectLine(p.id, written.get(p.id, plain[p.id]), p.id in written) for p in projects]
