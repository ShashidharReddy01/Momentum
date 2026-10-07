"""Phase 7.5 (spec §6.1): the report narrative. The builder's facts (numbers, keys, names) go to the
``default`` alias as data; the model returns paragraphs with what each cites. A paragraph is kept
only if it cites a task key or a name that is really in the facts; every kept paragraph is marked
``ai=True`` (renderers label it "AI-drafted, review before sending")."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.core.settings import Settings
from momentum.reports.document import Paragraph
from momentum.reports.narrative import NARRATIVE_PARTS, Narrator

KEY = re.compile(r"\bT-\d+\b")
NAME_FIELDS = ("name", "title", "project", "portfolio", "stage", "widget")
Part = Literal["summary", "highlights", "risks", "next_steps", "went_well", "slipped", "lessons"]


class NarrativeParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part: Part
    text: str = Field(min_length=1, max_length=900)
    cites: list[str] = Field(default_factory=list, max_length=12)


class Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraphs: list[NarrativeParagraph] = Field(default_factory=list, max_length=8)


def citables(facts: Any) -> list[str]:
    """Every task key and name in the facts (what a paragraph may cite), in order."""
    out: list[str] = []

    def walk(v: Any, key: str = "") -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and (KEY.fullmatch(v) or key in NAME_FIELDS or key == "at_risk"):
            out.append(v)

    walk(facts)
    return list(dict.fromkeys(x for x in out if x.strip()))


def facts_text(kind: str, facts: dict[str, Any]) -> str:
    parts = NARRATIVE_PARTS.get(kind, ("summary",))
    return "\n".join(
        [
            f"Report: {kind.replace('_', ' ')}. Parts to write, in order: {', '.join(parts)}.",
            f'<data source="report_facts" kind="{kind}">',
            safe(json.dumps(facts, ensure_ascii=False, default=str, indent=1)),
            "</data>",
            "Citable: " + " | ".join(safe(c) for c in citables(facts)[:60]),
        ]
    )


def keep(out: Narrative, kind: str, facts: dict[str, Any]) -> list[Paragraph]:
    """The paragraphs that cite something real, for parts this kind has, once each."""
    allowed = {c.lower(): c for c in citables(facts)}
    parts = NARRATIVE_PARTS.get(kind, ("summary",))
    seen: set[str] = set()
    kept: list[Paragraph] = []
    for p in out.paragraphs:
        if p.part not in parts or p.part in seen:
            continue
        cites: list[str] = []
        for raw in p.cites:
            for piece in [*KEY.findall(raw), *(x.strip() for x in raw.split("|"))]:
                hit = allowed.get(piece.strip("[] ").lower())
                if hit and hit not in cites:
                    cites.append(hit)
        if not cites:
            continue
        seen.add(p.part)
        kept.append(Paragraph(text=p.text.strip(), ai=True, cites=cites))
    return kept


async def narrate(llm: LLM, ctx: Ctx, kind: str, facts: dict[str, Any]) -> list[Paragraph]:
    prompt = prompts.load("report_narrative")
    out = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=facts_text(kind, facts),
        schema=Narrative,
        description="Submit the report's narrative paragraphs.",
    )
    return keep(out, kind, facts)


def make_narrator(llm: LLM, settings: Settings) -> Narrator:
    async def narrator(ctx: Ctx, kind: str, facts: dict[str, Any]) -> list[Paragraph]:
        if not settings.ai_enabled:
            return []
        return await narrate(llm, ctx, kind, facts)

    return narrator
