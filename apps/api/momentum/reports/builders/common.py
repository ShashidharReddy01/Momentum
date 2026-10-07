"""Shared pieces for the report builders (spec §6.1): the build context and number words."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.reports.document import ReportDocument
from momentum.reports.spec import ReportSpec

STATUS_WORDS = {
    "on_track": "On track",
    "at_risk": "At risk",
    "off_track": "Off track",
    "on_hold": "On hold",
    "complete": "Complete",
}


@dataclass
class BuildContext:
    session: AsyncSession
    ctx: Ctx
    spec: ReportSpec
    today: date
    now: datetime

    def period(self, default_days: int = 7) -> tuple[date, date]:
        if self.spec.period is not None:
            return self.spec.period.start, self.spec.period.end
        return self.today - timedelta(days=default_days - 1), self.today

    def doc(self, title: str, subtitle: str) -> ReportDocument:
        who = self.ctx.actor.name or "someone"
        return ReportDocument(
            title=title,
            subtitle=subtitle,
            generated_at=self.now,
            generated_by=who,
            scope_note=f"Includes what {who} could see on {self.today:%d %b %Y}.",
        )


def pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def money(value: float | None, unit: str | None = None) -> str:
    if value is None:
        return "—"
    text = f"{value:,.0f}"
    return f"{text} {unit}" if unit else text


def day(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else "—"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"
