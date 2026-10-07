"""Phase 7.5 (spec §8): the readiness check for moving a project into a gated stage.

The checklist is the deterministic gate (``lifecycle.check_readiness``: required fields,
milestones and files, met or missing). Only when the person ticks "also read files" does Mo read
the gate's files that are there (``file_digest``: outline, start, passages about signing and
dates) and add a note per file ("the signed contract has no signature date"). A note is kept only
if it cites a file from the facts and every number in it is in the facts. Without the tick, or
with no files to read, there is no model call. Nothing is stored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.file_digest import file_digest
from momentum.ai.grounding import data_block, grounded, match_cites, numbers_in
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.domain.portfolios import lifecycle
from momentum.domain.portfolios.gates import Readiness
from momentum.domain.projects.models import Project

MAX_FILES = 4
WORDS = ("signed", "signature", "sign", "date", "approved", "agreed")


class ReadinessNoteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(max_length=200, description="The checklist item the note is about")
    text: str = Field(min_length=1, max_length=400)
    concern: bool = Field(default=False, description="True if the file may not meet the gate")
    cites: list[str] = Field(default_factory=list, max_length=6)


class ReadinessNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: list[ReadinessNoteDraft] = Field(default_factory=list, max_length=MAX_FILES * 2)


@dataclass
class ReadinessNote:
    item: str
    text: str
    concern: bool
    cites: list[str]


@dataclass
class ReadinessCheck:
    readiness: Readiness
    project: str
    notes: list[ReadinessNote] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    ai: bool = False


def keep(out: ReadinessNotes, facts: dict[str, Any]) -> list[ReadinessNote]:
    allowed = [f["file"] for f in facts["files"]] + [i["label"] for i in facts["checklist"]]
    known = numbers_in(facts)
    kept: list[ReadinessNote] = []
    for n in out.notes:
        text = " ".join(n.text.split())
        cites = match_cites(n.cites, allowed)
        if not any(c in allowed[: len(facts["files"])] for c in cites):
            continue  # a note must be about a file Mo read
        if not grounded(text, known):
            continue
        kept.append(ReadinessNote(n.item.strip(), text, n.concern, cites))
    return kept


async def check(
    session: AsyncSession,
    llm: LLM | None,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    to: str,
    *,
    read_files: bool = False,
) -> ReadinessCheck:
    r = await lifecycle.check_readiness(session, ctx, portfolio_id, project_id, to)
    project = await session.get(Project, project_id)
    assert project is not None
    out = ReadinessCheck(r, project.name)
    if not read_files:
        return out
    digests: list[dict[str, Any]] = []
    for item in r.items:
        if item.kind != "file" or not item.met or not item.ref or len(digests) >= MAX_FILES:
            continue
        try:
            d = await file_digest(
                session,
                ctx,
                uuid.UUID(str(item.ref["id"])),
                words=(*WORDS, item.label.replace("*", "").strip()),
            )
        except NotFound:
            continue
        d["for_item"] = item.label
        if d.get("unreadable") or d.get("scanned"):
            out.unreadable.append(d["file"])
        digests.append(d)
    out.files_read = [d["file"] for d in digests]
    readable = [d for d in digests if not d.get("unreadable")]
    if not readable or llm is None:
        return out
    facts = {
        "project": project.name,
        "stage": r.stage_label,
        "checklist": [{"kind": i.kind, "label": i.label, "met": i.met} for i in r.items],
        "files": readable,
    }
    prompt = prompts.load("readiness")
    notes = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=data_block(
            "gate_files",
            facts,
            [d["file"] for d in readable] + [i.label for i in r.items],
            stage=r.stage_label,
        ),
        schema=ReadinessNotes,
        description="Submit the notes on the gate's files.",
    )
    out.notes = keep(notes, facts)
    out.ai = True
    return out
