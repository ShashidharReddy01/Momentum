"""Phase 7.6 S76-04 (spec §6.6): the records query engine, used by the API, Mo, dashboards and
exports. Numbers are always computed here, as the viewer, never by a model.

``RecordQuery{type, filters, group_by, measures, array, ...}``:
- **paths** come from the record's data (``vendor.name``) or, with ``array="lines"``, from each
  item (``lines[].amount``), unnested with ``jsonb_array_elements`` under the parent's filters;
  ``month:<date path>`` (or ``day``/``week``/``quarter``/``year``) buckets a date; ``status``,
  ``currency``, ``occurred_on``, ``amount`` and ``title`` are the record's own columns;
- **money is summed per currency**: a money measure without a single-currency filter is grouped
  by currency, so different currencies are never added together;
- **caps**: 50,000 records scanned (the rest is reported in ``notes``) and 200 groups.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, Numeric, Text, and_, cast, func, literal_column, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.records import paths
from momentum.domain.records.models import Record, RecordType
from momentum.domain.records.schemas import PathStr
from momentum.domain.records.service import CLASSIFIED, visible

MAX_SCAN = 50_000
MAX_GROUPS = 200
BUCKETS = ("day", "week", "month", "quarter", "year")
COLUMNS = ("status", "amount", "currency", "occurred_on", "title", "confidence")


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=200, description="A data path, or a column: status, currency…")
    op: Literal["eq", "ne", "in", "gte", "lte", "contains", "empty", "set"] = "eq"
    value: Any = None


class MeasureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["count", "sum", "avg", "min", "max"] = "count"
    path: PathStr | None = None

    @model_validator(mode="after")
    def _path(self) -> MeasureSpec:
        if (self.op == "count") != (self.path is None):
            raise ValueError("count takes no path; sum, avg, min and max need one")
        return self

    @property
    def label(self) -> str:
        return self.op if self.path is None else f"{self.op}({self.path})"


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=60)
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    status: list[str] = Field(default_factory=list, max_length=7)
    entity_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    measures: list[MeasureSpec] = Field(
        default_factory=lambda: [MeasureSpec(op="count")], min_length=1, max_length=4
    )
    array: str | None = Field(default=None, pattern=r"^[a-z_][a-z0-9_]*$")
    order: Literal["value_desc", "value_asc", "group"] = "value_desc"
    limit: int = Field(default=50, ge=1, le=MAX_GROUPS)


class QueryRow(BaseModel):
    group: dict[str, Any]
    values: dict[str, float | None]
    value: float | None = Field(default=None, description="The first measure's value")
    currency: str | None = None


class QueryResult(BaseModel):
    type: str
    rows: list[QueryRow]
    matched: int
    scanned: int
    truncated: bool
    measures: list[str]
    group_by: list[str]
    notes: list[str] = Field(default_factory=list)


class _Paths:
    """Paths as SQL over ``records.data``, or over the unnested item (``item``) of ``array``."""

    def __init__(self, display: dict[str, Any], array: str | None, item: Any) -> None:
        self.money = set(display.get("money") or [])
        self.currency_field: str | None = display.get("currency_field")
        self.array = array
        self.item = item

    def is_money(self, path: str) -> bool:
        return path in self.money

    def text(self, path: str) -> ColumnElement[Any]:
        if path in COLUMNS:
            return cast(getattr(Record, path), Text)
        steps = paths.parse(path)
        base: Any = Record.data
        if steps[0][1] == "*":
            if self.array is None or steps[0][0] != self.array:
                raise ValidationFailed(f"{path} needs array={steps[0][0]!r}")
            base, steps = self.item, steps[1:]
        keys: list[str] = []
        for name, index in steps:
            if index == "*":
                raise ValidationFailed(f"{path}: only the query's array can be unnested")
            keys.append(name)
            if index is not None:
                keys.append(str(index))
        if not keys:
            raise ValidationFailed(f"{path} names a whole item")
        return base.op("#>>")(pg_array(keys, type_=Text))  # type: ignore[no-any-return]

    def number(self, path: str) -> ColumnElement[Any]:
        if path in ("amount", "confidence"):
            return getattr(Record, path)  # type: ignore[no-any-return]
        cleaned = func.nullif(func.regexp_replace(self.text(path), r"[^0-9.\-]", "", "g"), "")
        return cast(cleaned, Numeric(18, 4))

    def day(self, path: str) -> ColumnElement[Any]:
        if path == "occurred_on":
            return Record.occurred_on  # type: ignore[return-value]
        return cast(func.nullif(func.substr(self.text(path), 1, 10), ""), Date)

    def group(self, spec: str) -> ColumnElement[Any]:
        unit, sep, path = spec.partition(":")
        if sep and unit in BUCKETS:
            return func.to_char(func.date_trunc(unit, self.day(path)), "YYYY-MM-DD")
        return self.text(spec)

    def currency(self) -> ColumnElement[Any]:
        if self.currency_field:
            return func.upper(self.text(self.currency_field))
        return Record.currency  # type: ignore[return-value]


def _filter(f: Filter, p: _Paths) -> ColumnElement[bool]:
    v = f.value
    numeric = isinstance(v, int | float | Decimal) and not isinstance(v, bool)
    if f.op == "empty":
        e = p.text(f.path)
        return or_(e.is_(None), e == "")
    if f.op == "set":
        e = p.text(f.path)
        return and_(e.is_not(None), e != "")
    if f.op == "in":
        if not isinstance(v, list) or not 1 <= len(v) <= 50:
            raise ValidationFailed(f"{f.path}: 'in' takes a list of 1 to 50 values")
        return p.text(f.path).in_([str(x) for x in v])
    if f.op == "contains":
        return func.lower(p.text(f.path)).contains(str(v).lower(), autoescape=True)
    if numeric:
        e, value = p.number(f.path), Decimal(str(v))
    elif f.op in ("gte", "lte") and isinstance(v, str) and len(v) == 10 and v[4] == "-":
        e, value = p.day(f.path), date.fromisoformat(v)  # type: ignore[assignment]
    else:
        e, value = p.text(f.path), str(v)  # type: ignore[assignment]
    ops = {"eq": e == value, "ne": e != value, "gte": e >= value, "lte": e <= value}
    return ops[f.op]


async def type_display(session: AsyncSession, ctx: Ctx, key: str) -> RecordType:
    row = await session.scalar(
        select(RecordType)
        .where(RecordType.workspace_id == ctx.workspace_id, RecordType.key == key)
        .order_by(RecordType.version.desc())
        .limit(1)
    )
    if row is None:
        raise ValidationFailed(f"No record type {key!r} is installed")
    return row


async def run_query(session: AsyncSession, ctx: Ctx, q: RecordQuery) -> QueryResult:
    row = await type_display(session, ctx, q.type)
    labels = [m.label for m in q.measures]
    empty = QueryResult(
        type=q.type,
        rows=[],
        matched=0,
        scanned=0,
        truncated=False,
        measures=labels,
        group_by=q.group_by,
    )
    if ctx.actor.role == "guest" and row.classification in CLASSIFIED:
        empty.notes = ["Guests can't see these records"]
        return empty
    if q.array and q.array != "checks" and q.array not in (row.display.get("arrays") or {}):
        raise ValidationFailed(f"{q.type} has no list {q.array!r}")
    item = None
    if q.array:
        # "checks" is every record's own list of check results (spec §6.2), not a data field
        source = Record.checks if q.array == "checks" else Record.data.op("->")(q.array)
        item = (
            func.jsonb_array_elements(func.coalesce(source, cast("[]", JSONB)))
            .table_valued("value")
            .alias("item")
        )
    p = _Paths(row.display, q.array, item.c.value if item is not None else None)
    item_prefix = f"{q.array}[]" if q.array else None

    # the records in scope, newest first, capped
    scope = select(Record.id, Record.created_at).where(
        await visible(session, ctx), Record.type == q.type
    )
    if q.project_ids:
        scope = scope.where(Record.project_id.in_(q.project_ids))
    scope = scope.where(
        Record.status.in_(q.status) if q.status else Record.status.not_in(("void", "superseded"))
    )
    if q.entity_id:
        scope = scope.where(Record.entity_ids.contains([q.entity_id]))
    if q.date_from:
        scope = scope.where(Record.occurred_on >= q.date_from)
    if q.date_to:
        scope = scope.where(Record.occurred_on <= q.date_to)
    for f in q.filters:
        if not (item_prefix and f.path.startswith(item_prefix)):
            scope = scope.where(_filter(f, p))
    matched = int(await session.scalar(select(func.count()).select_from(scope.subquery())) or 0)
    notes: list[str] = []
    if matched > MAX_SCAN:
        notes.append(f"Only the latest {MAX_SCAN:,} of {matched:,} records were counted")
    capped = scope.order_by(Record.created_at.desc()).limit(MAX_SCAN).subquery()

    # what to group by, and money per currency
    money = any(m.path and p.is_money(m.path) for m in q.measures)
    one_currency = any(f.op == "eq" and f.path in ("currency", p.currency_field) for f in q.filters)
    group_specs = list(q.group_by)
    by_currency = money and not one_currency and "currency" not in group_specs
    cols = [p.group(g).label(f"g{i}") for i, g in enumerate(group_specs)]
    if by_currency:
        cols.append(p.currency().label("cur"))
        notes.append("Amounts are per currency; different currencies are never added together")
    measures = [
        (func.count() if m.op == "count" else getattr(func, m.op)(p.number(m.path or ""))).label(
            f"m{i}"
        )
        for i, m in enumerate(q.measures)
    ]
    stmt = select(*cols, *measures).select_from(Record)
    if item is not None:
        stmt = stmt.join(item, true())
        for f in q.filters:
            if item_prefix and f.path.startswith(item_prefix):
                stmt = stmt.where(_filter(f, p))
    stmt = stmt.where(Record.id.in_(select(capped.c.id)))
    if cols:
        stmt = stmt.group_by(*[literal_column(c.name) for c in cols])
        if q.order == "group":
            stmt = stmt.order_by(*[literal_column(c.name) for c in cols])
        else:
            m0: ColumnElement[Any] = literal_column("m0")
            stmt = stmt.order_by(
                m0.desc().nulls_last() if q.order == "value_desc" else m0.asc().nulls_last()
            )
        stmt = stmt.limit(min(q.limit, MAX_GROUPS) + 1)
    out: list[QueryRow] = []
    for r in (await session.execute(stmt)).mappings():
        values = {
            m.label: float(r[f"m{i}"]) if r[f"m{i}"] is not None else None
            for i, m in enumerate(q.measures)
        }
        out.append(
            QueryRow(
                group={g: r[f"g{i}"] for i, g in enumerate(group_specs)},
                value=values[q.measures[0].label],
                values=values,
                currency=r["cur"] if by_currency else None,
            )
        )
    if len(out) > q.limit:
        notes.append(f"Showing the first {q.limit} groups")
        out = out[: q.limit]
    return QueryResult(
        type=q.type,
        rows=out,
        matched=matched,
        scanned=min(matched, MAX_SCAN),
        truncated=matched > MAX_SCAN,
        measures=labels,
        group_by=q.group_by,
        notes=notes,
    )
