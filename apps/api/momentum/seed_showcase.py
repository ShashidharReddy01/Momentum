"""Phase 6.5 ``momentum seed --showcase``: a synthetic workspace that exercises every screen and
state, for design reviews and the UI audit. Everything is created **through the services as
the real people** (so activity, notifications, mentions and search are genuine), with dates
relative to today. Safe to re-run: if the first showcase project exists, nothing is added.
Synthetic only.

What it fills, by surface:
- **List / Board / Timeline:** spans (start → due), milestones, dependency chains (one overdue
  blocker so the chain shows), subtasks with partial progress, all four priorities, estimates,
  unassigned and unscheduled tasks, a very long title, a recurring task, an approval, a task in
  two projects, overdue and done work (completions backdated so charts and forecasts have a
  history).
- **Pane:** descriptions, comments with @mentions, custom fields (single-select, number), tags.
- **Overview / Dashboards / Forecast:** project dates and brief, two status updates, starter
  dashboards (one with a chart drafted from a question), forecasts.
- **Portfolios / Goals / Workload:** a portfolio with a check-in, goals with a metric, linked work
  and a sub-goal, capacity overrides (someone away next week, a part-timer).
- **Inbox (admin):** mentions, an approval request, assignments; **Forms / Rules:** a request form
  with submissions and a rule; **Agents:** the starters installed (disabled).
- An empty project, for empty states.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import momentum.models  # noqa: F401 - every model registered, so foreign keys resolve
from momentum.core.context import Actor, Ctx
from momentum.core.settings import Settings
from momentum.domain.comments.service import create_comment
from momentum.domain.dashboards import service as dashboards
from momentum.domain.dashboards.schemas import DashboardIn, QuerySpec, VizIn, WidgetIn
from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn
from momentum.domain.fields.service import create_field, set_task_field_value
from momentum.domain.forecasts import service as forecasts
from momentum.domain.forms.models import Form
from momentum.domain.forms.schemas import FormIn, SubmitFormIn
from momentum.domain.forms.service import create_form, submit_form
from momentum.domain.goals import service as goals
from momentum.domain.goals.schemas import GoalCheckInIn, GoalIn, GoalMetric
from momentum.domain.portfolios import service as portfolios
from momentum.domain.portfolios.schemas import PortfolioIn
from momentum.domain.projects.models import Project
from momentum.domain.projects.schemas import ProjectCreateIn, ProjectPatchIn
from momentum.domain.projects.service import add_member, create_project, update_project
from momentum.domain.rules.schemas import RuleIn
from momentum.domain.rules.service import create_rule
from momentum.domain.sections.service import create_section, list_sections, rename_section
from momentum.domain.status_updates.schemas import StatusUpdateIn
from momentum.domain.status_updates.service import create_status_update
from momentum.domain.tags.service import add_task_tag
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User
from momentum.domain.workload import service as workload
from momentum.domain.workspace.service import ensure_default_workspace
from momentum.seed import seed

FIRST = "Atlas Website Relaunch"


def doc(*paragraphs: str | list[Any]) -> dict[str, Any]:
    """A rich-text document; a paragraph may mix text and ``("@", user)`` mentions."""
    content = []
    for p in paragraphs:
        parts = [p] if isinstance(p, str) else p
        nodes: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, tuple):
                user: User = part[1]
                nodes.append(
                    {
                        "type": "mention",
                        "attrs": {"id": str(user.id), "label": user.name, "kind": "user"},
                    }
                )
            else:
                nodes.append({"type": "text", "text": part})
        content.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "content": content}


class Showcase:
    def __init__(self, session: AsyncSession, settings: Settings, users: dict[str, User]) -> None:
        self.s = session
        self.settings = settings
        self.u = users
        self.today = datetime.now(UTC).date()
        self.ids: dict[str, uuid.UUID] = {}  # task title → id
        self.done: list[tuple[uuid.UUID, date, date]] = []  # (task, created, completed)

    def ctx(self, local: str) -> Ctx:
        u = self.u[local]
        return Ctx(
            actor=Actor(
                id=u.id,
                workspace_id=u.workspace_id,
                name=u.name,
                email=u.email,
                role=u.role,
                timezone=u.timezone,
            ),
            settings=self.settings,
        )

    def d(self, offset: int | None) -> date | None:
        return None if offset is None else self.today + timedelta(days=offset)

    async def project(
        self,
        owner: str,
        team: str,
        name: str,
        sections: list[str],
        *,
        color: str,
        privacy: str = "team",
        start: int | None = None,
        due: int | None = None,
        brief: str | None = None,
    ) -> tuple[Project, dict[str, uuid.UUID]]:
        ctx = self.ctx(owner)
        team_id = (await self.s.execute(select(Team.id).where(Team.name == team))).scalar_one()
        project = (
            await create_project(
                self.s,
                ctx,
                ProjectCreateIn(team_id=team_id, name=name, privacy=privacy, color=color),
            )
        ).entity
        (first,) = await list_sections(self.s, project.id)
        await rename_section(self.s, ctx, first.id, sections[0])
        secs = {sections[0]: first.id}
        prev = first.id
        for sname in sections[1:]:
            prev = (await create_section(self.s, ctx, project.id, sname, after_id=prev)).entity.id
            secs[sname] = prev
        patch: dict[str, Any] = {}
        if start is not None:
            patch["start_on"] = self.d(start)
        if due is not None:
            patch["due_on"] = self.d(due)
        if brief:
            patch["brief"] = doc(*brief.split("\n"))
        if patch:
            await update_project(self.s, ctx, project.id, ProjectPatchIn(**patch))
        return project, secs

    async def task(
        self,
        owner: str,
        project: Project,
        section: uuid.UUID,
        title: str,
        *,
        who: str | None = None,
        start: int | None = None,
        due: int | None = None,
        priority: str | None = None,
        hours: float | None = None,
        done: bool = False,
        tags: list[str] = (),  # type: ignore[assignment]
        subtasks: list[tuple[str, bool]] = (),  # type: ignore[assignment]
        description: str | None = None,
        milestone: bool = False,
        recurrence: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        ctx = self.ctx(owner)
        t = (
            await tasks.create_task(
                self.s,
                ctx,
                project.id,
                title,
                section_id=section,
                assignee_id=self.u[who].id if who else None,
                start_on=None if milestone else self.d(start),
                due_on=self.d(due),
                priority=priority,
                recurrence=recurrence,
                estimate_minutes=int(hours * 60) if hours else None,
            )
        ).entity[0]
        if description:
            await tasks.update_task(
                self.s, ctx, t.id, {"description": doc(*description.split("\n"))}
            )
        if milestone:
            await tasks.convert_task_type(self.s, ctx, t.id, "milestone")
        for tag in tags:
            await add_task_tag(self.s, ctx, t.id, None, tag)
        for sub, sub_done in subtasks:
            s = (await tasks.create_subtask(self.s, ctx, t.id, sub)).entity
            if sub_done:
                await tasks.set_completed(self.s, ctx, s.id, True)
        self.ids[title] = t.id
        if done:
            created = self.d(start if start is not None else (due or 0) - 5) or self.today
            finished = self.d(due) or self.today
            self.done.append((t.id, created - timedelta(days=3), finished))
        return t.id

    async def depends(self, owner: str, task: str, blocker: str) -> None:
        await tasks.add_dependency(self.s, self.ctx(owner), self.ids[task], self.ids[blocker])

    async def comment(self, who: str, task: str, *paragraphs: str | list[Any]) -> None:
        await create_comment(self.s, self.ctx(who), self.ids[task], doc(*paragraphs))

    async def finish(self, owner: str) -> None:
        """Complete the done tasks, then backdate them (synthetic history for charts and
        forecasts: created before they started, completed on their due day)."""
        for tid, _c, _f in self.done:
            await tasks.set_completed(self.s, self.ctx(owner), tid, True)
        for tid, created, finished in self.done:
            await self.s.execute(
                update(Task)
                .where(Task.id == tid)
                .values(
                    created_at=datetime.combine(created, time(10), tzinfo=UTC),
                    completed_at=datetime.combine(finished, time(16), tzinfo=UTC),
                )
            )
        self.done.clear()


async def seed_showcase(session: AsyncSession, settings: Settings) -> dict[str, int]:
    await seed(session, settings)
    ws = await ensure_default_workspace(session, settings)
    exists = (
        await session.execute(
            select(Project.id).where(Project.workspace_id == ws.id, Project.name == FIRST)
        )
    ).first()
    if exists is not None:
        return {"showcase_projects": 0}
    users = {
        u.email.split("@")[0]: u
        for u in (await session.execute(select(User).where(User.workspace_id == ws.id))).scalars()
    }
    w = Showcase(session, settings, users)
    S = "admin"  # Avery Admin
    out = {"showcase_projects": 0, "showcase_tasks": 0}

    # ---------- Atlas Website Relaunch (the richest project) ----------
    atlas, sec = await w.project(
        "ravi",
        "Product",
        FIRST,
        ["Discovery", "Design", "Build", "QA", "Launch"],
        color="proj-6",
        start=-42,
        due=35,
        brief=(
            "Relaunch the marketing site on the new design system before the November campaign."
            "\nDone means: new homepage, pricing and blog live, Core Web Vitals green, analytics "
            "verified.\nOut of scope: the customer portal and localisation."
        ),
    )
    await add_member(session, w.ctx("ravi"), atlas.id, users[S].id, "admin")
    T = w.task
    await T(
        "ravi",
        atlas,
        sec["Discovery"],
        "Stakeholder interviews",
        who="ravi",
        start=-42,
        due=-33,
        hours=8,
        done=True,
        tags=["Research"],
    )
    await T(
        "ravi",
        atlas,
        sec["Discovery"],
        "Analytics baseline report",
        who="priya",
        start=-38,
        due=-30,
        hours=6,
        done=True,
    )
    await T(
        "ravi",
        atlas,
        sec["Discovery"],
        "Competitive teardown of six sites",
        who="ana",
        start=-36,
        due=-26,
        hours=10,
        done=True,
        tags=["Research"],
    )
    await T(
        "ravi",
        atlas,
        sec["Discovery"],
        "Discovery readout",
        who="ravi",
        due=-24,
        milestone=True,
        done=True,
    )
    await T(
        "ravi",
        atlas,
        sec["Design"],
        "Information architecture v2",
        who="ana",
        start=-25,
        due=-14,
        hours=12,
        done=True,
        tags=["Design"],
    )
    await T(
        "ravi",
        atlas,
        sec["Design"],
        "Homepage wireframes",
        who="mei",
        start=-20,
        due=-9,
        hours=8,
        done=True,
        tags=["Design"],
    )
    await T(
        "ravi",
        atlas,
        sec["Design"],
        "Visual design system tokens",
        who="mei",
        start=-12,
        due=2,
        priority="high",
        hours=16,
        tags=["Design"],
        subtasks=[
            ("Colour tokens", True),
            ("Type scale", True),
            ("Spacing scale", True),
            ("Component states", False),
            ("Dark theme pass", False),
        ],
        description=(
            "Tokens for colour, type, spacing and radius, exported to the web app and Figma."
            "\nBlocking homepage build."
        ),
    )
    await T(
        "ravi",
        atlas,
        sec["Design"],
        "Pricing page design",
        who="mei",
        start=-6,
        due=6,
        priority="high",
        hours=10,
        tags=["Design", "Customer-facing"],
    )
    await T("ravi", atlas, sec["Design"], "Design sign-off", who="ravi", due=7, milestone=True)
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "Set up the web monorepo",
        who="diego",
        start=-18,
        due=-11,
        hours=8,
        done=True,
        tags=["Frontend"],
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "CMS content model",
        who="kim",
        start=-10,
        due=-2,
        priority="high",
        hours=12,
        tags=["Backend"],
        description="Content types for pages, posts, authors and pricing plans.",
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "Blog migration script",
        who="kim",
        start=-3,
        due=4,
        hours=6,
        tags=["Backend"],
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "Homepage build",
        who="diego",
        start=1,
        due=12,
        priority="medium",
        hours=20,
        tags=["Frontend"],
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "Pricing page build",
        who="diego",
        start=8,
        due=18,
        hours=14,
        tags=["Frontend", "Customer-facing"],
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        "Search integration",
        start=10,
        due=20,
        priority="medium",
        hours=10,
    )
    await T(
        "ravi",
        atlas,
        sec["Build"],
        (
            "Accessibility pass: keyboard navigation, focus order, colour contrast and "
            "screen-reader labels across every template"
        ),
        who="lena",
        start=14,
        due=21,
        priority="urgent",
        hours=8,
    )
    await T("ravi", atlas, sec["QA"], "Cross-browser QA", who="sam", start=18, due=26, hours=12)
    await T(
        "ravi",
        atlas,
        sec["QA"],
        "Load test the pricing API",
        who="priya",
        start=20,
        due=24,
        priority="low",
        hours=6,
    )
    await T("ravi", atlas, sec["QA"], "Bug bash", who="ravi", due=25, milestone=True)
    await T(
        "ravi",
        atlas,
        sec["Launch"],
        "Launch announcement copy",
        who="ana",
        start=22,
        due=30,
        hours=5,
        tags=["Customer-facing"],
    )
    await T(
        "ravi",
        atlas,
        sec["Launch"],
        "Go-live checklist",
        who="ravi",
        start=28,
        due=33,
        priority="urgent",
        hours=4,
    )
    await T("ravi", atlas, sec["Launch"], "Launch", who="ravi", due=35, milestone=True)
    await T(
        "ravi",
        atlas,
        sec["Launch"],
        "Weekly stakeholder update",
        who="ravi",
        due=2,
        hours=1,
        recurrence={"freq": "weekly", "interval": 1, "by_weekday": [4]},
    )
    await T("ravi", atlas, sec["Launch"], "Write FAQ entries", who="ana")
    await T("ravi", atlas, sec["Launch"], "Collect customer quotes")
    approval = await T(
        "ravi", atlas, sec["Launch"], "Approve the launch budget ($12k)", who=S, due=3
    )
    await tasks.convert_task_type(session, w.ctx("ravi"), approval, "approval")
    for task, blocker in [
        ("Pricing page design", "Information architecture v2"),
        ("Homepage build", "Homepage wireframes"),
        ("Homepage build", "Visual design system tokens"),
        ("Blog migration script", "CMS content model"),
        ("Pricing page build", "Pricing page design"),
        ("Cross-browser QA", "Homepage build"),
        ("Cross-browser QA", "Pricing page build"),
        ("Go-live checklist", "Cross-browser QA"),
        ("Launch", "Go-live checklist"),
        ("Design sign-off", "Pricing page design"),
    ]:
        await w.depends("ravi", task, blocker)
    stage = (
        await create_field(
            session,
            w.ctx("ravi"),
            atlas.id,
            FieldCreateIn(
                name="Stage",
                type="single_select",
                options=[SelectOptionIn(label=x) for x in ("Not started", "In review", "Approved")],
            ),
        )
    ).entity
    points = (
        await create_field(
            session, w.ctx("ravi"), atlas.id, FieldCreateIn(name="Story points", type="number")
        )
    ).entity
    opts = {o["label"]: o["id"] for o in stage.options or []}
    for title, label, pts in [
        ("Visual design system tokens", "In review", 8),
        ("Pricing page design", "In review", 5),
        ("Homepage build", "Not started", 13),
        ("CMS content model", "In review", 8),
        ("Pricing page build", "Not started", 8),
    ]:
        await set_task_field_value(session, w.ctx("ravi"), w.ids[title], stage.id, opts[label])
        await set_task_field_value(session, w.ctx("ravi"), w.ids[title], points.id, pts)
    await w.comment(
        "kim",
        "CMS content model",
        [
            "The pricing plans need a second schema pass. ",
            ("@", users[S]),
            " can you approve the extra two days?",
        ],
    )
    await w.comment(
        "ravi",
        "CMS content model",
        "Approved in principle; let's keep the blog migration unblocked first.",
    )
    await w.comment(
        "ana",
        "Pricing page design",
        [("@", users["ravi"]), " the annual toggle needs a decision before Thursday."],
    )
    await w.comment(
        "mei",
        "Visual design system tokens",
        ["Dark theme pass is next. ", ("@", users[S]), " want to review the contrast table?"],
    )
    await w.finish("ravi")
    await create_status_update(
        session,
        w.ctx("ravi"),
        atlas.id,
        StatusUpdateIn(
            status="on_track",
            title="Discovery and IA done",
            summary="Discovery closed on time; IA v2 approved.",
        ),
    )
    await create_status_update(
        session,
        w.ctx("ravi"),
        atlas.id,
        StatusUpdateIn(
            status="at_risk",
            title="CMS model is late",
            summary="The CMS content model slipped two days and blocks the blog migration.",
        ),
    )
    out["showcase_projects"] += 1

    # ---------- Mobile App 3.0 (private) ----------
    mobile, msec = await w.project(
        "priya",
        "Product",
        "Mobile App 3.0",
        ["To do", "Doing", "Review", "Done"],
        color="proj-8",
        privacy="private",
        start=-21,
        due=49,
    )
    await add_member(session, w.ctx("priya"), mobile.id, users["ravi"].id, "editor")
    await add_member(session, w.ctx("priya"), mobile.id, users[S].id, "viewer")
    # one row shape for the smaller projects: (title, section, who, start, due, priority,
    # hours, done); a None leaves that attribute unset
    who: str | None
    start: int | None
    due: int | None
    pr: str | None
    hrs: float | None
    for title, section, who, start, due, pr, hrs, done in [
        ("Offline sync design", "Done", "priya", -21, -12, "high", 10, True),
        ("Push notification settings", "Done", "mei", -15, -6, None, 6, True),
        ("Crash reporting setup", "Review", "diego", -8, 1, "medium", 4, False),
        ("New onboarding flow", "Doing", "mei", -4, 10, "high", 16, False),
        ("Biometric login", "Doing", "diego", -2, 9, "urgent", 12, False),
        ("App store screenshots", "To do", "ana", 20, 28, "low", 4, False),
        ("Beta tester recruitment", "To do", None, 12, 22, None, 3, False),
        ("Release notes 3.0", "To do", "priya", 40, 47, None, 2, False),
    ]:
        await T(
            "priya",
            mobile,
            msec[section],
            title,
            who=who,
            start=start,
            due=due,
            priority=pr,
            hours=hrs,
            done=done,
        )
    await w.depends("priya", "Biometric login", "Crash reporting setup")
    await w.depends("priya", "App store screenshots", "New onboarding flow")
    await w.finish("priya")
    out["showcase_projects"] += 1

    # ---------- Brand Campaign (marketing, a form and a rule) ----------
    brand, bsec = await w.project(
        "ana",
        "Marketing",
        "Q1 Brand Campaign",
        ["Ideas", "Writing", "Design", "Scheduled", "Published"],
        color="proj-1",
        start=-14,
        due=60,
    )
    for title, section, who, start, due, pr, hrs, done in [
        ("Campaign narrative", "Published", "ana", -14, -7, "high", 6, True),
        ("Hero video script", "Writing", "tom", -3, 6, "high", 8, False),
        ("Social calendar: January", "Scheduled", "lena", 2, 12, None, 5, False),
        ("Partner newsletter swap", "Ideas", "noor", None, None, "low", None, False),
        ("Billboard concepts", "Design", "mei", 5, 19, "medium", 12, False),
        ("Influencer shortlist", "Ideas", None, None, 15, None, 3, False),
        ("Press kit refresh", "Writing", "tom", 10, 24, None, 6, False),
    ]:
        await T(
            "ana",
            brand,
            bsec[section],
            title,
            who=who,
            start=start,
            due=due,
            priority=pr,
            hours=hrs,
            done=done,
        )
    await w.finish("ana")
    await tasks.add_task_to_project(
        session,
        w.ctx("ana"),
        w.ids["Launch announcement copy"],
        brand.id,
        section_id=bsec["Writing"],
    )
    form = (
        await create_form(
            session,
            w.ctx("ana"),
            FormIn(
                project_id=brand.id,
                name="Content request",
                section_id=bsec["Ideas"],
                description="Ask the marketing team for a post, a graphic or a newsletter item.",
                questions=[
                    {
                        "id": "q1",
                        "label": "What do you need?",
                        "required": True,
                        "maps_to": "title",
                    },
                    {"id": "q2", "label": "Details and links", "maps_to": "description"},
                    {"id": "q3", "label": "When do you need it?", "maps_to": "due_on"},
                ],
            ),
        )
    ).entity
    form_row = await session.get(Form, form.id)
    assert form_row is not None
    for title, days in [
        ("Customer story: Northwind", 9),
        ("Graphic for the hiring post", 4),
        ("Newsletter blurb for the beta", 14),
    ]:
        await submit_form(
            session,
            settings,
            form_row,
            SubmitFormIn(
                answers={"q1": title, "q2": "Requested through the form.", "q3": str(w.d(days))}
            ),
            submitted_by=users["sam"].id,
            ip_hash=None,
            rate_limited=False,
        )
    await create_rule(
        session,
        w.ctx("ana"),
        RuleIn.model_validate(
            {
                "name": "Tell Ana when something is published",
                "project_id": str(brand.id),
                "trigger": {"type": "task.moved", "to_section": str(bsec["Published"])},
                "conditions": [],
                "actions": [
                    {
                        "type": "notify_user",
                        "user_id": str(users["ana"].id),
                        "text": "A campaign item was published",
                    }
                ],
            }
        ),
    )
    out["showcase_projects"] += 1

    # ---------- IT Onboarding (operations) ----------
    it, isec = await w.project(
        "jordan",
        "Operations",
        "IT Onboarding",
        ["Requested", "In progress", "Done"],
        color="proj-4",
        start=-10,
        due=20,
    )
    for title, section, who, start, due, pr, hrs, done in [
        ("Laptop for new designer", "Done", "sam", -10, -6, None, 2, True),
        ("Accounts: email, chat, SSO", "In progress", "kim", -2, 1, "high", 2, False),
        ("Security training enrolment", "In progress", "diego", -1, 5, None, 1, False),
        ("Desk and badge", "Requested", None, 3, 6, "low", 1, False),
        ("Buddy assignment", "Requested", "jordan", None, 2, None, None, False),
    ]:
        await T(
            "jordan",
            it,
            isec[section],
            title,
            who=who,
            start=start,
            due=due,
            priority=pr,
            hours=hrs,
            done=done,
        )
    await w.finish("jordan")
    out["showcase_projects"] += 1

    # ---------- an empty project (empty states) ----------
    await w.project("sam", "Operations", "Office move (planning)", ["To do"], color="proj-10")
    out["showcase_projects"] += 1

    # ---------- portfolio, goals, dashboards, workload ----------
    pf = (
        await portfolios.create_portfolio(
            session,
            w.ctx(S),
            PortfolioIn(
                name="FY27 bets", description="The three projects leadership reviews weekly."
            ),
        )
    ).entity
    for p in (atlas, mobile, brand):
        await portfolios.add_project(session, w.ctx(S), pf.id, p.id)
    await portfolios.post_status(
        session,
        w.ctx(S),
        pf.id,
        StatusUpdateIn(
            status="at_risk",
            title="1 at risk, 2 on track",
            summary="Atlas is at risk on the CMS model; mobile and brand are on track.",
        ),
    )
    quarter_end = w.today + timedelta(days=60)
    relaunch = (
        await goals.create_goal(
            session,
            w.ctx("ravi"),
            GoalIn(
                name="Relaunch the website before the campaign",
                period_start=w.today - timedelta(days=30),
                period_end=quarter_end,
                period_label="This quarter",
                progress_source="projects",
            ),
        )
    ).entity
    await goals.link(session, w.ctx("ravi"), relaunch.id, "project", atlas.id)
    signups = (
        await goals.create_goal(
            session,
            w.ctx(S),
            GoalIn(
                name="Grow trial signups to 500 a month",
                period_start=w.today - timedelta(days=30),
                period_end=quarter_end,
                period_label="This quarter",
                progress_source="manual",
                metric=GoalMetric(type="number", start=220, target=500, current=260),
            ),
        )
    ).entity
    await goals.check_in(
        session,
        w.ctx(S),
        signups.id,
        GoalCheckInIn(status="on_track", title="Up to 310 after the pricing test", current=310),
    )
    child = (
        await goals.create_goal(
            session,
            w.ctx("ana"),
            GoalIn(
                name="Run the brand campaign",
                parent_id=signups.id,
                period_start=w.today - timedelta(days=14),
                period_end=quarter_end,
                progress_source="projects",
            ),
        )
    ).entity
    await goals.link(session, w.ctx("ana"), child.id, "project", brand.id)
    await dashboards.create_dashboard(session, w.ctx(S), DashboardIn(name="Leadership overview"))
    board = (
        await dashboards.create_dashboard(
            session, w.ctx("ravi"), DashboardIn(name="Atlas dashboard", project_id=atlas.id)
        )
    ).entity
    await dashboards.add_widget(
        session,
        w.ctx("ravi"),
        board.id,
        WidgetIn(
            kind="donut",
            title="Open work by priority",
            query_spec=QuerySpec(group_by="priority"),
            viz=VizIn(size="md"),
            created_from_prompt="Break down open work by priority",
        ),
    )
    monday = w.today - timedelta(days=w.today.weekday())
    await workload.set_week(session, w.ctx("ana"), users["ana"].id, monday + timedelta(days=7), 0)
    await workload.set_weekly_hours(session, w.ctx("mei"), users["mei"].id, 20)

    # ---------- agents (installed, switched off) and forecasts ----------
    from momentum.agents.loader import load_definitions
    from momentum.ai.tools.catalog import build_registry
    from momentum.domain.agents.service import install_definitions

    system = Ctx(
        actor=Actor(id=None, workspace_id=ws.id, role="admin"), settings=settings, via="system"
    )
    await install_definitions(session, system, load_definitions(), build_registry().names)
    for p in (atlas, mobile, brand, it):
        await forecasts.store(session, system, p)
    out["showcase_tasks"] = len(w.ids)
    await session.flush()
    return out
