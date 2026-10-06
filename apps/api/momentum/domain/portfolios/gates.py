"""Phase 7.5 (spec §5.5): stage gates. A portfolio's ``stage_gates`` say, per stage option, what
a project needs before it moves into that stage:

``{option_id: {required_fields: [field_id], required_milestones: [title],
required_files: [glob pattern]}}``

``readiness`` turns that into a deterministic checklist (met or missing, with what to open), and
``blocking_gate`` is what a rule asks before it sets a stage: a rule never overrides a gate.
Nothing here writes; the checklist is the same for everyone who can see the project.
"""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.attachments.models import Attachment
from momentum.domain.fields.models import FieldDef, ProjectFieldValue
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject


@dataclass
class GateItem:
    kind: str  # field | milestone | file
    label: str
    met: bool
    ref: dict[str, Any] | None = None  # what to open: {type, id}


@dataclass
class Readiness:
    stage: str  # the target option id
    stage_label: str
    items: list[GateItem] = field(default_factory=list)

    @property
    def met(self) -> bool:
        return all(i.met for i in self.items)

    @property
    def missing(self) -> list[GateItem]:
        return [i for i in self.items if not i.met]


def option_label(field_def: FieldDef | None, option_id: Any) -> str:
    for o in (field_def.options if field_def is not None else None) or []:
        if isinstance(o, dict) and o.get("id") == option_id:
            return str(o.get("label", option_id))
    return str(option_id)


def _ids(values: Any) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for v in values or []:
        try:
            out.append(uuid.UUID(str(v)))
        except ValueError:
            continue
    return out


async def readiness(
    session: AsyncSession, portfolio: Portfolio, project: Project, to_option: str
) -> Readiness:
    """The gate checklist for moving ``project`` into ``to_option`` of the portfolio's stage
    field. A stage without a gate is always ready (an empty checklist)."""
    stage_field = (
        await session.get(FieldDef, portfolio.stage_field_id) if portfolio.stage_field_id else None
    )
    out = Readiness(stage=to_option, stage_label=option_label(stage_field, to_option))
    gate = (portfolio.stage_gates or {}).get(to_option) or {}
    if not isinstance(gate, dict):
        return out

    field_ids = _ids(gate.get("required_fields"))
    if field_ids:
        defs = {
            f.id: f
            for f in (
                await session.execute(select(FieldDef).where(FieldDef.id.in_(field_ids)))
            ).scalars()
        }
        have = set(
            (
                await session.execute(
                    select(ProjectFieldValue.field_id).where(
                        ProjectFieldValue.project_id == project.id,
                        ProjectFieldValue.field_id.in_(field_ids),
                    )
                )
            ).scalars()
        )
        for fid in field_ids:
            f = defs.get(fid)
            if f is None or f.deleted_at is not None:
                continue  # a deleted field can't be required
            out.items.append(
                GateItem("field", f.name, fid in have, {"type": "project_field", "id": str(fid)})
            )

    titles = [str(t).strip() for t in gate.get("required_milestones") or [] if str(t).strip()]
    if titles:
        rows = (
            await session.execute(
                select(Task.id, Task.title, Task.completed_at)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == project.id,
                    Task.type == "milestone",
                    Task.deleted_at.is_(None),
                )
            )
        ).all()
        for title in titles:
            match = [r for r in rows if r.title.strip().lower() == title.lower()]
            done = next((r for r in match if r.completed_at is not None), None)
            pick = done or (match[0] if match else None)
            out.items.append(
                GateItem(
                    "milestone",
                    title,
                    done is not None,
                    {"type": "task", "id": str(pick.id)} if pick is not None else None,
                )
            )

    patterns = [str(p).strip() for p in gate.get("required_files") or [] if str(p).strip()]
    if patterns:
        in_project = select(TaskProject.task_id).where(TaskProject.project_id == project.id)
        files = (
            await session.execute(
                select(Attachment.id, Attachment.filename).where(
                    or_(Attachment.project_id == project.id, Attachment.task_id.in_(in_project)),
                    Attachment.deleted_at.is_(None),
                    Attachment.is_current.is_(True),
                )
            )
        ).all()
        for pattern in patterns:
            hit = next(
                (f for f in files if fnmatch.fnmatch(f.filename.lower(), pattern.lower())), None
            )
            out.items.append(
                GateItem(
                    "file",
                    pattern,
                    hit is not None,
                    {"type": "file", "id": str(hit.id)} if hit is not None else None,
                )
            )
    return out


def missing_words(r: Readiness) -> str:
    return ", ".join(f"{i.kind} “{i.label}”" for i in r.missing)


async def blocking_gate(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, field_id: uuid.UUID, value: Any
) -> str | None:
    """Why setting ``field_id`` = ``value`` on the project would break a stage gate, or None.
    Only portfolios that contain the project and use the field as their stage field count."""
    from momentum.domain.portfolios.membership import portfolio_ids_containing

    if not isinstance(value, str):
        return None
    project = await session.get(Project, project_id)
    if project is None:
        return None
    for pid in await portfolio_ids_containing(session, project):
        portfolio = await session.get(Portfolio, pid)
        if portfolio is None or portfolio.stage_field_id != field_id:
            continue
        r = await readiness(session, portfolio, project, value)
        if not r.met:
            return (
                f"Gate for {r.stage_label} in {portfolio.name} not met "
                f"(missing {missing_words(r)}), skipped"
            )
    return None
