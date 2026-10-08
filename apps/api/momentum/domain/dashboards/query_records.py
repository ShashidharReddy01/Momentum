"""Phase 7.6 S76-04 (spec §6.6): dashboard widgets over records (entity ``records``) and their list
items (``record_lines``), computed by the records query engine as the viewer. Money is per
currency: a money measure shows one group per currency (``Acme · USD``), never a mixed total.
A type that isn't installed, or that has no records yet, gives an empty widget that says so."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards.query_scope import now_utc
from momentum.domain.dashboards.schemas import DrillOut, GroupOut, PointOut, QueryResultOut
from momentum.domain.dashboards.schemas_v2 import RecordsSpec
from momentum.domain.records import query as rq

DRILL_LIMIT = 50


def _query(s: RecordsSpec, *, window: int | None, kind: str) -> rq.RecordQuery:
    group: list[str] = []
    if s.time_bucket is not None:
        group = [f"{s.time_bucket}:{s.time_path}"]
    elif s.group_by is not None:
        group = [s.group_by]
    measure = rq.MeasureSpec(op=s.measure, path=s.measure_path)
    days = window or s.window_days
    return rq.RecordQuery(
        type=s.type,
        project_ids=s.project_ids,
        status=s.status,
        filters=s.filters,
        group_by=group,
        measures=[measure],
        array=s.array if s.entity == "record_lines" else None,
        date_from=(now_utc().date() - timedelta(days=days)) if days else None,
        order="group" if s.time_bucket else "value_desc",
        limit=s.limit if kind != "line" else 200,
    )


def _label(row: rq.QueryRow, key: str) -> str:
    base = "" if row.group.get(key) is None else str(row.group[key])
    base = base or "None"
    return f"{base} · {row.currency}" if row.currency else base


async def run_records(
    session: AsyncSession, ctx: Ctx, kind: str, s: RecordsSpec, *, window: int | None = None
) -> QueryResultOut:
    measure_name = s.measure if s.measure_path is None else f"{s.measure} of {s.measure_path}"
    what = "record items" if s.entity == "record_lines" else "records"
    out = QueryResultOut(
        kind=kind,
        measure=s.measure,
        entity=s.entity,
        description=f"{measure_name.capitalize()} of {s.type} {what}",
        total=0,
        tasks_total=0,
        computed_at=now_utc(),
    )
    try:
        result = await rq.run_query(session, ctx, _query(s, window=window, kind=kind))
    except ValidationFailed as e:
        if "No record type" in e.detail:
            out.notes = [f"No {s.type} records yet"]
            return out
        raise
    out.notes = list(result.notes)
    out.tasks_total = result.matched
    if result.matched == 0 and not out.notes:
        out.notes = [f"No {s.type} records match yet"]
    values = [r.values[result.measures[0]] or 0.0 for r in result.rows]
    out.total = float(sum(values))
    if kind in ("count", "kpi"):
        currencies = {r.currency for r in result.rows if r.currency}
        if len(currencies) > 1:
            out.value = None
            out.groups = [
                GroupOut(key=r.currency or "", label=r.currency or "", value=v, tasks=0)
                for r, v in zip(result.rows, values, strict=True)
            ]
            out.notes.append("More than one currency: see each one")
        else:
            out.value = values[0] if values else 0.0
    elif kind == "line":
        key = result.group_by[0] if result.group_by else ""
        for r, v in zip(result.rows, values, strict=True):
            start = r.group.get(key)
            if not start:
                continue
            d = date.fromisoformat(str(start))
            end = _bucket_end(d, s.time_bucket or "month")
            out.series.append(PointOut(start=d, end=end, value=v, tasks=0))
    else:
        key = result.group_by[0] if result.group_by else ""
        out.groups = [
            GroupOut(key=_label(r, key), label=_label(r, key), value=v, tasks=0)
            for r, v in zip(result.rows, values, strict=True)
        ]
    return out


def _bucket_end(d: date, bucket: str) -> date:
    if bucket == "day":
        return d
    if bucket == "week":
        return d + timedelta(days=6)
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


async def drill_records(
    session: AsyncSession, ctx: Ctx, s: RecordsSpec, key: str | None, limit: int
) -> DrillOut:
    """The records behind a mark: a group's (by its label) or all of them."""
    from momentum.domain.records.service import list_records

    rows, _total = await list_records(
        session, ctx, type=s.type, status=s.status or None, limit=min(limit, DRILL_LIMIT) * 4
    )
    picked: list[Any] = []
    for r in rows:
        if s.project_ids and r.project_id not in s.project_ids:
            continue
        if key and s.group_by:
            from momentum.domain.records import paths

            label = str(paths.get(r.data, s.group_by)) if "[" not in s.group_by else ""
            want = key.split(" · ")[0]
            if label != want or (" · " in key and r.currency != key.split(" · ")[1]):
                continue
        picked.append(r)
    return DrillOut(
        label=key or s.type,
        tasks=[],
        total=len(picked),
        entity="records",
        records=[
            {
                "id": str(r.id),
                "title": r.title,
                "status": r.status,
                "amount": str(r.amount) if r.amount is not None else None,
                "currency": r.currency,
            }
            for r in picked[:limit]
        ],
    )
