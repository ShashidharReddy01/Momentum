"""Phase 7.6 S76-06 (spec §8.8): an agent's health over the last ``days``, computed from its jobs,
the records they made, their asks and its skills. Every number has one definition here, and the
tests check them against constructed data:

- **jobs**: its top-level jobs created in the window; **items**: records its jobs made;
- **success**: succeeded ÷ finished top-level jobs (``None`` before any finished);
- **median active / waiting time**: of finished top-level jobs; waiting = time from creation to
  finish minus the active time;
- **asks per item**, **median answer time** (answered asks);
- **human-touch rate**: items a person corrected (a version made by a person with operations
  other than a status change) ÷ items;
- **auto-approved**: items approved by the agent itself ÷ items;
- **top corrected fields** (detail);
- **calibration** (detail) per confidence band: the mean predicted confidence vs the share of
  reviewed items nobody corrected; "Not enough reviewed items yet" below 20 reviewed items;
- **cost per item**: what all its runs cost ÷ items;
- **skills**: active, proposed, and how often they helped and hurt;
- **top failure reasons** (detail);
- **estimated time saved**: the capability's ``manual_minutes_per_item`` times the items nobody
  corrected, plus half that for corrected ones; labelled as an estimate.

Members see the summary; workspace admins and the pack's stewards also see the detail.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.asks.models import Ask
from momentum.domain.records.models import Record, RecordVersion
from momentum.domain.skills.models import Skill

MIN_REVIEWED = 20
BANDS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.0001))
FINISHED = ("succeeded", "failed", "cancelled", "budget_exceeded", "expired")


class Band(BaseModel):
    band: str
    items: int
    predicted: float
    actual: float


class Calibration(BaseModel):
    reviewed: int
    bands: list[Band]
    note: str | None = None


class SkillStats(BaseModel):
    active: int
    proposed: int
    helped: int
    hurt: int


class HealthOut(BaseModel):
    agent_id: uuid.UUID
    days: int
    detail: bool
    jobs: int
    items: int
    success_rate: float | None
    median_active_seconds: float | None
    median_waiting_seconds: float | None
    asks_per_item: float | None
    median_answer_seconds: float | None
    human_touch_rate: float | None
    auto_approved_rate: float | None
    cost_per_item_usd: float | None
    skills: SkillStats | None
    time_saved_minutes: float | None
    time_saved_is_estimate: bool = True
    top_corrected_fields: list[tuple[str, int]] | None = None
    calibration: Calibration | None = None
    top_failure_reasons: list[tuple[str, int]] | None = None


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _human_fields(change: dict[str, Any]) -> list[str]:
    """The fields a person's version corrected (a status change alone isn't a correction)."""
    ops = [o for o in change.get("ops") or [] if o.get("op") != "set_status"]
    return list(change.get("fields") or []) if ops else []


async def compute(
    session: AsyncSession, ctx: Ctx, agent: Agent, packs: Any, days: int = 30
) -> HealthOut:
    from momentum.domain.pack_settings.service import is_steward

    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents")
    detail = ctx.actor.is_admin or bool(
        agent.pack_key and await is_steward(session, ctx.workspace_id, agent.pack_key, ctx.actor.id)
    )
    since = datetime.now(UTC) - timedelta(days=days)
    runs = list(
        (
            await session.execute(
                select(AgentRun).where(AgentRun.agent_id == agent.id, AgentRun.created_at >= since)
            )
        ).scalars()
    )
    run_ids = [r.id for r in runs]
    roots = [r for r in runs if r.parent_run_id is None]
    finished = [r for r in roots if r.status in FINISHED and r.finished_at is not None]
    succeeded = [r for r in finished if r.status == "succeeded"]
    active = [float(r.active_seconds) for r in finished]
    waiting = [
        max(0.0, (r.finished_at - r.created_at).total_seconds() - r.active_seconds)  # type: ignore[operator]
        for r in finished
    ]
    items = (
        list(
            (
                await session.execute(
                    select(Record).where(Record.run_id.in_(run_ids), Record.deleted_at.is_(None))
                )
            ).scalars()
        )
        if run_ids
        else []
    )
    item_ids = [r.id for r in items]
    versions = (
        list(
            (
                await session.execute(
                    select(RecordVersion).where(RecordVersion.record_id.in_(item_ids))
                )
            ).scalars()
        )
        if item_ids
        else []
    )
    corrected: dict[uuid.UUID, list[str]] = {}
    approved_by_agent: set[uuid.UUID] = set()
    for v in versions:
        if v.via in ("review", "api"):
            fields = _human_fields(v.change or {})
            if fields:
                corrected.setdefault(v.record_id, []).extend(fields)
        if v.via == "agent" and v.status == "approved":
            approved_by_agent.add(v.record_id)
    n = len(items)
    asks = (
        list((await session.execute(select(Ask).where(Ask.run_id.in_(run_ids)))).scalars())
        if run_ids
        else []
    )
    answer_times = [
        (a.answered_at - a.created_at).total_seconds()
        for a in asks
        if a.status == "answered" and a.answered_at is not None
    ]
    cost = sum((r.cost_usd for r in runs), Decimal(0))
    skills = None
    if agent.pack_key:
        rows = list(
            (
                await session.execute(
                    select(Skill).where(
                        Skill.workspace_id == ctx.workspace_id, Skill.pack_key == agent.pack_key
                    )
                )
            ).scalars()
        )
        skills = SkillStats(
            active=sum(1 for s in rows if s.status == "active"),
            proposed=sum(1 for s in rows if s.status == "proposed"),
            helped=sum(int((s.metrics or {}).get("helped", 0)) for s in rows),
            hurt=sum(int((s.metrics or {}).get("hurt", 0)) for s in rows),
        )
    minutes = _manual_minutes(agent, packs)
    saved = None
    if minutes is not None and n:
        clean = n - len(corrected)
        saved = minutes * clean + minutes * 0.5 * len(corrected)
    out = HealthOut(
        agent_id=agent.id,
        days=days,
        detail=detail,
        jobs=len(roots),
        items=n,
        success_rate=len(succeeded) / len(finished) if finished else None,
        median_active_seconds=_median(active),
        median_waiting_seconds=_median(waiting),
        asks_per_item=len(asks) / n if n else None,
        median_answer_seconds=_median(answer_times),
        human_touch_rate=len(corrected) / n if n else None,
        auto_approved_rate=len(approved_by_agent) / n if n else None,
        cost_per_item_usd=float(cost) / n if n else None,
        skills=skills,
        time_saved_minutes=saved,
    )
    if detail:
        field_counts = Counter(
            f.split(".")[0].split("[")[0] for fs in corrected.values() for f in fs
        )
        out.top_corrected_fields = field_counts.most_common(5)
        reasons = Counter((r.error or "Unknown")[:80] for r in finished if r.status != "succeeded")
        out.top_failure_reasons = reasons.most_common(5)
        out.calibration = _calibration(items, corrected)
    return out


def _calibration(items: list[Record], corrected: dict[uuid.UUID, list[str]]) -> Calibration:
    reviewed = [
        r for r in items if r.confidence is not None and r.status in ("approved", "rejected")
    ]
    if len(reviewed) < MIN_REVIEWED:
        return Calibration(reviewed=len(reviewed), bands=[], note="Not enough reviewed items yet")
    bands: list[Band] = []
    for lo, hi in BANDS:
        inside = [r for r in reviewed if lo <= float(r.confidence or 0) < hi]
        if not inside:
            continue
        bands.append(
            Band(
                band=f"{lo:.2f}-{min(hi, 1.0):.2f}",
                items=len(inside),
                predicted=round(sum(float(r.confidence or 0) for r in inside) / len(inside), 4),
                actual=round(sum(1 for r in inside if r.id not in corrected) / len(inside), 4),
            )
        )
    return Calibration(reviewed=len(reviewed), bands=bands)


def _manual_minutes(agent: Agent, packs: Any) -> float | None:
    pack = (getattr(packs, "packs", None) or {}).get(agent.pack_key) if agent.pack_key else None
    if pack is None:
        return None
    for cap in pack.manifest.capabilities:
        if cap.manual_minutes_per_item is not None:
            return float(cap.manual_minutes_per_item)
    return None
