"""Phase 7.5 (spec §4.5): table queries over a parsed sheet, computed by the server.

Any number Mo states about a spreadsheet comes from here (or ``read_sheet``): filters, up to two
group-by columns, aggregates (count, sum, avg, min, max, distinct count), sorting and a limit, in
Python over the cached rows, with typed comparisons per inferred column type (locale-tolerant
numbers, common date forms, booleans). Columns are named by header text or by letter.
"""

from __future__ import annotations

import re
import statistics
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum.files.model import Cell, SheetInfo, column_letter
from momentum.files.values import (
    as_bool,
    as_date,
    as_number,
    display,
    infer_day_first,
    infer_decimal,
    is_empty,
)

Op = Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in", "empty", "not_empty"]
Fn = Literal["count", "sum", "avg", "min", "max", "distinct_count"]


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=200)
    op: Op
    value: str | float | int | bool | list[str | float | int] | None = None


class Aggregate(BaseModel):
    fn: Fn
    column: str | None = Field(default=None, max_length=200)
    as_: str | None = Field(default=None, alias="as", max_length=60)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @property
    def label(self) -> str:
        return self.as_ or (f"{self.fn}({self.column})" if self.column else self.fn)


class Sort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str = Field(max_length=200)
    dir: Literal["asc", "desc"] = "asc"


class TableQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    aggregates: list[Aggregate] = Field(default_factory=list, max_length=10)
    sort: list[Sort] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=50, ge=1, le=200)


class QueryError(ValueError):
    """The query names a column that isn't there, or asks for something impossible."""


class TableResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    matched_rows: int  # data rows that passed the filters
    total_rows: int
    truncated: bool  # the result was limited, or the sheet itself was cut at parse time
    note: str | None = None


class _Col:
    def __init__(self, index: int, name: str, kind: str, values: list[Cell]):
        self.index = index
        self.name = name
        self.kind = kind
        texts = [v for v in values if isinstance(v, str)]
        self.decimal = infer_decimal(texts)
        self.day_first = infer_day_first(texts)

    def typed(self, v: Cell) -> Any:
        if is_empty(v):
            return None
        if self.kind in ("number", "percent"):
            return as_number(v, self.decimal)
        if self.kind == "date":
            return as_date(v, self.day_first)
        if self.kind == "bool":
            return as_bool(v)
        return display(v).strip()

    def coerce(self, value: Any) -> Any:
        """A filter value typed like this column."""
        if value is None:
            return None
        if self.kind in ("number", "percent"):
            if isinstance(value, bool):
                raise QueryError(f"{self.name} holds numbers")
            if isinstance(value, int | float):
                return float(value)
            n = as_number(str(value), self.decimal)
            if n is None:
                raise QueryError(f"{value!r} isn't a number ({self.name} holds numbers)")
            return n
        if self.kind == "date":
            d = as_date(str(value), self.day_first)
            if d is None:
                raise QueryError(f"{value!r} isn't a date ({self.name} holds dates)")
            return d
        if self.kind == "bool":
            b = as_bool(value if isinstance(value, bool) else str(value))
            if b is None:
                raise QueryError(f"{value!r} isn't true/false")
            return b
        return str(value).strip()


def _columns(info: SheetInfo, body: list[list[Cell]]) -> list[_Col]:
    return [
        _Col(i, c.name, c.inferred_type, [r[i] if i < len(r) else None for r in body])
        for i, c in enumerate(info.columns)
    ]


def _find(cols: list[_Col], name: str) -> _Col:
    """By header text (case-insensitive), else by column letter ("C")."""
    low = name.strip().lower()
    for c in cols:
        if c.name.lower() == low:
            return c
    if 1 <= len(low) <= 3 and low.isalpha():
        for c in cols:
            if column_letter(c.index) == low.upper():
                return c
    raise QueryError(f"No column named {name!r}. Columns: " + ", ".join(c.name for c in cols[:40]))


def _test(op: Op, cell: Any, target: Any, col: _Col) -> bool:
    if op == "empty":
        return cell is None
    if op == "not_empty":
        return cell is not None
    if op == "in":
        values = target if isinstance(target, list) else [target]
        typed = [col.coerce(v) for v in values]
        if isinstance(cell, str):
            return cell.lower() in {str(t).lower() for t in typed}
        return cell in typed
    if op == "contains":
        return cell is not None and str(target).lower() in display(cell).lower()
    t = col.coerce(target)
    if cell is None:
        return op == "ne"
    if isinstance(cell, str) and isinstance(t, str):
        a, b = cell.lower(), t.lower()
    else:
        a, b = cell, t
    try:
        return {
            "eq": a == b,
            "ne": a != b,
            "lt": a < b,
            "lte": a <= b,
            "gt": a > b,
            "gte": a >= b,
        }[op]
    except TypeError:
        return False


def _out(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    if isinstance(v, float):
        return round(v, 10)
    return v


def _aggregate(fn: Fn, col: _Col | None, rows: list[list[Any]]) -> Any:
    if fn == "count":
        if col is None:
            return len(rows)
        return sum(1 for r in rows if r[col.index] is not None)
    assert col is not None
    values = [r[col.index] for r in rows if r[col.index] is not None]
    if fn == "distinct_count":
        return len({str(v).lower() if isinstance(v, str) else v for v in values})
    if fn in ("sum", "avg"):
        nums = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
        if col.kind not in ("number", "percent"):
            raise QueryError(f"{col.name} isn't a number column, so it can't be summed or averaged")
        if not nums:
            return None
        return sum(nums) if fn == "sum" else statistics.fmean(nums)
    if not values:
        return None
    try:
        return min(values) if fn == "min" else max(values)
    except TypeError as e:
        raise QueryError(f"{col.name} mixes kinds of values") from e


_TOTAL_LABEL = re.compile(r"^(grand\s+|sub-?\s*)?totals?\s*:?$", re.IGNORECASE)


def _is_total_row(r: list[Any]) -> bool:
    """The sheet's own total line: its first text cell is exactly Total / Subtotal / Grand total."""
    first = next((v for v in r if isinstance(v, str) and v.strip()), None)
    return first is not None and bool(_TOTAL_LABEL.match(first.strip()))


def run_query(info: SheetInfo, rows: list[list[Cell]], q: TableQuery) -> TableResult:
    header = info.header_row_guess
    body = [r for r in (rows[header:] if header else rows) if any(not is_empty(c) for c in r)]
    cols = _columns(info, body)
    typed = [[c.typed(r[c.index] if c.index < len(r) else None) for c in cols] for r in body]
    for f in q.filters:
        col = _find(cols, f.column)
        typed = [r for r in typed if _test(f.op, r[col.index], f.value, col)]
    matched = len(typed)
    note = (
        f"The sheet was cut at {len(rows):,} rows when it was read: results cover those rows only"
        if info.truncated
        else None
    )
    if q.group_by or q.aggregates:
        # a sum over the items must not count the sheet's own Total line again
        totals = [r for r in typed if _is_total_row(r)]
        if totals:
            typed = [r for r in typed if not _is_total_row(r)]
            matched = len(typed)
            left = f"Left out the sheet's own Total row(s) ({len(totals)}): not counted twice"
            note = f"{note}. {left}" if note else left
        groups = [_find(cols, g) for g in q.group_by]
        aggs = q.aggregates or [Aggregate(fn="count")]
        agg_cols = [(_find(cols, a.column) if a.column else None) for a in aggs]
        buckets: dict[tuple[Any, ...], list[list[Any]]] = {}
        for r in typed:
            key = tuple(
                (r[g.index].lower() if isinstance(r[g.index], str) else r[g.index]) for g in groups
            )
            buckets.setdefault(key, []).append(r)
        labels = {k: tuple(b[0][g.index] for g in groups) for k, b in buckets.items()}
        out_cols = [g.name for g in groups] + [a.label for a in aggs]
        out_rows: list[list[Any]] = []
        for key, members in buckets.items() if groups else [((), typed)]:
            out_rows.append(
                [
                    *(labels.get(key, ()) if groups else ()),
                    *(_aggregate(a.fn, c, members) for a, c in zip(aggs, agg_cols, strict=True)),
                ]
            )
    else:
        out_cols = [c.name for c in cols]
        out_rows = typed
    if q.sort:
        for s in reversed(q.sort):
            try:
                idx = (
                    out_cols.index(s.by)
                    if s.by in out_cols
                    else next(i for i, n in enumerate(out_cols) if n.lower() == s.by.lower())
                )
            except StopIteration as e:
                raise QueryError(f"Can't sort by {s.by!r}: not in the result") from e
            present = [r for r in out_rows if r[idx] is not None]
            missing = [r for r in out_rows if r[idx] is None]

            def sort_key(r: list[Any], i: int = idx) -> Any:
                return str(r[i]).lower() if isinstance(r[i], str) else r[i]

            present.sort(key=sort_key, reverse=s.dir == "desc")
            out_rows = present + missing
    limited = len(out_rows) > q.limit
    return TableResult(
        columns=out_cols,
        rows=[[_out(v) for v in r] for r in out_rows[: q.limit]],
        matched_rows=matched,
        total_rows=len(body),
        truncated=limited or info.truncated,
        note=note,
    )
