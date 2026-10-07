"""Phase 7.5 (spec §6.2): ``task_export``: a summary (by status, assignee, section) and every task
of a project or a portfolio the requester can see, with its custom fields; ``filters`` narrow it
like a dashboard's (status, assignees, due, priorities, tags…)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from momentum.domain.access import get_visible_project
from momentum.domain.dashboards import query
from momentum.domain.dashboards.query_scope import scope_projects
from momentum.domain.dashboards.spec import QueryFilters, QuerySpec
from momentum.reports.builders.common import BuildContext, day
from momentum.reports.data import local_date, option_label, project_tasks, task_fields
from momentum.reports.document import Chart, Heading, Kpi, KPIRow, ReportDocument, Table

MAX_ROWS = 20_000


async def build_task_export(bc: BuildContext) -> ReportDocument:
    s = bc.spec.scope
    if s.project_id is not None:
        project, _ = await get_visible_project(bc.session, bc.ctx, s.project_id)
        projects = [project]
        where = project.name
    else:
        assert s.portfolio_id is not None
        scope = await scope_projects(bc.session, bc.ctx, portfolio_id=s.portfolio_id)
        projects = scope.projects
        where = scope.portfolio.name if scope.portfolio else "Portfolio"
    names = {p.id: p.name for p in projects}
    tasks = await project_tasks(bc.session, list(names), names)
    filters = bc.spec.filters
    if filters is not None and filters != QueryFilters(status="all"):
        # the dashboard engine decides which tasks match (same rules as a chart's filters)
        # the scope's projects, set (not validated: a portfolio can hold more than 50)
        spec = QuerySpec(filters=filters.model_copy(update={"project_ids": list(names)}), limit=50)
        run, _fields = await query._prepare(bc.session, bc.ctx, spec, None)
        rows, _total = await run.task_rows([], MAX_ROWS)
        keep = {r.id for r in rows}
        tasks = [t for t in tasks if t.id in keep]
    tasks = tasks[:MAX_ROWS]
    defs, values = await task_fields(bc.session, bc.ctx, [t.id for t in tasks])
    doc = bc.doc(f"{where}: tasks", f"Exported {day(bc.today)}")
    status = Counter(
        "Completed" if t.done else "Overdue" if t.overdue(bc.today) else "Open" for t in tasks
    )
    by_assignee = Counter(t.assignee or "Unassigned" for t in tasks if not t.done)
    by_section = Counter(t.section or "No section" for t in tasks if not t.done)
    if bc.spec.wants("summary"):
        doc.add(
            KPIRow(
                [
                    Kpi("Tasks", str(len(tasks)), len(tasks)),
                    Kpi(
                        "Open",
                        str(status["Open"] + status["Overdue"]),
                        status["Open"] + status["Overdue"],
                    ),
                    Kpi("Overdue", str(status["Overdue"]), status["Overdue"]),
                    Kpi("Completed", str(status["Completed"]), status["Completed"]),
                ]
            ),
            Heading("Open tasks by assignee", 2),
            Table(
                "Open tasks by assignee",
                ["Assignee", "Open tasks"],
                [[k, v] for k, v in by_assignee.most_common()],
            ),
            Chart(
                "Open tasks by assignee",
                "bar",
                [k for k, _ in by_assignee.most_common(12)],
                [float(v) for _, v in by_assignee.most_common(12)],
            ),
            Table(
                "Open tasks by section",
                ["Section", "Open tasks"],
                [[k, v] for k, v in by_section.most_common()],
            ),
            Chart("Tasks by status", "donut", list(status), [float(v) for v in status.values()]),
        )

    def cell(t: Any, f: Any) -> Any:
        v = values.get((t.id, f.id))
        if v is None:
            return None
        if f.type in ("single_select",):
            return option_label(f, v)
        if f.type == "multi_select" and isinstance(v, list):
            return ", ".join(x for x in (option_label(f, i) for i in v) if x)
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v

    if bc.spec.wants("tasks"):
        doc.add(
            Table(
                "Tasks",
                [
                    "Key",
                    "Title",
                    "Type",
                    "Project",
                    "Section",
                    "Assignee",
                    "Due",
                    "Completed",
                    "Tags",
                ]
                + [f.name for f in defs],
                [
                    [
                        t.key,
                        t.title,
                        t.type,
                        t.project,
                        t.section,
                        t.assignee,
                        t.due_on,
                        local_date(t.completed_at, bc.ctx),
                        ", ".join(t.tags) or None,
                    ]
                    + [cell(t, f) for f in defs]
                    for t in tasks
                ],
                sheet="Tasks",
            )
        )
    doc.facts = {"tasks": len(tasks), "status": dict(status)}
    return doc
