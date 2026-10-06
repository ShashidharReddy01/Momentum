"""Phase 7.5 S75-06: ``momentum seed --onboarding``. Counts per stage, the template (milestones,
fields, rules), gates consistent with each customer's stage, history inside six months, the rule
portfolio's board, the rules firing on a project made from the template, determinism and
re-running adding nothing."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.fields.models import FieldDef, ProjectFieldEvent
from momentum.domain.portfolios.gates import readiness
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import ViewSpec, portfolio_rows_v2
from momentum.domain.projects.models import Project, ProjectSnapshot
from momentum.domain.rules.engine import run_rules
from momentum.domain.rules.models import Rule
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.templates.models import Template
from momentum.seed_onboarding import (
    DISTRIBUTION,
    PORTFOLIO_NAME,
    STAGES,
    TEMPLATE_NAME,
    plan_customers,
    seed_onboarding,
)
from tests.helpers import Clients, ctx_for


def test_the_plan_is_deterministic_and_inside_six_months() -> None:
    today = datetime(2026, 10, 6, tzinfo=UTC).date()
    a, b = plan_customers(today=today), plan_customers(today=today)
    assert [(p.name, p.stage, p.path) for p in a] == [(p.name, p.stage, p.path) for p in b]
    assert Counter(p.stage for p in a) == Counter(DISTRIBUTION)
    assert len({p.name for p in a}) == 40
    assert all(p.start >= today - timedelta(days=183) for p in a)
    assert any(p.slipping for p in a) and not all(p.slipping for p in a)


async def test_seed_onboarding_builds_the_lifecycle_demo(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    async with uow.transaction() as s:
        out = await seed_onboarding(s, settings, backfill_days=30)
    assert out["onboarding_customers"] == 40 and out["onboarding_portfolio"] == 1
    assert out["onboarding_snapshots"] > 0
    async with uow.transaction() as s:
        again = await seed_onboarding(s, settings, backfill_days=30)
    assert again == {"onboarding_customers": 0}  # re-running adds nothing

    ctx = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        template = (
            await s.execute(select(Template).where(Template.name == TEMPLATE_NAME))
        ).scalar_one()
        assert len(template.payload["rules"]) == 5
        milestones = [
            t["title"]
            for sec in template.payload["sections"]
            for t in sec["tasks"]
            if t.get("type") == "milestone"
        ]
        assert "Contract signed" in milestones and "Hypercare exit" in milestones
        n_tasks = sum(len(sec["tasks"]) for sec in template.payload["sections"])
        assert 34 <= n_tasks <= 40

        portfolio = (
            await s.execute(select(Portfolio).where(Portfolio.name == PORTFOLIO_NAME))
        ).scalar_one()
        assert portfolio.kind == "rule" and portfolio.stage_field_id is not None
        stage = await s.get(FieldDef, portfolio.stage_field_id)
        assert stage is not None
        label = {o["id"]: o["label"] for o in stage.options or []}
        rows = await portfolio_rows_v2(s, ctx, portfolio, ViewSpec(group_by="stage"))
        assert len(rows.rows) == 40 and rows.hidden == 0
        counts = {g.label: g.rollup["count"] for g in rows.groups or []}
        assert {k: v for k, v in counts.items() if v} == DISTRIBUTION
        assert list(counts)[: len(STAGES)] == STAGES  # every stage shows, in order

        # gates hold for every customer past them; history fits in six months
        oldest = datetime.now(UTC) - timedelta(days=190)
        for r in rows.rows:
            project = await s.get(Project, r["id"])
            assert project is not None and project.template_id == template.id
            current = label[r["stage"]["option_id"]]
            for gated in ("Implementation", "Go-live", "Live"):
                if STAGES.index(current) >= STAGES.index(gated) and current in STAGES[:7]:
                    option = next(k for k, v in label.items() if v == gated)
                    check = await readiness(s, portfolio, project, option)
                    assert check.met, (project.name, current, gated, check.missing)
            first = (
                await s.execute(
                    select(func.min(ProjectFieldEvent.at)).where(
                        ProjectFieldEvent.project_id == project.id
                    )
                )
            ).scalar_one()
            assert first is not None and first >= oldest
        assert any(r["waiting_on_customer"] for r in rows.rows)
        assert any(r["stage_age_days"] and r["stage_age_days"] > 30 for r in rows.rows)
        snaps = (await s.execute(select(func.count()).select_from(ProjectSnapshot))).scalar_one()
        assert snaps > 0
        # the seed's history is never replayed by the template's rules
        rule_times = (
            await s.execute(select(func.min(Rule.created_at)).where(Rule.project_id.is_not(None)))
        ).scalar_one()
        assert rule_times is not None


async def test_rules_fire_on_a_project_made_from_the_template(
    uow: UnitOfWork, settings: Settings, as_user: Clients, session_factory: object
) -> None:
    async with uow.transaction() as s:
        await seed_onboarding(s, settings, files=False, backfill_days=0)
    ravi = await as_user("ravi")
    templates = (await ravi.get("/api/v1/templates?kind=project")).json()["data"]
    template = next(t for t in templates if t["name"] == TEMPLATE_NAME)
    teams = {t["name"]: t["id"] for t in (await ravi.get("/api/v1/teams")).json()["data"]}
    made = await ravi.post(
        f"/api/v1/templates/{template['id']}/new-project",
        json={
            "team_id": teams["Customer Success"],
            "name": "Fresh customer",
            "start_date": datetime.now(UTC).date().isoformat(),
        },
    )
    assert made.status_code == 201, made.text
    pid = made.json()["data"]["id"]
    tasks = (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    signed = next(t for t in tasks if t["title"] == "Contract signed")
    assert signed["type"] == "milestone"
    r = await ravi.post(f"/api/v1/tasks/{signed['id']}/complete")
    assert r.status_code == 200, r.text
    async with uow.transaction() as s:
        await run_rules(s, settings)
        stage = (
            await s.execute(
                select(FieldDef).where(FieldDef.name == "Stage", FieldDef.applies_to == "project")
            )
        ).scalar_one()
        stage_id = str(stage.id)
        label = {o["id"]: o["label"] for o in stage.options or []}
        value_id = (
            await s.execute(select(FieldDef.id).where(FieldDef.name == "Contract value"))
        ).scalar_one()

    async def current() -> str:
        rows = (await ravi.get(f"/api/v1/projects/{pid}/project-field-values")).json()["data"]
        return label[next(v["value"] for v in rows if v["field_id"] == stage_id)]

    # the new project joined the lifecycle portfolio, whose Implementation gate isn't met yet:
    # the rule never overrides it
    assert await current() == "Pre-sales"
    # meet the gate (value, signed contract), complete the milestone again: the stage moves
    r = await ravi.put(
        f"/api/v1/projects/{pid}/project-field-values/{value_id}", json={"value": 90000}
    )
    assert r.status_code == 200, r.text
    up = await ravi.post(
        f"/api/v1/projects/{pid}/files",
        files={"file": ("Fresh - contract signed.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
    )
    assert up.status_code == 201, up.text
    await ravi.post(f"/api/v1/tasks/{signed['id']}/uncomplete")
    await ravi.post(f"/api/v1/tasks/{signed['id']}/complete")
    async with uow.transaction() as s:
        await run_rules(s, settings)
    assert await current() == "Implementation"
    async with uow.transaction() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(TaskProject.project_id == uuid.UUID(pid), Task.type == "milestone")
            )
        ).scalar_one()
        assert n >= 6
