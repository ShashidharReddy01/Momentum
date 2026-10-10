"""Phase 7.6 S76-07 (spec §12.1, §12.2): the agents directory and an agent's profile.

The profile is what a person needs before handing an agent work: its title and charter, its
capabilities with examples, what it may do (its declared effects, in plain English), what wakes
it and how to hand it work. Pack agents take all of it from their manifest; other agents show
what they have (description, triggers) and nothing is made up for the rest.

Directory search reads like a question ("who can read invoices?"): the filler words are dropped
and every remaining word must appear somewhere in the agent's name, title, description or
capabilities.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents import health
from momentum.agents.packs.manifest import PackManifest
from momentum.core.context import Ctx
from momentum.domain.agents.models import Agent

DataClass = Literal["public", "internal", "financial", "personal"]

_FILLER = frozenset(
    {
        *("a", "an", "and", "any", "are", "can", "could", "do", "does", "for", "from", "help"),
        *("i", "is", "it", "me", "my", "of", "on", "or", "our", "some", "someone", "that"),
        *("the", "this", "to", "us", "we", "what", "which", "who", "whom", "will", "with"),
        *("would", "agent", "agents"),
    }
)

EFFECT_TEXT: dict[str, str] = {
    "tasks.create_subtask": "add subtasks to the task it's working on",
    "tasks.set_fields": "fill in the task's custom fields",
    "tasks.rename": "rename the task it's working on",
    "tasks.move_to_review": "move the task to a review section",
    "tasks.request_approval": "ask someone to approve the task",
    "tasks.complete_own": "mark its own subtasks done",
    "attachments.create": "attach files it produces to the task",
    "comments.create": "comment on the task",
    "records.create": "create {types} records",
    "records.update": "update {types} records",
    "entities.create": "add new {types} entries",
    "entities.update": "update {types} entries",
    "skills.propose": "propose new skills ({types}) for a steward to review",
}

TRIGGER_TEXT: dict[str, str] = {
    "assigned": "When a task is assigned to it",
    "mentioned": "When someone @mentions it",
    "manual": "When someone runs it by hand",
    "plan_step": "As a step in another agent's plan",
}


class CapabilityOut(BaseModel):
    key: str
    title: str
    description: str
    examples: list[str]
    files: list[str]
    typical_duration_s: int | None


class HealthSummaryOut(BaseModel):
    jobs: int
    items: int
    success_rate: float | None


class ProfileOut(BaseModel):
    agent_id: uuid.UUID
    is_pack: bool
    title: str | None
    charter: str
    capabilities: list[CapabilityOut]
    effects: list[str]
    triggers: list[str]
    data_class: DataClass | None
    personal_data: str | None
    reads_external_content: bool
    has_settings: bool
    can_assign: bool
    can_mention: bool
    can_run: bool


class DirectoryCardOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    key: str
    name: str
    avatar: str
    description: str
    enabled: bool
    source: str
    title: str | None
    capabilities: list[CapabilityOut]
    data_class: DataClass | None
    health: HealthSummaryOut | None


def _manifest(agent: Agent, packs: Any) -> PackManifest | None:
    pack = (getattr(packs, "packs", None) or {}).get(agent.pack_key) if agent.pack_key else None
    return pack.manifest if pack is not None else None


def _labels(packs: Any, pack_key: str, kind: str, keys: list[str]) -> str:
    pack = (getattr(packs, "packs", None) or {}).get(pack_key)
    out = []
    for key in keys:
        label = key.replace("_", " ")
        types = (pack.record_types if kind == "records" else pack.entity_types) if pack else ()
        label = next((t.label for t in types if t.key == key), label)
        out.append(label.lower())
    return ", ".join(out)


def effect_sentences(manifest: PackManifest, packs: Any) -> list[str]:
    """Each declared effect as the end of "When you hand <name> work, they may…"."""
    out = []
    for item in manifest.effects:
        if isinstance(item, str):
            out.append(EFFECT_TEXT.get(item, item))
            continue
        ((name, types),) = item.items()
        kind = name.split(".")[0]
        if kind in ("records", "entities"):
            text = _labels(packs, manifest.key, kind, types)
        else:
            text = ", ".join(t.replace("_", " ") for t in types)
        out.append(EFFECT_TEXT.get(name, name).format(types=text))
    return out


def _trigger_sentence(t: dict[str, Any]) -> str:
    kind = str(t.get("type") or "")
    if kind == "event":
        text = f"On {t.get('event')}"
    elif kind == "schedule":
        text = f"On a schedule ({t.get('cron')})"
    else:
        text = TRIGGER_TEXT.get(kind, kind)
    if t.get("setting"):
        text += f", where the “{str(t['setting']).replace('_', ' ')}” setting is on"
    return text


def _capabilities(manifest: PackManifest | None) -> list[CapabilityOut]:
    if manifest is None:
        return []
    return [
        CapabilityOut(
            key=c.key,
            title=c.title,
            description=c.description,
            examples=list(c.examples),
            files=list(c.input.files),
            typical_duration_s=c.typical_duration_s,
        )
        for c in manifest.capabilities
        if not c.internal
    ]


def profile(agent: Agent, packs: Any) -> ProfileOut:
    manifest = _manifest(agent, packs)
    trigger_rows: list[dict[str, Any]] = (
        [t.model_dump(exclude_none=True) for t in manifest.triggers]
        if manifest is not None
        else list(agent.triggers or [])
    )
    kinds = {str(t.get("type")) for t in trigger_rows}
    pack = (getattr(packs, "packs", None) or {}).get(agent.pack_key) if agent.pack_key else None
    return ProfileOut(
        agent_id=agent.id,
        is_pack=manifest is not None,
        title=manifest.title if manifest is not None else None,
        charter=(manifest.charter.strip() if manifest is not None else "") or agent.description,
        capabilities=_capabilities(manifest),
        effects=effect_sentences(manifest, packs) if manifest is not None else [],
        triggers=[_trigger_sentence(t) for t in trigger_rows],
        data_class=manifest.data.classification if manifest is not None else None,
        personal_data=manifest.data.personal_data if manifest is not None else None,
        reads_external_content=bool(manifest and manifest.data.reads_external_content),
        has_settings=pack is not None and bool(pack.settings.model_fields),
        can_assign="assigned" in kinds,
        can_mention="mentioned" in kinds,
        can_run="manual" in kinds,
    )


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _FILLER]


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def matches(query: str, card: DirectoryCardOut) -> bool:
    words = _words(query)
    if not words:
        return True
    hay = " ".join(
        [
            card.name,
            card.title or "",
            card.description,
            *(
                f"{c.key} {c.title} {c.description} {' '.join(c.examples)}"
                for c in card.capabilities
            ),
        ]
    ).lower()
    return all(_stem(w) in hay for w in words)


async def directory(
    session: AsyncSession,
    ctx: Ctx,
    agents: list[Agent],
    packs: Any,
    *,
    q: str | None = None,
    capability: str | None = None,
    data_class: str | None = None,
    enabled: bool | None = None,
) -> list[DirectoryCardOut]:
    out = []
    for agent in agents:
        manifest = _manifest(agent, packs)
        card = DirectoryCardOut(
            id=agent.id,
            user_id=agent.user_id,
            key=agent.key,
            name=agent.name,
            avatar=agent.avatar,
            description=agent.description,
            enabled=agent.enabled,
            source=agent.source,
            title=manifest.title if manifest is not None else None,
            capabilities=_capabilities(manifest),
            data_class=manifest.data.classification if manifest is not None else None,
            health=None,
        )
        if enabled is not None and card.enabled != enabled:
            continue
        if data_class and card.data_class != data_class:
            continue
        if capability and not any(
            capability.lower() in (c.key, c.title.lower()) for c in card.capabilities
        ):
            continue
        if q and not matches(q, card):
            continue
        if manifest is not None:
            h = await health.compute(session, ctx, agent, packs, 30)
            card.health = HealthSummaryOut(jobs=h.jobs, items=h.items, success_rate=h.success_rate)
        out.append(card)
    return out
