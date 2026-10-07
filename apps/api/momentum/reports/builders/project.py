"""Phase 7.5 (spec §6.2): the project kinds — status, customer status and close-out.

Numbers come from the same code as the portfolio table (``portfolios.rows.compute_rows``), so a
report, a dashboard and the portfolio always agree. A customer report leaves out tasks tagged
``internal`` and names no one but the project's owner.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from momentum.domain.access import get_visible_project
from momentum.domain.fields.models import FieldDef, ProjectFieldEvent, ProjectFieldValue
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import compute_rows
from momentum.domain.projects.models import Project, ProjectSnapshot
from momentum.domain.users.models import User
from momentum.reports.builders.common import (
    STATUS_WORDS,
    BuildContext,
    day,
    pct,
    plural,
)
from momentum.reports.data import (
    TaskFact,
    blockers,
    days,
    in_period,
    local_date,
    project_tasks,
    waiting_on_customer,
)
from momentum.reports.document import (
    Callout,
    Cell,
    Chart,
    Heading,
    Kpi,
    KPIRow,
    Paragraph,
    ReportDocument,
    Table,
    TaskItem,
    TaskList,
)


async def _project(bc: BuildContext) -> tuple[Project, dict[str, Any], list[TaskFact]]:
    assert bc.spec.scope.project_id is not None
    project, _role = await get_visible_project(bc.session, bc.ctx, bc.spec.scope.project_id)
    rows = await compute_rows(
        bc.session,
        bc.ctx,
        [project],
        stage_field=None,
        stage_targets={},
        columns=[],
        today=bc.today,
        live_fields=set(),
    )
    tasks = await project_tasks(bc.session, [project.id], {project.id: project.name})
    return project, rows[0], tasks


def _item(t: TaskFact, *, people: bool = True) -> TaskItem:
    return TaskItem(
        key=t.key,
        title=t.title,
        assignee=t.assignee if people else None,
        due_on=t.due_on,
        done=t.done,
    )


def _milestone_rows(
    bc: BuildContext, milestones: list[TaskFact]
) -> tuple[list[list[Any]], int, int]:
    rows: list[list[Any]] = []
    hit = missed = 0
    for m in milestones:
        done_on = local_date(m.completed_at, bc.ctx)
        if done_on is not None:
            late = m.due_on is not None and done_on > m.due_on
            missed += late
            hit += not late
            state = f"Done {days(m.due_on, done_on)} days late" if late and m.due_on else "Done"
        elif m.due_on is not None and m.due_on < bc.today:
            missed += 1
            state = f"{days(m.due_on, bc.today)} days late"
        else:
            state = "Upcoming"
        rows.append([m.title, m.due_on, done_on, state])
    return rows, hit, missed


def _facts_tasks(tasks: list[TaskFact]) -> list[dict[str, Any]]:
    return [
        {"key": t.key, "title": t.title, "due_on": t.due_on.isoformat() if t.due_on else None}
        for t in tasks[:15]
    ]


async def build_project_status(bc: BuildContext) -> ReportDocument:
    project, row, tasks = await _project(bc)
    start, end = bc.period()
    doc = bc.doc(f"{project.name}: status", f"{day(start)} to {day(end)}")
    milestones = [t for t in tasks if t.type == "milestone"]
    m_rows, hit, missed = _milestone_rows(bc, milestones)
    completed = [t for t in tasks if in_period(t.completed_at, start, end, bc.ctx)]
    upcoming = [
        t
        for t in tasks
        if not t.done and t.due_on and bc.today <= t.due_on <= bc.today + timedelta(days=14)
    ]
    overdue = [t for t in tasks if t.overdue(bc.today)]
    status = STATUS_WORDS.get(row["status"] or "", "No status yet")
    if bc.spec.wants("kpis"):
        doc.add(
            KPIRow(
                [
                    Kpi("Progress", pct(row["progress"]), row["progress"]),
                    Kpi("Open tasks", str(row["open"]), row["open"]),
                    Kpi("Overdue", str(row["overdue"]), row["overdue"]),
                    Kpi("Blocked", str(row["blocked"]), row["blocked"]),
                    Kpi("Milestones hit", str(hit), hit),
                    Kpi("Milestones missed", str(missed), missed),
                ]
            )
        )
    doc.narrative_index = len(doc.blocks)
    if bc.spec.wants("status"):
        u = row["latest_update"]
        doc.add(Heading("Status"), Paragraph(f"Current status: {status}."))
        if u:
            doc.add(Paragraph(f"Latest update: {u['title']}."))
        if row["target_date"] or row["forecast_date"]:
            doc.add(
                Paragraph(
                    f"Target date {day(row['target_date'])}; likely done "
                    f"{day(row['forecast_date'])}."
                )
            )
    if bc.spec.wants("milestones"):
        doc.add(Table("Milestones", ["Milestone", "Due", "Done on", "Where it stands"], m_rows))
    if bc.spec.wants("completed"):
        doc.add(TaskList("Completed in the period", [_item(t) for t in completed]))
    if bc.spec.wants("upcoming"):
        doc.add(TaskList("Due in the next 2 weeks", [_item(t) for t in upcoming]))
    if bc.spec.wants("overdue"):
        doc.add(TaskList("Overdue", [_item(t) for t in overdue], empty="Nothing is overdue."))
    risks = _risks(bc, row, milestones, overdue)
    if bc.spec.wants("risks"):
        doc.add(Heading("Risks"))
        doc.add(*(risks or [Callout("No risk signals right now.", "ok")]))
    doc.facts = {
        "project": project.name,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "status": status,
        "kpis": {
            "progress": pct(row["progress"]),
            "open": row["open"],
            "overdue": row["overdue"],
            "blocked": row["blocked"],
            "milestones_hit": hit,
            "milestones_missed": missed,
        },
        "milestones": [
            {"name": r[0], "due": r[1].isoformat() if r[1] else None, "state": r[3]} for r in m_rows
        ],
        "completed": _facts_tasks(completed),
        "upcoming": _facts_tasks(upcoming),
        "overdue": _facts_tasks(overdue),
        "risks": [c.text for c in risks],
    }
    return doc


def _risks(
    bc: BuildContext, row: dict[str, Any], milestones: list[TaskFact], overdue: list[TaskFact]
) -> list[Callout]:
    """The project's risk signals, worked out from its own numbers (the same signals Radar
    watches: late milestones, slipping forecast, blocked and overdue work, a red status)."""
    out: list[Callout] = []
    if (row["slip_days"] or 0) > 0:
        out.append(
            Callout(f"The forecast is {row['slip_days']} days past the target date.", "crit")
        )
    for m in milestones:
        if not m.done and m.due_on and m.due_on < bc.today:
            out.append(
                Callout(f"Milestone {m.title} is {days(m.due_on, bc.today)} days late.", "crit")
            )
    if row["status"] in ("at_risk", "off_track"):
        out.append(Callout(f"The latest status is {STATUS_WORDS[row['status']]}.", "warn"))
    if row["blocked"]:
        out.append(Callout(f"{plural(row['blocked'], 'task')} wait on another task.", "warn"))
    if overdue:
        out.append(Callout(f"{plural(len(overdue), 'task is', 'tasks are')} overdue.", "warn"))
    return out


async def build_customer_status(bc: BuildContext) -> ReportDocument:
    project, _row, all_tasks = await _project(bc)
    tasks = [t for t in all_tasks if not t.internal]  # never a task tagged internal
    start, end = bc.period()
    owner = await bc.session.get(User, project.owner_id) if project.owner_id else None
    doc = bc.doc(f"{project.name}: progress update", f"{day(start)} to {day(end)}")
    doc.scope_note = (
        f"Prepared by {owner.name if owner else 'the project team'} on {bc.today:%d %b %Y}."
    )
    done = sum(t.done for t in tasks)
    progress = done / len(tasks) if tasks else None
    milestones = [t for t in tasks if t.type == "milestone"]
    m_rows, hit, _missed = _milestone_rows(bc, milestones)
    waiting_ids = await waiting_on_customer(bc.session, bc.ctx, [t.id for t in tasks])
    needs = [t for t in tasks if t.id in waiting_ids and not t.done]
    nxt = [
        t
        for t in tasks
        if not t.done and t.due_on and bc.today <= t.due_on <= bc.today + timedelta(days=14)
    ]
    if bc.spec.wants("progress"):
        doc.add(
            KPIRow(
                [
                    Kpi("Progress", pct(progress), progress),
                    Kpi(
                        "Milestones reached",
                        f"{sum(1 for m in milestones if m.done)} of {len(milestones)}",
                    ),
                    Kpi("Waiting on you", str(len(needs)), len(needs)),
                ]
            )
        )
    doc.narrative_index = len(doc.blocks)
    if bc.spec.wants("milestones"):
        doc.add(
            Table(
                "Milestones",
                ["Milestone", "Planned", "Reached", "Where it stands"],
                [[r[0], r[1], r[2], r[3]] for r in m_rows],
            )
        )
    if bc.spec.wants("needs"):
        doc.add(
            TaskList(
                "What we need from you",
                [_item(t, people=False) for t in needs],
                empty="Nothing is waiting on you right now.",
            )
        )
    if bc.spec.wants("next_steps"):
        doc.add(TaskList("Next steps (2 weeks)", [_item(t, people=False) for t in nxt]))
    doc.facts = {
        "project": project.name,
        "audience": "customer",
        "progress": pct(progress),
        "milestones": [{"name": r[0], "state": r[3]} for r in m_rows],
        "needs": _facts_tasks(needs),
        "next_steps": _facts_tasks(nxt),
        "milestones_reached": hit,
    }
    return doc


async def _stage_stays(bc: BuildContext, project: Project) -> list[list[Any]]:
    """Time in each stage, from the project's stage-field history (the stage field of a
    portfolio holding it, else a project field named Stage)."""
    field_ids = list(
        (
            await bc.session.execute(
                select(Portfolio.stage_field_id).where(
                    Portfolio.workspace_id == bc.ctx.workspace_id,
                    Portfolio.stage_field_id.is_not(None),
                    Portfolio.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    named = (
        await bc.session.execute(
            select(FieldDef.id).where(
                FieldDef.workspace_id == bc.ctx.workspace_id,
                FieldDef.applies_to == "project",
                FieldDef.name.ilike("stage"),
                FieldDef.deleted_at.is_(None),
            )
        )
    ).scalars()
    candidates = [*field_ids, *named]
    if not candidates:
        return []
    events = (
        await bc.session.execute(
            select(ProjectFieldEvent)
            .where(
                ProjectFieldEvent.project_id == project.id,
                ProjectFieldEvent.field_id.in_(candidates),
            )
            .order_by(ProjectFieldEvent.at, ProjectFieldEvent.id)
        )
    ).scalars()
    by_field: dict[uuid.UUID, list[ProjectFieldEvent]] = defaultdict(list)
    for e in events:
        by_field[e.field_id].append(e)
    if not by_field:
        return []
    fid = max(by_field, key=lambda k: len(by_field[k]))
    field = await bc.session.get(FieldDef, fid)
    labels = {
        str(o.get("id")): str(o.get("label"))
        for o in (field.options if field and isinstance(field.options, list) else [])
        if isinstance(o, dict)
    }
    out: list[list[Any]] = []
    evs = by_field[fid]
    for i, e in enumerate(evs):
        if not isinstance(e.new, str):
            continue
        entered = local_date(e.at, bc.ctx)
        left = local_date(evs[i + 1].at, bc.ctx) if i + 1 < len(evs) else None
        assert entered is not None
        out.append([labels.get(e.new, "A stage"), entered, left, days(entered, left or bc.today)])
    return out


async def build_closeout(bc: BuildContext) -> ReportDocument:
    project, row, tasks = await _project(bc)
    created = local_date(project.created_at, bc.ctx) or bc.today
    start = bc.spec.period.start if bc.spec.period else (project.start_on or created)
    end = bc.spec.period.end if bc.spec.period else bc.today
    doc = bc.doc(f"{project.name}: close-out", f"{day(start)} to {day(end)}")
    finished = [local_date(t.completed_at, bc.ctx) for t in tasks if t.done]
    all_done = bool(tasks) and all(t.done for t in tasks)
    actual_end = max(d for d in finished if d) if all_done and finished else None
    planned_end = project.due_on
    target = (
        await bc.session.execute(
            select(ProjectFieldValue.value)
            .join(FieldDef, FieldDef.id == ProjectFieldValue.field_id)
            .where(
                ProjectFieldValue.project_id == project.id,
                FieldDef.name.ilike("target go-live"),
                FieldDef.type == "date",
            )
        )
    ).scalar_one_or_none()
    if planned_end is None and isinstance(target, str):
        planned_end = date.fromisoformat(target)
    planned_days = days(start, planned_end) if planned_end else None
    actual_days = days(start, actual_end or bc.today)
    if bc.spec.wants("planned_actual"):
        doc.add(
            Heading("Planned and actual"),
            Table(
                "Planned and actual",
                ["", "Planned", "Actual"],
                [
                    ["Start", start, created],
                    ["Finish (go-live)", planned_end, actual_end],
                    ["Duration (days)", planned_days, actual_days],
                ],
            ),
        )
        if actual_end is None:
            doc.add(Callout("Some work is still open: the actual finish is not set yet.", "warn"))
    doc.narrative_index = len(doc.blocks)
    # scope: the work planned at the start (the earliest snapshot in the first week, else the
    # tasks created in the first week) against all the work now
    snap = (
        await bc.session.execute(
            select(ProjectSnapshot)
            .where(
                ProjectSnapshot.project_id == project.id,
                ProjectSnapshot.day <= created + timedelta(days=7),
            )
            .order_by(ProjectSnapshot.day)
            .limit(1)
        )
    ).scalar_one_or_none()
    if snap is not None:
        planned = int(snap.data.get("open", 0)) + int(snap.data.get("completed", 0))
        basis = f"the snapshot of {day(snap.day)}"
    else:
        cutoff = created + timedelta(days=7)
        planned = sum(1 for t in tasks if (local_date(t.created_at, bc.ctx) or cutoff) <= cutoff)
        basis = "tasks created in the first week"
    added = max(0, len(tasks) - planned)
    if bc.spec.wants("scope"):
        doc.add(
            Heading("Scope"),
            KPIRow(
                [
                    Kpi("Planned at the start", str(planned), planned),
                    Kpi("Added later", str(added), added),
                    Kpi("Done", f"{sum(t.done for t in tasks)} of {len(tasks)}"),
                ]
            ),
            Paragraph(f"Planned work counted from {basis}."),
        )
    milestones = [t for t in tasks if t.type == "milestone"]
    slips: list[list[Cell]] = []
    for m in milestones:
        done_on = local_date(m.completed_at, bc.ctx)
        if m.due_on is None:
            continue
        slip = days(m.due_on, done_on or bc.today)
        slips.append([m.title, m.due_on, done_on, max(0, slip)])
    if bc.spec.wants("milestone_slips"):
        doc.add(Table("Milestone slips", ["Milestone", "Due", "Done on", "Days late"], slips))
    stays = await _stage_stays(bc, project)
    if bc.spec.wants("stages") and stays:
        doc.add(Table("Time in each stage", ["Stage", "Entered", "Left", "Days"], stays))
        doc.add(Chart("Days per stage", "bar", [s[0] for s in stays], [float(s[3]) for s in stays]))
    top = sorted((await blockers(bc.session, [t.id for t in tasks])).items(), key=lambda x: -x[1])
    names = {t.id: t for t in tasks}
    blocker_rows: list[list[Cell]] = []
    for k, n in top:
        if k in names and len(blocker_rows) < 5:
            blocker_rows.append([names[k].key, names[k].title, n])
    if bc.spec.wants("blockers"):
        doc.add(Table("Top blockers", ["Task", "Title", "Tasks it held up"], blocker_rows))
    done_by = Counter(t.assignee or "Unassigned" for t in tasks if t.done)
    open_by = Counter(t.assignee or "Unassigned" for t in tasks if not t.done)
    people = sorted(set(done_by) | set(open_by))
    work_rows: list[list[Cell]] = [[p, done_by.get(p, 0), open_by.get(p, 0)] for p in people]
    if bc.spec.wants("workload"):
        doc.add(Table("Workload by person", ["Person", "Completed", "Still open"], work_rows))
    doc.facts = {
        "project": project.name,
        "planned_finish": planned_end.isoformat() if planned_end else None,
        "actual_finish": actual_end.isoformat() if actual_end else None,
        "planned_days": planned_days,
        "actual_days": actual_days,
        "scope": {"planned": planned, "added": added, "total": len(tasks)},
        "milestone_slips": [{"name": s[0], "days_late": s[3]} for s in slips if s[3]],
        "stages": [{"stage": s[0], "days": s[3]} for s in stays],
        "blockers": [{"key": b[0], "title": b[1], "held_up": b[2]} for b in blocker_rows],
        "status": STATUS_WORDS.get(row["status"] or "", "No status"),
    }
    return doc
