"""Phase 7.5 (spec §9.4): project close-out. The close-out report itself is the reports engine's
``closeout`` kind (S75-09); this module turns the same facts (and Mo's cited narrative, prompt
``report_narrative/v1`` with the close-out parts) into the project's final **status update**
draft, previewed and posted only after the person confirms. Nothing is stored here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.report_narrative import citables, narrate
from momentum.core.context import Ctx
from momentum.domain.access import get_visible_project
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.reports.document import Paragraph
from momentum.reports.generate import build
from momentum.reports.spec import ReportSpec


@dataclass
class CloseoutDraft:
    project_id: uuid.UUID
    project: str
    status_update: StatusUpdateIn
    paragraphs: list[Paragraph] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def citable(self) -> list[str]:
        return citables(self.facts)


def plain_summary(facts: dict[str, Any]) -> str:
    """The facts in one sentence, when Mo isn't there to write the summary."""
    parts: list[str] = []
    if facts.get("actual_days") is not None and facts.get("planned_days") is not None:
        parts.append(f"Took {facts['actual_days']} days against a plan of {facts['planned_days']}")
    scope = facts.get("scope") or {}
    if scope.get("total"):
        parts.append(f"{scope['total']} tasks, {scope.get('added', 0)} added after the start")
    slips = facts.get("milestone_slips") or []
    if slips:
        parts.append(f"{len(slips)} milestones finished late")
    return (". ".join(parts) + ".") if parts else "Close-out of the project."


def status_from(facts: dict[str, Any], paragraphs: list[Paragraph]) -> StatusUpdateIn:
    slipped = [
        StatusItem(text=f"{s['name']} finished {s['days_late']} days late")
        for s in facts.get("milestone_slips") or []
    ][:10]
    blockers = [
        StatusItem(text=f"{b['key']} {b['title']} held up {b['held_up']} tasks")
        for b in facts.get("blockers") or []
    ][:5]
    completed: list[StatusItem] = []
    if facts.get("actual_finish"):
        completed.append(StatusItem(text=f"Finished on {facts['actual_finish']}"))
    summary = "\n\n".join(p.text for p in paragraphs) or plain_summary(facts)
    return StatusUpdateIn(
        status="complete",
        title=f"Close-out: {facts['project']}"[:200],
        summary=summary[:4000],
        sections=StatusSections(completed=completed, slipped=slipped, blockers=blockers),
        generated_by_ai=bool(paragraphs),
    )


async def closeout_status(
    session: AsyncSession, llm: LLM | None, ctx: Ctx, project_id: uuid.UUID
) -> CloseoutDraft:
    """The close-out facts as the person, Mo's cited summary (when a gateway is there), and the
    status update they would post."""
    project, _ = await get_visible_project(session, ctx, project_id)
    spec = ReportSpec.model_validate(
        {"kind": "closeout", "scope": {"project_id": str(project.id)}, "format": "docx"}
    )
    doc = await build(session, ctx, spec)
    paragraphs: list[Paragraph] = []
    if llm is not None and ctx.settings.ai_enabled:
        try:
            paragraphs = await narrate(llm, ctx, "closeout", doc.facts)
        except AIUnavailable:
            paragraphs = []  # the facts-only draft still stands
    return CloseoutDraft(
        project.id, project.name, status_from(doc.facts, paragraphs), paragraphs, doc.facts
    )
