"""S6.2.2: portfolios. The one write path for them and for their status updates.

Visibility (kickoff Q5): every workspace member can see a portfolio; its owner and workspace
admins edit it. Everything *inside* is computed as the viewer: a project row appears only if the
viewer can see that project, and the rest are only counted (``hidden_projects``), never named.
Adding a project requires seeing it. A portfolio's status updates reuse ``status_updates`` with
``entity_type='portfolio'``; posting one sets ``portfolios.status``, undoable like a project's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.permissions import Action, can
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, visible_projects_clause
from momentum.domain.portfolios.models import Portfolio, PortfolioItem
from momentum.domain.portfolios.schemas import PortfolioIn, PortfolioPatchIn
from momentum.domain.projects.models import Project
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.domain.status_updates.service import STATUS_LABELS, body_text
from momentum.domain.tasks.models import Task, TaskProject

# worst first: a portfolio is as healthy as its least healthy project
SEVERITY = ("off_track", "at_risk", "on_hold", "on_track", "complete")


def _channels(p: Portfolio) -> list[str]:
    return [f"portfolio:{p.id}"]


async def get_portfolio(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, *, include_deleted: bool = False
) -> Portfolio:
    p = await session.get(Portfolio, portfolio_id)
    if p is None or p.workspace_id != ctx.workspace_id:
        raise NotFound("Portfolio not found")
    if p.deleted_at is not None and not include_deleted:
        raise NotFound("Portfolio not found")
    return p


def can_edit(ctx: Ctx, p: Portfolio) -> bool:
    return ctx.actor.is_admin or p.owner_id == ctx.actor.id


def _require_edit(ctx: Ctx, p: Portfolio) -> None:
    if not can_edit(ctx, p):
        raise Forbidden("Only the portfolio's owner or a workspace admin can change it")


async def _record(
    session: AsyncSession,
    ctx: Ctx,
    p: Portfolio,
    verb: str,
    changes: Diff | None = None,
    undo: dict[str, Any] | None = None,
) -> uuid.UUID:
    act = await record_activity(
        session,
        ctx,
        entity_type="portfolio",
        entity_id=p.id,
        verb=verb,
        changes=changes or {},
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="portfolio",
        entity_id=p.id,
        data={"version": p.version},
        channels=_channels(p),
        activity_id=act.id,
    )
    return act.id


# ---------- portfolios ----------


async def list_portfolios(session: AsyncSession, ctx: Ctx) -> list[tuple[Portfolio, int]]:
    """Every portfolio in the workspace, with how many of its projects the viewer can see."""
    portfolios = list(
        (
            await session.execute(
                select(Portfolio)
                .where(Portfolio.workspace_id == ctx.workspace_id, Portfolio.deleted_at.is_(None))
                .order_by(func.lower(Portfolio.name))
            )
        ).scalars()
    )
    counts: dict[uuid.UUID, int] = {
        pid: int(n)
        for pid, n in (
            await session.execute(
                select(PortfolioItem.portfolio_id, func.count())
                .join(Project, Project.id == PortfolioItem.project_id)
                .where(
                    PortfolioItem.workspace_id == ctx.workspace_id,
                    Project.deleted_at.is_(None),
                    visible_projects_clause(ctx),
                )
                .group_by(PortfolioItem.portfolio_id)
            )
        ).all()
    }
    return [(p, counts.get(p.id, 0)) for p in portfolios]


async def create_portfolio(
    session: AsyncSession, ctx: Ctx, data: PortfolioIn
) -> Mutation[Portfolio]:
    if ctx.actor.id is None or not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create portfolios")
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Portfolio name can't be empty")
    p = Portfolio(
        workspace_id=ctx.workspace_id,
        name=name,
        description=(data.description or "").strip() or None,
        owner_id=ctx.actor.id,
    )
    session.add(p)
    await session.flush()
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.created",
        {"name": (None, p.name)},
        undo_op("portfolios.delete", portfolio_id=p.id),
    )
    return Mutation(p, act, version=p.version)


async def update_portfolio(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    patch: PortfolioPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    p = await get_portfolio(session, ctx, portfolio_id)
    _require_edit(ctx, p)
    changes: Diff = {}
    for f in patch.model_fields_set & {"name", "description"}:
        new = getattr(patch, f)
        new = new.strip() if isinstance(new, str) else new
        if f == "name" and not new:
            raise ValidationFailed("Portfolio name can't be empty")
        if f == "description":
            new = new or None
        if getattr(p, f) != new:
            changes[f] = (getattr(p, f), new)
            setattr(p, f, new)
    if not changes:
        return Mutation(p, version=p.version)
    p.version += 1
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.updated",
        changes,
        undo_op(
            "portfolios.update",
            portfolio_id=p.id,
            version=p.version,
            patch={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    return Mutation(p, act, version=p.version)


async def delete_portfolio(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Portfolio]:
    p = await get_portfolio(session, ctx, portfolio_id)
    _require_edit(ctx, p)
    p.deleted_at = datetime.now(UTC)
    p.version += 1
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.deleted",
        undo=undo_op("portfolios.restore", portfolio_id=p.id) if record_undo else None,
    )
    return Mutation(p, act, version=p.version)


# ---------- projects in a portfolio ----------


async def add_project(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    position: str | None = None,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    p = await get_portfolio(session, ctx, portfolio_id)
    _require_edit(ctx, p)
    project, _ = await get_visible_project(session, ctx, project_id)  # you add what you can see
    if await session.get(PortfolioItem, (p.id, project.id)) is not None:
        raise Conflict("That project is already in this portfolio", code="already_added")
    if position is None:
        last = (
            await session.execute(
                select(func.max(PortfolioItem.position)).where(PortfolioItem.portfolio_id == p.id)
            )
        ).scalar_one_or_none()
        position = key_between(last, None)
    session.add(
        PortfolioItem(
            portfolio_id=p.id,
            project_id=project.id,
            workspace_id=ctx.workspace_id,
            position=position,
        )
    )
    p.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.project_added",
        {"project": (None, project.name)},
        undo_op("portfolios.remove_project", portfolio_id=p.id, project_id=project.id)
        if record_undo
        else None,
    )
    return Mutation(p, act, version=p.version)


async def remove_project(
    session: AsyncSession,
    ctx: Ctx,
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[Portfolio]:
    p = await get_portfolio(session, ctx, portfolio_id)
    _require_edit(ctx, p)
    item = await session.get(PortfolioItem, (p.id, project_id))
    if item is None:
        raise NotFound("That project isn't in this portfolio")
    project = await session.get(Project, project_id)
    position = item.position
    await session.delete(item)
    p.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.project_removed",
        {"project": (project.name if project else None, None)},
        undo_op(
            "portfolios.add_project", portfolio_id=p.id, project_id=project_id, position=position
        )
        if record_undo
        else None,
    )
    return Mutation(p, act, version=p.version)


# ---------- the table ----------


async def portfolio_rows(
    session: AsyncSession, ctx: Ctx, p: Portfolio
) -> tuple[list[tuple[Project, dict[str, Any]]], int]:
    """(visible project rows in portfolio order, how many more the viewer can't see)."""
    visible = list(
        (
            await session.execute(
                select(Project)
                .join(PortfolioItem, PortfolioItem.project_id == Project.id)
                .where(
                    PortfolioItem.portfolio_id == p.id,
                    Project.deleted_at.is_(None),
                    visible_projects_clause(ctx),
                )
                .order_by(PortfolioItem.position)
            )
        ).scalars()
    )
    total_items = (
        await session.execute(
            select(func.count())
            .select_from(PortfolioItem)
            .join(Project, Project.id == PortfolioItem.project_id)
            .where(PortfolioItem.portfolio_id == p.id, Project.deleted_at.is_(None))
        )
    ).scalar_one()
    ids = [x.id for x in visible]
    today = datetime.now(UTC).date()
    counts: dict[uuid.UUID, tuple[int, int, int]] = {}
    latest: dict[uuid.UUID, tuple[str, datetime]] = {}
    if ids:
        for pid, total, done, overdue in (
            await session.execute(
                select(
                    TaskProject.project_id,
                    func.count(),
                    func.count(Task.completed_at),
                    func.count().filter(Task.completed_at.is_(None), Task.due_on < today),
                )
                .join(Task, Task.id == TaskProject.task_id)
                .where(
                    TaskProject.project_id.in_(ids),
                    Task.parent_id.is_(None),
                    Task.deleted_at.is_(None),
                )
                .group_by(TaskProject.project_id)
            )
        ).all():
            counts[pid] = (int(total), int(done), int(overdue))
        for pid, title, at in (
            await session.execute(
                select(StatusUpdate.entity_id, StatusUpdate.title, StatusUpdate.created_at)
                .where(
                    StatusUpdate.entity_type == "project",
                    StatusUpdate.entity_id.in_(ids),
                    StatusUpdate.deleted_at.is_(None),
                )
                .distinct(StatusUpdate.entity_id)
                .order_by(StatusUpdate.entity_id, StatusUpdate.created_at.desc())
            )
        ).all():
            latest[pid] = (title, at)
    rows = []
    for x in visible:
        total, done, overdue = counts.get(x.id, (0, 0, 0))
        title, at = latest.get(x.id, (None, None))
        rows.append(
            (
                x,
                {
                    "total_tasks": total,
                    "completed_tasks": done,
                    "overdue_tasks": overdue,
                    "latest_update_title": title,
                    "latest_update_at": at,
                },
            )
        )
    return rows, int(total_items) - len(visible)


# ---------- portfolio status updates ----------


async def list_statuses(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, *, limit: int = 20
) -> list[StatusUpdate]:
    p = await get_portfolio(session, ctx, portfolio_id)
    return list(
        (
            await session.execute(
                select(StatusUpdate)
                .where(
                    StatusUpdate.entity_type == "portfolio",
                    StatusUpdate.entity_id == p.id,
                    StatusUpdate.deleted_at.is_(None),
                )
                .order_by(StatusUpdate.created_at.desc(), StatusUpdate.id.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def post_status(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID, data: StatusUpdateIn
) -> Mutation[StatusUpdate]:
    p = await get_portfolio(session, ctx, portfolio_id)
    _require_edit(ctx, p)
    update = StatusUpdate(
        workspace_id=ctx.workspace_id,
        entity_type="portfolio",
        entity_id=p.id,
        status=data.status,
        title=data.title.strip(),
        body={"summary": data.summary.strip(), "sections": data.sections.model_dump()},
        body_text=body_text(data),
        author_id=ctx.actor.id,
        generated_by_ai=data.generated_by_ai or ctx.via in ("ai", "agent"),
        created_via=ctx.via,
    )
    session.add(update)
    previous = p.status
    p.status = data.status
    p.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        p,
        "portfolio.status_updated",
        {"status": (previous, data.status), "status_update": (None, update.title)},
        undo_op(
            "portfolios.withdraw_status",
            update_id=update.id,
            portfolio_id=p.id,
            previous_status=previous,
        ),
    )
    return Mutation(update, act, version=p.version)


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"  # no %-d: it fails on Windows


async def draft_status(session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID) -> StatusUpdateIn:
    """A portfolio check-in built in code from its projects, as the viewer sees them: the status
    is the least healthy project's; the title counts statuses; projects at risk or off track go
    under Slipped (with their latest update's title), overdue work under Blockers, completed
    projects under Completed, and what's due in the next two weeks under Next. Nothing is
    invented: a project with no status is counted as "no status yet"."""
    p = await get_portfolio(session, ctx, portfolio_id)
    rows, hidden = await portfolio_rows(session, ctx, p)
    statuses = [x.status for x, _ in rows]
    known = [s for s in statuses if s]
    worst = min(known, key=SEVERITY.index) if known else "on_track"
    tally = [
        f"{statuses.count(s)} {STATUS_LABELS[s].lower()}" for s in SEVERITY if statuses.count(s)
    ]
    if statuses.count(None):
        tally.append(f"{statuses.count(None)} with no status yet")
    title = ", ".join(tally) if tally else "No projects yet"
    today = datetime.now(UTC).date()
    slipped, blockers, completed, nxt = [], [], [], []
    for x, facts in rows:
        latest = facts["latest_update_title"]
        if x.status in ("at_risk", "off_track"):
            label = STATUS_LABELS[x.status].lower()
            slipped.append(f"{x.name} is {label}" + (f": {latest}" if latest else ""))
        if x.status == "complete":
            completed.append(f"{x.name} is complete")
        if facts["overdue_tasks"]:
            n = facts["overdue_tasks"]
            blockers.append(f"{x.name} has {n} overdue {'task' if n == 1 else 'tasks'}")
        if x.due_on and today <= x.due_on <= today + timedelta(days=14) and x.status != "complete":
            nxt.append(f"{x.name} is due {_fmt(x.due_on)}")
    done = sum(f["completed_tasks"] for _, f in rows)
    total = sum(f["total_tasks"] for _, f in rows)
    summary = f"{len(rows)} projects, {done} of {total} tasks done." if rows else ""
    if hidden:
        summary += f" {hidden} more in projects you can't see are not included."

    def items(xs: list[str]) -> list[StatusItem]:
        return [StatusItem(text=t[:500]) for t in xs[:30]]

    return StatusUpdateIn(
        status=worst,
        title=title[:200],
        summary=summary.strip(),
        sections=StatusSections(
            completed=items(completed),
            slipped=items(slipped),
            blockers=items(blockers),
            next=items(nxt),
        ),
    )


# ---------- undo ----------


def _pid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["portfolio_id"]))


@undo_handler("portfolios.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await delete_portfolio(session, ctx, _pid(args), record_undo=False)


@undo_handler("portfolios.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    p = await get_portfolio(session, ctx, _pid(args), include_deleted=True)
    _require_edit(ctx, p)
    if p.deleted_at is None:
        raise UndoConflict("The portfolio is not deleted")
    p.deleted_at = None
    p.version += 1
    await _record(session, ctx, p, "portfolio.restored")


@undo_handler("portfolios.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    p = await get_portfolio(session, ctx, _pid(args))
    if p.version != int(args["version"]):
        raise UndoConflict("This portfolio changed after your edit")
    await update_portfolio(session, ctx, p.id, PortfolioPatchIn(**args["patch"]), record_undo=False)


@undo_handler("portfolios.remove_project")
async def _undo_add(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await remove_project(
        session, ctx, _pid(args), uuid.UUID(str(args["project_id"])), record_undo=False
    )


@undo_handler("portfolios.add_project")
async def _undo_remove(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await add_project(
        session,
        ctx,
        _pid(args),
        uuid.UUID(str(args["project_id"])),
        position=str(args["position"]),
        record_undo=False,
    )


@undo_handler("portfolios.withdraw_status")
async def _undo_status(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    update = await session.get(StatusUpdate, uuid.UUID(str(args["update_id"])))
    if update is None or update.deleted_at is not None:
        raise UndoConflict("That status update is already gone")
    p = await get_portfolio(session, ctx, _pid(args))
    if p.status != update.status:
        raise UndoConflict("The portfolio's status changed after this update")
    update.deleted_at = datetime.now(UTC)
    p.status = args.get("previous_status")
    p.version += 1
    await _record(session, ctx, p, "portfolio.status_withdrawn")
