"""Phase 7.5 S75-06 ``momentum seed --onboarding``: the customer lifecycle demo.

What it adds (synthetic only, deterministic with ``random.Random(75)``, safe to re-run):

- The **Customer onboarding** project template (sections Pre-sales → Hypercare plus RAID, ~36
  tasks with milestones, owners as template roles, the task fields Waiting on / RAID type /
  Severity, the project fields Stage, Account owner, Contract value, Region, Target go-live and
  Products, and five rules that move the Stage when a milestone is completed).
- Two personas (Sofia Reyes, sales; Dev Patel, discovery) and a **Customer Success** team.
- **40 customers** made from the template, spread over the stages (Pre-sales 8, Discovery 6,
  Contracts 5, Implementation 10, Go-live 3, Hypercare 3, Live 3, Lost 1, On hold 1) with six
  months of stage history around the targets (some breaches), work done up to the current stage,
  waiting-on-customer tasks, open RAID items, files, comments, status updates and forecasts.
- The **Customer onboarding** rule portfolio (template = Customer onboarding) with the stage
  field, SLA targets, gates and default columns, then a 180-day snapshot backfill.

Everything goes through the services (activity, history rows, events) except the backdating of
timestamps, which a seed has to write directly. The template's rules start after the seeded
history (their ``created_at`` is moved past it), so the rules executor never replays the seed.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import momentum.models  # noqa: F401 - every model registered, so foreign keys resolve
from momentum.core.context import Actor, Ctx
from momentum.core.settings import Settings
from momentum.domain.fields.models import FieldDef, ProjectFieldEvent, ProjectFieldValue
from momentum.domain.projects.models import Project
from momentum.domain.rules.models import Rule
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.templates.models import Template
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace
from momentum.seed import SEED_DOMAIN, seed

SEED = 75
TEMPLATE_NAME = "Customer onboarding"
PORTFOLIO_NAME = "Customer onboarding"
TEAM = "Customer Success"
HISTORY_DAYS = 182  # about six months

PERSONAS = [
    # (name, local-part, timezone)
    ("Sofia Reyes", "sofia", "America/Mexico_City"),
    ("Dev Patel", "dev", "Asia/Kolkata"),
]
TEAM_MEMBERS = ["sofia", "dev", "lena", "ravi", "mei", "tom", "sam", "admin"]

STAGES = [
    "Pre-sales",
    "Discovery",
    "Contracts",
    "Implementation",
    "Go-live",
    "Hypercare",
    "Live",
    "Lost",
    "On hold",
]
LIFECYCLE = STAGES[:7]  # the path a customer walks; Lost and On hold step off it
TARGETS = {
    "Pre-sales": 30,
    "Discovery": 21,
    "Contracts": 14,
    "Implementation": 90,
    "Go-live": 14,
    "Hypercare": 30,
}
DISTRIBUTION = {
    "Pre-sales": 8,
    "Discovery": 6,
    "Contracts": 5,
    "Implementation": 10,
    "Go-live": 3,
    "Hypercare": 3,
    "Live": 3,
    "Lost": 1,
    "On hold": 1,
}
# the eval workspace's smaller draw from the same generator
SMALL_DISTRIBUTION = {
    "Pre-sales": 2,
    "Discovery": 2,
    "Contracts": 2,
    "Implementation": 3,
    "Go-live": 1,
    "Hypercare": 1,
    "Live": 1,
}
REGIONS = ["EMEA", "North America", "APAC", "LATAM"]
PRODUCTS = ["Core", "Analytics", "Integrations", "Mobile"]

# template roles → the persona each customer's project maps them to
ROLES = {
    "sales": ("Sales AE", "sofia"),
    "discovery": ("Discovery consultant", "dev"),
    "contracts": ("Contracts manager", "lena"),
    "lead": ("Implementation lead", "ravi"),
    "consultant": ("Consultant", "mei"),
    "consultant2": ("Consultant (2)", "tom"),
    "support": ("Go-live and support", "sam"),
}

# (section, [(title, role, milestone, day offset from the project start)])
SECTIONS: list[tuple[str, list[tuple[str, str, bool, int]]]] = [
    (
        "Pre-sales",
        [
            ("Qualify opportunity", "sales", False, 5),
            ("Demo", "sales", False, 12),
            ("Proposal", "sales", False, 20),
            ("Pricing approval", "sales", False, 26),
        ],
    ),
    (
        "Discovery",
        [
            ("Kickoff call", "discovery", False, 33),
            ("Current-state workshop", "discovery", False, 38),
            ("Requirements doc", "discovery", False, 44),
            ("Solution design", "discovery", False, 48),
            ("Discovery complete", "discovery", True, 51),
        ],
    ),
    (
        "Contracts",
        [
            ("Draft SOW", "contracts", False, 54),
            ("Quote", "contracts", False, 55),
            ("Legal review", "contracts", False, 59),
            ("Customer redlines", "contracts", False, 62),
            ("Contract signed", "contracts", True, 65),
        ],
    ),
    (
        "Implementation",
        [
            ("Implementation kickoff", "lead", True, 68),
            ("Environment setup", "consultant", False, 75),
            ("Data migration plan", "consultant2", False, 85),
            ("Configuration", "consultant", False, 110),
            ("Integrations", "consultant2", False, 125),
            ("Training plan", "lead", False, 130),
            ("UAT plan", "lead", False, 135),
            ("UAT", "consultant", False, 148),
            ("UAT sign-off", "lead", True, 155),
        ],
    ),
    (
        "Go-live",
        [
            ("Cutover plan", "support", False, 160),
            ("Go/no-go meeting", "lead", False, 165),
            ("Go-live", "support", True, 169),
            ("Post-go-live check", "support", False, 172),
        ],
    ),
    (
        "Hypercare",
        [
            ("Daily check-ins", "support", False, 185),
            ("Issue log review", "support", False, 192),
            ("Hypercare exit", "support", True, 199),
        ],
    ),
    (
        "RAID",
        [
            ("Risk: customer data quality", "lead", False, 90),
            ("Assumption: SSO through the customer's identity provider", "lead", False, 60),
            ("Issue: sandbox access delayed", "consultant", False, 80),
            ("Decision: mobile rollout in phase 2", "lead", False, 70),
        ],
    ),
]
RAID = {
    "Risk: customer data quality": ("Risk", "High"),
    "Assumption: SSO through the customer's identity provider": ("Assumption", "Medium"),
    "Issue: sandbox access delayed": ("Issue", "Medium"),
    "Decision: mobile rollout in phase 2": ("Decision", "Low"),
}
# milestone → the stage its completion moves the project into
RULES = [
    ("Discovery complete", "Contracts"),
    ("Contract signed", "Implementation"),
    ("UAT sign-off", "Go-live"),
    ("Go-live", "Hypercare"),
    ("Hypercare exit", "Live"),
]
ANALYZE_TABLES = (
    "projects",
    "tasks",
    "task_projects",
    "task_dependencies",
    "field_values",
    "project_field_values",
    "project_field_events",
    "status_updates",
    "forecasts",
    "project_snapshots",
    "attachments",
)
DEFAULT_COLUMNS = [
    "name",
    "stage",
    "field:Account owner",
    "field:Contract value",
    "status",
    "progress",
    "stage_age_days",
    "target_date",
    "forecast_date",
    "slip_days",
    "next_milestone",
    "waiting_on_customer",
]

COMPANIES = [
    "Northwind Health", "Bluepeak Logistics", "Cedar & Finch Legal", "Orbital Foods",
    "Harbor Point Bank", "Lumen Retail", "Quarry Lane Energy", "Silverline Clinics",
    "Tidewater Insurance", "Kestrel Aviation", "Maple Row Schools", "Vantage Hotels",
    "Redwood Utilities", "Sable Pharmaceuticals", "Copperleaf Farms", "Aster Telecom",
    "Granite Works", "Juniper Credit Union", "Polaris Freight", "Meridian Media",
    "Brightwater Water Co", "Falcon Ridge Mining", "Oakmont Realty", "Pioneer Robotics",
    "Starling Travel", "Willow Creek Dental", "Ironclad Security", "Lakeside Logistics",
    "Crescent Apparel", "Evergreen Pharmacy", "Summit Outdoor", "Nimbus Cloud Labs",
    "Halcyon Spa Group", "Riverbend Manufacturing", "Atlas Engineering", "Bramble Books",
    "Cobalt Automotive", "Driftwood Marine", "Elmstead Council", "Foxglove Florists",
    "Gilded Theatres", "Hollow Oak Brewery", "Indigo Fashion", "Jade Garden Restaurants",
]  # fmt: skip


@dataclass
class CustomerPlan:
    name: str
    stage: str
    region: str
    products: list[str]
    contract_value: int
    owner: str  # local-part
    path: list[tuple[str, int]]  # (stage, days spent there), oldest first; the last is current
    slipping: bool
    waiting: int  # tasks waiting on the customer
    start: date = field(default_factory=lambda: datetime.now(UTC).date())


def plan_customers(
    distribution: dict[str, int] | None = None, today: date | None = None, seed_: int = SEED
) -> list[CustomerPlan]:
    """The customers to create: names, stages and six months of stage history. Pure and
    deterministic (``random.Random(seed_)``), so tests and the eval workspace can reuse it."""
    rng = random.Random(seed_)  # noqa: S311 - deterministic synthetic data, not security
    today = today or datetime.now(UTC).date()
    distribution = distribution or DISTRIBUTION
    stages = [s for s, n in distribution.items() for _ in range(n)]
    names = rng.sample(COMPANIES, len(stages))
    plans: list[CustomerPlan] = []
    for name, stage in zip(names, stages, strict=True):
        if stage == "Lost":
            walk = LIFECYCLE[: rng.choice([2, 3])]  # lost in Discovery or Contracts
        elif stage == "On hold":
            walk = LIFECYCLE[: rng.choice([3, 4])]
        else:
            walk = LIFECYCLE[: LIFECYCLE.index(stage)]
        path: list[tuple[str, int]] = []
        for s in walk:
            target = TARGETS[s]
            breach = rng.random() < 0.2
            days = round(target * (rng.uniform(1.25, 1.8) if breach else rng.uniform(0.6, 1.05)))
            path.append((s, max(2, days)))
        target_now = TARGETS.get(stage, 30)
        late_now = rng.random() < 0.25
        age = round(target_now * (rng.uniform(1.1, 1.6) if late_now else rng.uniform(0.1, 0.9)))
        path.append((stage, max(1, age)))
        total = sum(d for _s, d in path)
        if total > HISTORY_DAYS:  # keep the whole history inside six months
            scale = HISTORY_DAYS / total
            path = [(s, max(1, round(d * scale))) for s, d in path]
        start = today - timedelta(days=sum(d for _s, d in path))
        plans.append(
            CustomerPlan(
                name=name,
                stage=stage,
                region=rng.choice(REGIONS),
                products=sorted(rng.sample(PRODUCTS, rng.randint(1, 3))),
                contract_value=rng.randrange(40, 400) * 1000,
                owner=rng.choice(["sofia", "ravi", "lena", "admin"]),
                path=path,
                slipping=late_now or rng.random() < 0.15,
                waiting=rng.randint(1, 3)
                if stage in ("Discovery", "Contracts", "Implementation")
                else 0,
                start=start,
            )
        )
    return plans


def _ctx(user: User, settings: Settings) -> Ctx:
    return Ctx(
        actor=Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            name=user.name,
            email=user.email,
            role=user.role,
            timezone=user.timezone,
        ),
        settings=settings,
    )


def _at(day: date, hour: int = 11) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=UTC)


class _Seeder:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        users: dict[str, User],
        quiet: tuple[str, ...] = (),
    ) -> None:
        self.s = session
        self.settings = settings
        self.users = users
        self.today = datetime.now(UTC).date()
        self.quiet = quiet

    def person(self, local: str) -> str:
        """A persona, unless it must stay quiet (the eval workspace keeps Lena's inbox empty):
        then Dev covers for them."""
        return "dev" if local in self.quiet else local

    def ctx(self, local: str) -> Ctx:
        return _ctx(self.users[local], self.settings)

    # ---------------- definitions ----------------

    async def team(self) -> Team:
        team = (
            await self.s.execute(
                select(Team).where(
                    Team.workspace_id == self.users["admin"].workspace_id, Team.name == TEAM
                )
            )
        ).scalar_one_or_none()
        if team is None:
            team = Team(
                workspace_id=self.users["admin"].workspace_id,
                name=TEAM,
                color="proj-3",
                created_by=self.users["ravi"].id,
            )
            self.s.add(team)
            await self.s.flush()
            self.s.add(TeamMember(team_id=team.id, user_id=self.users["ravi"].id, role="lead"))
            for local in TEAM_MEMBERS:
                if local != "ravi" and local not in self.quiet:
                    self.s.add(
                        TeamMember(team_id=team.id, user_id=self.users[local].id, role="member")
                    )
            await self.s.flush()
        return team

    async def project_fields(self) -> dict[str, FieldDef]:
        from momentum.domain.fields.project_values import (
            create_project_field,
            list_project_field_defs,
        )
        from momentum.domain.fields.schemas import FieldCreateIn, NumberOptions, SelectOptionIn

        have = {f.name: f for f in await list_project_field_defs(self.s, self.ctx("admin"))}
        wanted: list[tuple[str, str, list[str] | None]] = [
            ("Stage", "single_select", STAGES),
            ("Account owner", "people", None),
            ("Contract value", "currency", None),
            ("Region", "single_select", REGIONS),
            ("Target go-live", "date", None),
            ("Products", "multi_select", PRODUCTS),
        ]
        for name, type_, options in wanted:
            if name in have:
                await self._add_missing_options(have[name], options or [])
                continue
            m = await create_project_field(
                self.s,
                self.ctx("admin"),
                FieldCreateIn(
                    name=name,
                    type=type_,
                    options=[SelectOptionIn(label=o) for o in options]
                    if options
                    else (NumberOptions(precision=0, unit="EUR") if type_ == "currency" else None),
                ),
            )
            have[name] = m.entity
        return have

    async def _add_missing_options(self, f: FieldDef, labels: list[str]) -> None:
        """A field of that name already exists (another seed made it): keep its choices and
        their ids, and add the ones this demo needs."""
        from momentum.domain.fields.project_values import patch_project_field
        from momentum.domain.fields.schemas import FieldPatchIn, SelectOptionIn

        existing = [o for o in f.options or [] if isinstance(o, dict)]
        missing = [lb for lb in labels if lb not in {str(o.get("label")) for o in existing}]
        if not missing or f.type not in ("single_select", "multi_select"):
            return
        keep = [
            SelectOptionIn(id=str(o["id"]), label=str(o["label"]), color=str(o["color"]))
            for o in existing
        ]
        await patch_project_field(
            self.s,
            self.ctx("admin"),
            f.id,
            FieldPatchIn(options=[*keep, *(SelectOptionIn(label=lb) for lb in missing)]),
        )

    async def task_fields(self, home: uuid.UUID) -> dict[str, FieldDef]:
        """The template's task fields, created on a hidden home project (fields are born on a
        project) and kept in the library so the template attaches them."""
        from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn
        from momentum.domain.fields.service import create_field

        wanted = {
            "Waiting on": ["Customer", "Internal", "Third party"],
            "RAID type": ["Risk", "Assumption", "Issue", "Decision"],
            "Severity": ["High", "Medium", "Low"],
        }
        out: dict[str, FieldDef] = {}
        for name, options in wanted.items():
            f = (
                await self.s.execute(
                    select(FieldDef).where(
                        FieldDef.workspace_id == self.users["admin"].workspace_id,
                        FieldDef.name == name,
                        FieldDef.applies_to == "task",
                        FieldDef.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if f is None:
                m = await create_field(
                    self.s,
                    self.ctx("ravi"),
                    home,
                    FieldCreateIn(
                        name=name,
                        type="single_select",
                        options=[SelectOptionIn(label=o) for o in options],
                    ),
                )
                f = m.entity
            out[name] = f
        return out

    async def template(
        self, team: Team, pfields: dict[str, FieldDef], tfields: dict[str, FieldDef]
    ) -> Template:
        from momentum.domain.templates.service import save_template_payload

        found = (
            await self.s.execute(
                select(Template).where(
                    Template.workspace_id == team.workspace_id,
                    Template.name == TEMPLATE_NAME,
                    Template.kind == "project",
                    Template.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if found is not None:
            return found
        stage = pfields["Stage"]
        option = {str(o["label"]): str(o["id"]) for o in stage.options or []}

        def opt(f: FieldDef, label: str) -> str:
            return next(str(o["id"]) for o in f.options or [] if o["label"] == label)

        sections: list[dict[str, Any]] = []
        for sname, tasks in SECTIONS:
            specs: list[dict[str, Any]] = []
            for title, role, milestone, day in tasks:
                values: dict[str, Any] = {}
                if title in RAID:
                    raid, severity = RAID[title]
                    values[str(tfields["RAID type"].id)] = opt(tfields["RAID type"], raid)
                    values[str(tfields["Severity"].id)] = opt(tfields["Severity"], severity)
                specs.append(
                    {
                        "title": title,
                        "description": None,
                        "priority": "high" if milestone else None,
                        "due_offset_days": day,
                        "start_offset_days": None,
                        "role_id": role,
                        "field_values": values,
                        "subtasks": [],
                        "type": "milestone" if milestone else "task",
                    }
                )
            sections.append({"name": sname, "tasks": specs})
        rules = [
            {
                "name": f"{milestone} → {to}",
                "enabled": True,
                "trigger": {"type": "task.completed"},
                "conditions": [{"field": "title", "op": "eq", "value": milestone}],
                "actions": [
                    {"type": "set_project_field", "field_id": str(stage.id), "value": option[to]}
                ],
            }
            for milestone, to in RULES
        ]
        payload = {
            "roles": [{"id": rid, "label": label} for rid, (label, _l) in ROLES.items()],
            "fields": [str(f.id) for f in tfields.values()],
            "project_field_defaults": {str(stage.id): option["Pre-sales"]},
            "sections": sections,
            "rules": rules,
            "dependencies": [],
        }
        m = await save_template_payload(
            self.s,
            self.ctx("admin"),
            TEMPLATE_NAME,
            "A customer's lifecycle from pre-sales to hypercare: stages, milestones, RAID, and "
            "rules that move the Stage when a milestone is done.",
            payload,
        )
        return m.entity

    # ---------------- one customer ----------------

    async def customer(
        self,
        plan: CustomerPlan,
        team: Team,
        template: Template,
        pfields: dict[str, FieldDef],
        tfields: dict[str, FieldDef],
        rng: random.Random,
        files: bool,
    ) -> Project | None:
        from momentum.domain.comments.service import create_comment
        from momentum.domain.fields.project_values import set_project_field_value
        from momentum.domain.fields.service import set_task_field_value
        from momentum.domain.status_updates.schemas import StatusUpdateIn
        from momentum.domain.status_updates.service import create_status_update
        from momentum.domain.tasks.service import set_completed
        from momentum.domain.templates.schemas import NewProjectFromTemplateIn, RoleMapping
        from momentum.domain.templates.service import create_project_from_template

        exists = (
            await self.s.execute(
                select(Project.id).where(
                    Project.workspace_id == team.workspace_id,
                    Project.name == plan.name,
                    Project.deleted_at.is_(None),
                )
            )
        ).first()
        if exists is not None:
            return None
        lead = self.ctx("ravi")
        m = await create_project_from_template(
            self.s,
            lead,
            template.id,
            NewProjectFromTemplateIn(
                team_id=team.id,
                name=plan.name,
                start_date=plan.start,
                role_mapping=[
                    RoleMapping(role_id=rid, user_id=self.users[self.person(local)].id)
                    for rid, (_label, local) in ROLES.items()
                ],
            ),
        )
        project: Project = m.entity
        stage = pfields["Stage"]
        option = {str(o["label"]): str(o["id"]) for o in stage.options or []}

        # the other project fields
        go_live = plan.start + timedelta(days=170 + rng.randint(-10, 25))
        sets: list[tuple[FieldDef, Any]] = [
            (pfields["Account owner"], [str(self.users[self.person(plan.owner)].id)]),
            (pfields["Region"], option_id(pfields["Region"], plan.region)),
            (pfields["Target go-live"], go_live.isoformat()),
            (pfields["Products"], [option_id(pfields["Products"], p) for p in plan.products]),
        ]
        index = LIFECYCLE.index(plan.stage) if plan.stage in LIFECYCLE else len(plan.path) - 1
        if index >= 2 or plan.stage in ("Lost", "On hold"):  # priced once in Contracts
            sets.append((pfields["Contract value"], plan.contract_value))
        for f, value in sets:
            await set_project_field_value(self.s, lead, project.id, f.id, value)

        # the stage walk (Pre-sales came from the template's default)
        for s, _days in plan.path[1:]:
            await set_project_field_value(self.s, lead, project.id, stage.id, option[s])

        tasks = list(
            (
                await self.s.execute(
                    select(Task)
                    .join(TaskProject, TaskProject.task_id == Task.id)
                    .where(TaskProject.project_id == project.id, Task.parent_id.is_(None))
                    .order_by(Task.due_on, Task.title)
                )
            ).scalars()
        )
        by_title = {t.title: t for t in tasks}
        section_of = {title: sname for sname, ts in SECTIONS for title, *_r in ts}
        walked = [s for s, _d in plan.path]
        done_sections = set(walked[:-1]) if plan.stage not in ("Live",) else set(LIFECYCLE[:6])
        if plan.stage == "Live":
            done_sections = set(LIFECYCLE[:6])
        current = plan.path[-1][0]

        # complete the work of every stage passed, and part of the current one
        completions: list[tuple[uuid.UUID, date]] = []
        stage_start: dict[str, date] = {}
        day = plan.start
        for s, d in plan.path:
            stage_start[s] = day
            day = day + timedelta(days=d)
        for t in tasks:
            sname = section_of.get(t.title)
            if sname is None or sname == "RAID":
                continue
            finish: date | None = None
            if sname in done_sections:
                begin = stage_start.get(sname, plan.start)
                span = dict(plan.path).get(sname, 7)
                finish = begin + timedelta(days=rng.randint(0, max(0, span - 1)))
            elif (
                sname == current and plan.stage not in ("Lost", "On hold") and t.type != "milestone"
            ):
                if rng.random() < 0.4:
                    finish = stage_start[current] + timedelta(
                        days=rng.randint(0, max(0, (self.today - stage_start[current]).days))
                    )
            if finish is not None:
                await set_completed(self.s, lead, t.id, True, force=True)
                completions.append((t.id, min(finish, self.today)))
        # RAID: decisions and assumptions settle early; risks and issues stay open while live
        for title in RAID:
            raid_task = by_title.get(title)
            if raid_task is not None and plan.stage in ("Live",) and rng.random() < 0.7:
                await set_completed(self.s, lead, raid_task.id, True, force=True)
                completions.append((raid_task.id, self.today - timedelta(days=rng.randint(1, 20))))

        # dates: the plan's due dates move with the project's real pace; slipping projects have
        # their current work overdue
        for t in tasks:
            sname = section_of.get(t.title)
            if sname in stage_start and t.completed_at is None and sname == current:
                lateness = -rng.randint(3, 12) if plan.slipping else rng.randint(2, 20)
                await self.s.execute(
                    update(Task)
                    .where(Task.id == t.id)
                    .values(due_on=self.today + timedelta(days=lateness))
                )

        # waiting on the customer
        open_now = [
            t
            for t in tasks
            if section_of.get(t.title) == current and t.completed_at is None and t.type == "task"
        ]
        waiting = tfields["Waiting on"]
        for t in open_now[: plan.waiting]:
            await set_task_field_value(
                self.s, lead, t.id, waiting.id, option_id(waiting, "Customer")
            )

        # files the stages produce (the gate wants a signed contract from Implementation on)
        if files:
            await self.files(project, walked, plan, rng)

        # a comment on the work in hand, and a status update
        if open_now:
            await create_comment(
                self.s,
                self.ctx(rng.choice(["mei", "tom", "dev"])),
                open_now[0].id,
                _doc(f"Synced with {plan.name.split()[0]} today; next step agreed on the call."),
            )
        if plan.stage not in ("Pre-sales",):
            status = (
                "off_track"
                if plan.slipping and rng.random() < 0.5
                else "at_risk"
                if plan.slipping
                else "on_hold"
                if plan.stage == "On hold"
                else "complete"
                if plan.stage in ("Live", "Lost")
                else "on_track"
            )
            await create_status_update(
                self.s,
                lead,
                project.id,
                StatusUpdateIn(
                    status=status,
                    title=f"{plan.stage}: week update",
                    summary=(
                        "Behind the plan: waiting on the customer's data and sign-offs."
                        if plan.slipping
                        else "On plan for this stage."
                    ),
                ),
            )

        await self.backdate(project, plan, completions, stage.id)
        return project

    async def files(
        self, project: Project, walked: list[str], plan: CustomerPlan, rng: random.Random
    ) -> None:
        wanted: list[tuple[str, str]] = []
        if "Discovery" in walked:
            wanted.append(("kickoff.pptx", f"Kickoff - {plan.name}.pptx"))
        if "Contracts" in walked:
            wanted.append(("statement-of-work.docx", f"SOW - {plan.name}.docx"))
            wanted.append(("quote.xlsx", f"Quote - {plan.name}.xlsx"))
        if any(s in walked for s in LIFECYCLE[3:]):
            wanted.append(("contract-signed.pdf", f"Contract signed - {plan.name}.pdf"))
        if rng.random() < 0.3:
            wanted.append(("screenshot.png", f"Screenshot - {plan.name}.png"))
        for sample, name in wanted:
            await upload_sample(
                self.s, self.settings, self.ctx("ravi"), sample, name, project_id=project.id
            )

    async def backdate(
        self,
        project: Project,
        plan: CustomerPlan,
        completions: list[tuple[uuid.UUID, date]],
        stage_id: uuid.UUID,
    ) -> None:
        """Move the seeded history into the past: the project and its tasks were made on the
        plan's start, each stage was entered when the plan says, each task finished on its
        day. (A seed writes these directly; the app never backdates.)"""
        start = _at(plan.start, 9)
        await self.s.execute(
            update(Project).where(Project.id == project.id).values(created_at=start)
        )
        task_ids = select(TaskProject.task_id).where(TaskProject.project_id == project.id)
        await self.s.execute(update(Task).where(Task.id.in_(task_ids)).values(created_at=start))
        for task_id, day in completions:
            await self.s.execute(
                update(Task).where(Task.id == task_id).values(completed_at=_at(day, 15))
            )
        events = list(
            (
                await self.s.execute(
                    select(ProjectFieldEvent)
                    .where(ProjectFieldEvent.project_id == project.id)
                    .order_by(ProjectFieldEvent.at, ProjectFieldEvent.id)
                )
            ).scalars()
        )
        entered: list[datetime] = []
        day = plan.start
        for _s, d in plan.path:
            entered.append(_at(day, 10))
            day = day + timedelta(days=d)
        stage_events = [e for e in events if e.field_id == stage_id]
        for e, at in zip(stage_events, entered, strict=False):
            e.at = at
        for e in events:
            if e.field_id != stage_id:
                e.at = _at(plan.start, 10)
        await self.s.flush()


def option_id(f: FieldDef, label: str) -> str:
    return next(str(o["id"]) for o in f.options or [] if o["label"] == label)


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def upload_sample(
    session: AsyncSession,
    settings: Settings,
    owner: Ctx,
    sample: str,
    filename: str | None = None,
    **where: uuid.UUID,
) -> None:
    """A synthetic sample file (``momentum.files.samples``) stored and attached like an upload."""
    from momentum.core.ids import new_id
    from momentum.core.storage import build_storage
    from momentum.domain.attachments.service import create_attachment
    from momentum.files.samples import SAMPLES

    builder, mime = SAMPLES[sample]
    data = builder()
    key = f"{owner.workspace_id}/{new_id()}"

    async def one() -> Any:
        yield data

    await build_storage(settings).save_stream(key, one())
    await create_attachment(
        session,
        owner,
        storage_key=key,
        filename=filename or sample,
        mime=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        **where,  # type: ignore[arg-type]
    )


async def _ensure_personas(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    for name, local, tz in PERSONAS:
        email = f"{local}@{SEED_DOMAIN}"
        exists = (
            await session.execute(
                select(User.id).where(User.workspace_id == workspace_id, User.email == email)
            )
        ).first()
        if exists is None:
            session.add(
                User(workspace_id=workspace_id, email=email, name=name, role="member", timezone=tz)
            )
    await session.flush()


async def seed_onboarding(
    session: AsyncSession,
    settings: Settings,
    *,
    distribution: dict[str, int] | None = None,
    files: bool = True,
    backfill_days: int = 180,
    quiet: tuple[str, ...] = (),
    dashboards: bool = True,
) -> dict[str, int]:
    """The customer lifecycle demo on top of the base seed. Re-running adds nothing."""
    from momentum.domain.forecasts.service import store
    from momentum.domain.projects.snapshots import backfill

    await seed(session, settings)
    ws = await ensure_default_workspace(session, settings)
    exists = (
        await session.execute(
            select(Template.id).where(
                Template.workspace_id == ws.id,
                Template.name == TEMPLATE_NAME,
                Template.deleted_at.is_(None),
            )
        )
    ).first()
    if exists is not None:
        return {"onboarding_customers": 0}
    await _ensure_personas(session, ws.id)
    users = {
        u.email.split("@")[0]: u
        for u in (await session.execute(select(User).where(User.workspace_id == ws.id))).scalars()
    }
    w = _Seeder(session, settings, users, quiet)
    rng = random.Random(SEED)  # noqa: S311 - deterministic synthetic data, not security
    team = await w.team()
    pfields = await w.project_fields()
    home = await _home_project(w, team)
    tfields = await w.task_fields(home.id)
    template = await w.template(team, pfields, tfields)
    seeded_at = datetime.now(UTC)

    made: list[Project] = []
    for plan in plan_customers(distribution, w.today):
        project = await w.customer(plan, team, template, pfields, tfields, rng, files)
        if project is not None:
            made.append(project)

    portfolio = await _portfolio(w, template, pfields)
    # the template's rules start after the seeded history: never replay the seed
    await session.execute(
        update(Rule)
        .where(Rule.project_id.in_([p.id for p in made]))
        .values(created_at=seeded_at + timedelta(seconds=1))
    )
    system = Ctx(actor=Actor(id=None, workspace_id=ws.id), settings=settings, via="system")
    for p in made:
        await store(session, system, p)
    await _persona_touches(w, pfields, made)
    snapshots = await backfill(session, backfill_days) if backfill_days else 0
    if dashboards and portfolio is not None:
        await _role_dashboards(w, portfolio)
    # fresh statistics for the tables the seed filled: before autovacuum gets to them the
    # planner guesses, and the portfolio's rows took ~4 s instead of ~30 ms (measured)
    for table in ANALYZE_TABLES:
        await session.execute(text(f"ANALYZE {table}"))
    return {
        "onboarding_customers": len(made),
        "onboarding_portfolio": 1 if portfolio else 0,
        "onboarding_snapshots": snapshots,
    }


# Phase 7.5 S75-08 (D75-40): each persona's role dashboard, pinned to their Home
ROLE_DASHBOARDS = {
    "sales": "sofia",
    "discovery": "dev",
    "contracts": "lena",
    "implementation_lead": "ravi",
    "implementation_consultant": "mei",
    "golive_support": "sam",
    "leadership": "admin",
}


async def _persona_touches(w: _Seeder, pfields: dict[str, FieldDef], made: list[Project]) -> None:
    """Make sure each persona's own widgets have something to show: Sofia owns a customer that
    went live, has work due in the next two weeks on one of her accounts, and one of Mei's tasks
    waits on another."""
    from momentum.domain.fields.project_values import set_project_field_value
    from momentum.domain.tasks.service import add_dependency

    ids = [p.id for p in made]
    if not ids:
        return
    sofia = w.users[w.person("sofia")].id
    owner_field = pfields["Account owner"]
    live = option_id(pfields["Stage"], "Live")
    live_ids = [
        pid
        for pid, value in (
            await w.s.execute(
                select(ProjectFieldValue.project_id, ProjectFieldValue.value)
                .join(Project, Project.id == ProjectFieldValue.project_id)
                .where(
                    ProjectFieldValue.field_id == pfields["Stage"].id,
                    ProjectFieldValue.project_id.in_(ids),
                )
                .order_by(Project.name)
            )
        ).tuples()
        if value == live
    ]
    if live_ids:
        have = await w.s.get(ProjectFieldValue, (live_ids[0], owner_field.id))
        people = list(have.value) if have is not None and isinstance(have.value, list) else []
        if str(sofia) not in people:
            await set_project_field_value(
                w.s, w.ctx("ravi"), live_ids[0], owner_field.id, [*people, str(sofia)]
            )
    mine = (
        await w.s.execute(
            select(ProjectFieldValue.project_id).where(
                ProjectFieldValue.field_id == pfields["Account owner"].id,
                ProjectFieldValue.project_id.in_(ids),
                ProjectFieldValue.value.contains([str(sofia)]),
            )
        )
    ).scalars()
    open_sofia = list(
        (
            await w.s.execute(
                select(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id.in_(list(mine)),
                    Task.assignee_id == sofia,
                    Task.completed_at.is_(None),
                    Task.deleted_at.is_(None),
                )
                .order_by(Task.title, Task.id)
            )
        ).scalars()
    )
    soon = w.today + timedelta(days=14)
    if open_sofia and not any(t.due_on and w.today <= t.due_on <= soon for t in open_sofia):
        await w.s.execute(
            update(Task)
            .where(Task.id == open_sofia[0].id)
            .values(due_on=w.today + timedelta(days=6))
        )
    mei = w.users[w.person("mei")].id
    rows = (
        await w.s.execute(
            select(Task, TaskProject.project_id)
            .join(TaskProject, TaskProject.task_id == Task.id)
            .where(
                TaskProject.project_id.in_(ids),
                Task.completed_at.is_(None),
                Task.deleted_at.is_(None),
                Task.parent_id.is_(None),
                Task.type == "task",
            )
            .order_by(TaskProject.project_id, Task.title, Task.id)
        )
    ).all()
    by_project: dict[uuid.UUID, list[Task]] = {}
    for t, pid in rows:
        by_project.setdefault(pid, []).append(t)
    for tasks in by_project.values():
        waits = next((t for t in tasks if t.assignee_id == mei), None)
        on = next((t for t in tasks if t.assignee_id not in (mei, None)), None)
        if waits is not None and on is not None:
            await add_dependency(w.s, w.ctx("ravi"), waits.id, on.id)
            return


async def _role_dashboards(w: _Seeder, portfolio: Any) -> None:
    from momentum.domain.dashboards.service import create_from_template, pin

    for key, local in ROLE_DASHBOARDS.items():
        ctx = w.ctx(w.person(local))
        m, _notes = await create_from_template(w.s, ctx, key, portfolio.id)
        await pin(w.s, ctx, m.entity.id, True)


async def _home_project(w: _Seeder, team: Team) -> Project:
    """Where the template's task fields are born: an archived project of the team (fields are
    always created on a project); the fields stay in the library for the template."""
    from momentum.domain.projects.schemas import ProjectCreateIn
    from momentum.domain.projects.service import create_project, set_archived

    name = "Customer onboarding (fields)"
    found = (
        await w.s.execute(
            select(Project).where(Project.workspace_id == team.workspace_id, Project.name == name)
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    m = await create_project(w.s, w.ctx("ravi"), ProjectCreateIn(team_id=team.id, name=name))
    await set_archived(w.s, w.ctx("ravi"), m.entity.id, True)
    return m.entity


async def _portfolio(w: _Seeder, template: Template, pfields: dict[str, FieldDef]) -> Any:
    from momentum.domain.portfolios import lifecycle
    from momentum.domain.portfolios.schemas import (
        ConvertIn,
        PortfolioConfigIn,
        PortfolioIn,
        PortfolioRuleIn,
    )
    from momentum.domain.portfolios.service import create_portfolio

    admin = w.ctx("admin")
    m = await create_portfolio(
        w.s,
        admin,
        PortfolioIn(
            name=PORTFOLIO_NAME,
            description="Every customer made from the Customer onboarding template, by stage.",
        ),
    )
    p = m.entity
    await lifecycle.convert(
        w.s,
        admin,
        p.id,
        ConvertIn(
            kind="rule",
            # Live and Lost customers stay on the board (their status may be "complete")
            rule=PortfolioRuleIn(template_ids=[template.id], include_completed=True),
        ),
    )
    stage = pfields["Stage"]
    option = {str(o["label"]): str(o["id"]) for o in stage.options or []}
    columns = []
    for key in DEFAULT_COLUMNS:
        if key.startswith("field:"):
            key = f"field:{pfields[key.removeprefix('field:')].id}"
        columns.append({"key": key})
    await lifecycle.configure(
        w.s,
        admin,
        p.id,
        PortfolioConfigIn.model_validate(
            {
                "stage_field_id": str(stage.id),
                "stage_targets": {option[s]: d for s, d in TARGETS.items()},
                "stage_gates": {
                    option["Implementation"]: {
                        "required_fields": [str(pfields["Contract value"].id)],
                        "required_milestones": ["Contract signed"],
                        "required_files": ["*signed*"],
                    },
                    option["Go-live"]: {"required_milestones": ["UAT sign-off"]},
                    option["Live"]: {"required_milestones": ["Hypercare exit"]},
                },
                "columns": columns,
            }
        ),
    )
    for local, role in (("ravi", "editor"), ("sofia", "editor")):
        await lifecycle.set_member(w.s, admin, p.id, w.users[local].id, role)
    return p
