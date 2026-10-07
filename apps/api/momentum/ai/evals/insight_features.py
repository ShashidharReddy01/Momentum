"""Phase 7.5 S75-10 (spec §8): the eval runs for Mo on portfolios and dashboards, on the
onboarding_v1 eval workspace (the "Customer onboarding" portfolio and its role dashboards).

Cases name a customer by its stage (``customer_in: Hypercare``: the first one in that stage the
person can see, by name), so they don't depend on the generator's company names. What the
scorers read is put on the ``Observation``: the text Mo wrote, what it cited and what it could
have cited, the numbers it could use, and whether a model call happened at all.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import dashboard_draft, explain_chart, handoff, nl_filters, portfolio_brief
from momentum.ai import readiness_check as readiness_ai
from momentum.ai.evals.workspace import EvalWorld
from momentum.ai.grounding import numbers_in
from momentum.ai.llm import LLM
from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.domain.dashboards.models import Dashboard, DashboardWidget
from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import ViewSpec, portfolio_rows_v2

INSIGHT_FEATURES = (
    "portfolio_brief",
    "nl_filters",
    "dashboard_draft",
    "explain_chart",
    "readiness",
    "handoff",
)
PORTFOLIO = "Customer onboarding"


async def _portfolio(session: AsyncSession, name: str = PORTFOLIO) -> Portfolio:
    return (
        await session.execute(
            select(Portfolio).where(Portfolio.name == name, Portfolio.deleted_at.is_(None))
        )
    ).scalar_one()


async def _stage_option(session: AsyncSession, p: Portfolio, label: str) -> str:
    stage = await session.get(FieldDef, p.stage_field_id)
    assert stage is not None
    return next(str(o["id"]) for o in stage.options or [] if o.get("label") == label)


async def customer_in(session: AsyncSession, ctx: Ctx, p: Portfolio, stage: str) -> uuid.UUID:
    """The first customer (by name) in that stage the person can see."""
    rows = (await portfolio_rows_v2(session, ctx, p, ViewSpec())).rows
    hits = sorted(
        (r for r in rows if (r.get("stage") or {}).get("label") == stage), key=lambda r: r["name"]
    )
    if not hits:
        raise NotFound(f"no customer in {stage} for this person")
    return uuid.UUID(str(hits[0]["id"]))


async def _widget(session: AsyncSession, dashboard: str, title: str) -> uuid.UUID:
    return (
        await session.execute(
            select(DashboardWidget.id)
            .join(Dashboard, Dashboard.id == DashboardWidget.dashboard_id)
            .where(
                Dashboard.name == dashboard,
                Dashboard.deleted_at.is_(None),
                DashboardWidget.title == title,
                DashboardWidget.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one()


def _cited(obs_data: dict[str, Any], cites: list[str], citable: list[str]) -> None:
    obs_data["cites"] = cites
    obs_data["citables"] = citable


async def run_insight(
    session: AsyncSession,
    llm: LLM,
    world: EvalWorld,
    case: dict[str, Any],
    feature: str,
    ctx: Ctx,
    obs: Any,
) -> None:
    inp = str(case.get("input", ""))
    p = await _portfolio(session, case.get("portfolio", PORTFOLIO))
    if feature == "portfolio_brief":
        b = await portfolio_brief.brief(session, llm, ctx, p.id)
        obs.text = "\n".join([b.headline, *(i.text for i in b.items)])
        obs.data = {
            "paragraphs": len(b.items),
            "ai": b.ai,
            "hidden": b.hidden,
            "kinds": sorted({i.kind for i in b.items}),
            "facts_numbers": sorted(numbers_in(b.facts)),
        }
        _cited(obs.data, [c for i in b.items for c in i.cites], portfolio_brief.citables(b.facts))
    elif feature == "nl_filters":
        d = await nl_filters.draft_filters(session, llm, ctx, inp, "portfolio", portfolio_id=p.id)
        obs.clarified = d.question is not None
        obs.text = d.question or "\n".join(c.label for c in d.chips)
        obs.data = {"filters": d.named, "question": d.question, "options": d.options}
        if d.filters and not d.question:  # the filters run: how many projects they keep
            rows = await portfolio_rows_v2(session, ctx, p, ViewSpec(filters=d.filters))
            obs.data["rows"] = len(rows.rows)
    elif feature == "dashboard_draft":
        dd = await dashboard_draft.draft_dashboard(
            session, llm, ctx, inp, portfolio_id=p.id if case.get("on_portfolio") else None
        )
        obs.clarified = dd.question is not None
        obs.text = dd.question or "\n".join(
            [dd.name, *(w.title for w in dd.widgets), *dd.notes, *dd.left_out]
        )
        obs.data = {
            "draft": dashboard_draft.canonical(dd),
            "question": dd.question,
            "options": dd.options,
            "left_out": dd.left_out,
            "widgets_with_numbers": sum(1 for w in dd.widgets if w.result is not None),
            "widgets": len(dd.widgets),
        }
    elif feature == "explain_chart":
        wid = await _widget(session, case["dashboard"], case["widget"])
        e = await explain_chart.explain(session, llm, ctx, wid)
        obs.text = "\n".join(x.text for x in e.paragraphs)
        obs.data = {
            "paragraphs": len(e.paragraphs),
            "ai": e.ai,
            "links": len(e.links),
            "facts_numbers": sorted(numbers_in(e.facts)),
        }
        _cited(
            obs.data, [c for x in e.paragraphs for c in x.cites], explain_chart.citables(e.facts)
        )
    elif feature == "readiness":
        picker = world.ctx(case["pick_as"], ctx.settings) if case.get("pick_as") else ctx
        pid = await customer_in(session, picker, p, case["customer_in"])
        to = await _stage_option(session, p, case.get("to", "Implementation"))
        r = await readiness_ai.check(
            session, llm, ctx, p.id, pid, to, read_files=bool(case.get("read_files"))
        )
        obs.text = "\n".join(n.text for n in r.notes)
        obs.data = {
            "paragraphs": len(r.notes),
            "ai": r.ai,
            "met": r.readiness.met,
            "checklist": [[i.kind, i.met] for i in r.readiness.items],
            "files_read": len(r.files_read),
            "concerns": sum(1 for n in r.notes if n.concern),
        }
        _cited(
            obs.data,
            [c for n in r.notes for c in n.cites],
            [*r.files_read, *(i.label for i in r.readiness.items)],
        )
    elif feature == "handoff":
        picker = world.ctx(case["pick_as"], ctx.settings) if case.get("pick_as") else ctx
        pid = await customer_in(session, picker, p, case["customer_in"])
        h = await handoff.draft_handoff(
            session,
            llm,
            ctx,
            pid,
            to_stage=case.get("to"),
            read_files=bool(case.get("read_files")),
        )
        items = [i for v in h.sections.values() for i in v]
        obs.text = h.text()
        obs.data = {
            "paragraphs": len(items),
            "sections": sorted(h.sections),
            "files_read": len(h.files_read),
            "facts_numbers": sorted(numbers_in(h.facts)),
        }
        _cited(obs.data, [c for i in items for c in i.cites], handoff.citables(h.facts))
