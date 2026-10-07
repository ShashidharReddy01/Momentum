"""Phase 7.5 (spec §8): the portfolio brief ("Brief me").

The facts are computed in code as the viewer (``portfolio_facts``: the table's rows and the stage
metrics, sorted into slipping, over stage target, the bottleneck, waiting on the customer vs on
us, and decisions needed); the ``default`` alias words them. An item is kept only if it cites a
project or stage from the facts and every number in it is in the facts; the headline falls back
to a plain sentence built here. Nothing is stored: "Post as status update" goes through the
normal preview and confirm, as a portfolio status update marked as Mo's draft.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.grounding import data_block, grounded, match_cites, numbers_in
from momentum.ai.llm import LLM
from momentum.ai.portfolio_facts import brief_facts, row_facts, stage_facts
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.domain.portfolios.service import get_portfolio
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.reports.data import today_for

Kind = Literal["slipping", "bottleneck", "sla", "waiting_customer", "waiting_us", "decision"]
KINDS: tuple[str, ...] = Kind.__args__  # type: ignore[attr-defined]


class BriefItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    text: str = Field(min_length=1, max_length=400)
    cites: list[str] = Field(default_factory=list, max_length=10)


class BriefDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(default="", max_length=240)
    items: list[BriefItemDraft] = Field(default_factory=list, max_length=10)


@dataclass
class BriefItem:
    kind: str
    text: str
    cites: list[str]
    project_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class Brief:
    portfolio_id: uuid.UUID
    portfolio: str
    headline: str
    items: list[BriefItem]
    facts: dict[str, Any]
    hidden: int
    status: str
    ai: bool  # False when there was nothing to brief on (no model call)

    def status_update(self, today: date) -> StatusUpdateIn:
        """The brief as a portfolio status update, for the preview the user confirms."""

        def items(*kinds: str) -> list[StatusItem]:
            return [StatusItem(text=i.text[:500]) for i in self.items if i.kind in kinds]

        return StatusUpdateIn(
            status=self.status,
            title=f"Portfolio brief, {today.strftime('%d %b %Y')}",
            summary=self.headline[:4000],
            sections=StatusSections(
                slipped=items("slipping", "sla", "bottleneck"),
                blockers=items("waiting_customer", "waiting_us"),
                next=items("decision"),
            ),
            generated_by_ai=self.ai,
        )


def citables(facts: dict[str, Any]) -> list[str]:
    """Project and stage names the brief may cite."""
    out: list[str] = [facts["portfolio"]]
    for key in ("slipping", "over_stage_target", "waiting_on_customer", "waiting_on_us"):
        for r in facts.get(key) or []:
            out.append(r["name"])
            if r.get("stage"):
                out.append(r["stage"])
    for r in facts.get("decisions_needed") or []:
        out.append(r["name"])
    if facts.get("bottleneck"):
        out.append(facts["bottleneck"]["stage"])
    for s in facts.get("funnel") or []:
        out.append(s["stage"])
    return list(dict.fromkeys(x for x in out if x))


def plain_headline(facts: dict[str, Any]) -> str:
    parts = [f"{facts['projects_shown']} projects"]
    for key, words in (
        ("slipping", "slipping"),
        ("over_stage_target", "over their stage target"),
        ("waiting_on_customer", "waiting on the customer"),
    ):
        if facts.get(key):
            parts.append(f"{len(facts[key])} {words}")
    return ", ".join(parts) + "."


def suggested_status(rows: list[dict[str, Any]], facts: dict[str, Any]) -> str:
    healths = {r.get("health") for r in rows}
    if "Off track" in healths:
        return "off_track"
    if "At risk" in healths or facts.get("slipping") or facts.get("over_stage_target"):
        return "at_risk"
    return "on_track"


def keep(draft: BriefDraft, facts: dict[str, Any]) -> tuple[str, list[BriefItem]]:
    """The headline and the items Mo can back (one cite at least; numbers from the facts)."""
    allowed = citables(facts)
    known = numbers_in(facts)
    items: list[BriefItem] = []
    for d in draft.items:
        text = " ".join(d.text.split())
        cites = match_cites(d.cites, allowed)
        if not cites or not grounded(text, known):
            continue
        items.append(BriefItem(kind=d.kind, text=text, cites=cites))
    headline = " ".join(draft.headline.split())
    if not headline or not grounded(headline, known):
        headline = plain_headline(facts)
    return headline, items


async def brief(session: AsyncSession, llm: LLM, ctx: Ctx, portfolio_id: uuid.UUID) -> Brief:
    p = await get_portfolio(session, ctx, portfolio_id)
    today = today_for(ctx)
    rows, hidden, raw = await row_facts(session, ctx, p, today=today)
    stages = await stage_facts(session, ctx, p)
    facts = brief_facts(p, rows, hidden, stages, today)
    status = suggested_status(rows, facts)
    if not rows:  # nothing the viewer can see: no model call
        return Brief(
            p.id, p.name, "No projects here that you can see.", [], facts, hidden, status, False
        )
    prompt = prompts.load("portfolio_brief")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=data_block("portfolio_facts", facts, citables(facts), portfolio=p.name),
        schema=BriefDraft,
        description="Submit the portfolio brief.",
    )
    headline, items = keep(draft, facts)
    ids = {r["name"]: r["id"] for r in raw}
    for i in items:
        i.project_ids = [ids[c] for c in i.cites if c in ids]
    return Brief(p.id, p.name, headline, items, facts, hidden, status, True)
