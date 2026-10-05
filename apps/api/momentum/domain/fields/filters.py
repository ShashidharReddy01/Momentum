"""S7.4.1: filtering tasks by custom fields, one definition for every place that does it (search,
dashboards and charts, Mo's ``query_metrics``); the web app's list views apply the same rules in
``features/fields/filters.ts``.

A filter is typed data (``FieldFilter``); URLs and query parameters carry it as text,
``<field id>:<op>[:<argument>]``:

- ``any:<a>,<b>``: single/multi-select option ids, people's user ids, or ``true``/``false`` for a
  checkbox; ``none`` matches tasks with no value. Several values are OR-ed.
- ``min:<x>`` / ``max:<x>``: numbers (number, currency, percent) or ``YYYY-MM-DD`` (date),
  inclusive.
- ``has:<text>``: text and URL fields containing the text (any case).
- ``set`` / ``empty``: the task has a value / has none.

Several filters are AND-ed. Only fields of the viewer's workspace can be named; the tasks they
match are still limited by the caller's own visibility clause.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Numeric, Text, and_, cast, false, func, not_, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.tasks.models import Task

FieldOp = Literal["any", "min", "max", "has", "set", "empty"]
NONE = "none"
NUMERIC = ("number", "currency", "percent")
LISTED = ("single_select", "multi_select", "people")  # values are option or user ids
MAX_FILTERS = 10


class FieldFilter(BaseModel):
    """One condition on one custom field (see the module doc for what each ``op`` takes)."""

    model_config = ConfigDict(extra="forbid")

    field_id: uuid.UUID
    op: FieldOp
    values: list[str] = Field(
        default_factory=list,
        max_length=50,
        description='For "any": option ids, user ids, "true"/"false", or "none" (no value)',
    )
    value: str | None = Field(
        default=None,
        max_length=200,
        description='For "min"/"max": a number or YYYY-MM-DD; for "has": the text to look for',
    )

    @model_validator(mode="after")
    def _shape(self) -> FieldFilter:
        if self.op == "any" and not self.values:
            raise ValueError('"any" needs at least one value')
        if self.op != "any" and self.values:
            raise ValueError(f'"{self.op}" takes no values list')
        if self.op in ("min", "max", "has") and not (self.value or "").strip():
            raise ValueError(f'"{self.op}" needs a value')
        if self.op in ("any", "set", "empty") and self.value is not None:
            raise ValueError(f'"{self.op}" takes no value')
        return self

    def to_text(self) -> str:
        if self.op == "any":
            return f"{self.field_id}:any:{','.join(self.values)}"
        if self.op in ("set", "empty"):
            return f"{self.field_id}:{self.op}"
        return f"{self.field_id}:{self.op}:{self.value}"


def parse_field_filter(text: str) -> FieldFilter:
    """``<field id>:<op>[:<argument>]`` → a filter, or ``ValidationFailed`` saying what's wrong."""
    raw_id, _, rest = text.partition(":")
    op, _, arg = rest.partition(":")
    try:
        field_id = uuid.UUID(raw_id)
    except ValueError:
        raise ValidationFailed(
            f'"{raw_id}" is not a field id', code="invalid_field_filter"
        ) from None
    try:
        if op == "any":
            return FieldFilter(field_id=field_id, op="any", values=[v for v in arg.split(",") if v])
        if op in ("set", "empty"):
            return FieldFilter(field_id=field_id, op=op, value=arg or None)
        if op in ("min", "max", "has"):
            return FieldFilter(field_id=field_id, op=op, value=arg)
    except ValueError as e:
        raise ValidationFailed(str(e), code="invalid_field_filter") from None
    raise ValidationFailed(
        f'Unknown field filter "{op}" (use any, min, max, has, set or empty)',
        code="invalid_field_filter",
    )


def parse_field_filters(texts: list[str]) -> list[FieldFilter]:
    if len(texts) > MAX_FILTERS:
        raise ValidationFailed(f"At most {MAX_FILTERS} field filters", code="invalid_field_filter")
    return [parse_field_filter(t) for t in texts]


def scalar_text(value: Any) -> ColumnElement[str]:
    # a scalar JSON value as text (a JSON string unquoted, a number as written); ->>0 of a
    # one-element array reads it, and a JSON null reads as SQL null
    return func.jsonb_build_array(value).op("->>")(0)


def is_checked(value: Any) -> ColumnElement[bool]:
    """A checkbox value is JSON ``true``, compared as text (a bound "true" is a JSON string)."""
    return and_(func.jsonb_typeof(value) == "boolean", scalar_text(value) == "true")


def _number(raw: str) -> Decimal:
    try:
        n = Decimal(raw)
    except InvalidOperation:
        raise ValidationFailed(f'"{raw}" is not a number', code="invalid_field_filter") from None
    if not n.is_finite():
        raise ValidationFailed(f'"{raw}" is not a number', code="invalid_field_filter")
    return n


def _date(raw: str) -> str:
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise ValidationFailed(
            f'"{raw}" is not a YYYY-MM-DD date', code="invalid_field_filter"
        ) from None


def _condition(field: FieldDef, f: FieldFilter) -> ColumnElement[bool]:
    """SQL for "this task matches ``f``" on ``Task.id``."""
    fv = aliased(FieldValue)  # never correlated with a field_values join in the caller's query
    value = fv.value
    has_value = and_(value.is_not(None), func.jsonb_typeof(value) != "null")

    def valued(*cond: ColumnElement[bool]) -> ColumnElement[bool]:
        return Task.id.in_(select(fv.task_id).where(fv.field_id == field.id, has_value, *cond))

    t, name = field.type, field.name
    if f.op == "set":
        return valued()
    if f.op == "empty":
        return not_(valued())
    if f.op == "any":
        named = [v for v in f.values if v != NONE]
        parts: list[ColumnElement[bool]] = [not_(valued())] if NONE in f.values else []
        if t == "checkbox":
            if not set(named) <= {"true", "false"}:
                raise ValidationFailed(
                    f'"{name}" is a checkbox: use true, false or none', code="invalid_field_filter"
                )
            checked = valued(is_checked(value))
            if "true" in named:
                parts.append(checked)
            if "false" in named or NONE in f.values:
                parts.append(not_(checked))  # unchecked and never set read the same
        elif t in LISTED:
            if t == "people":
                for v in named:
                    try:
                        uuid.UUID(v)
                    except ValueError:
                        raise ValidationFailed(
                            f'"{v}" is not a user id', code="invalid_field_filter"
                        ) from None
            if named:
                # jsonb ?| matches a string scalar equal to one of them, or an array holding one
                parts.append(valued(value.op("?|")(cast(array(named), ARRAY(Text)))))
        else:
            raise ValidationFailed(
                f'"{name}" can\'t be filtered by "any" (use min/max, has, set or empty)',
                code="invalid_field_filter",
            )
        return or_(*parts) if parts else false()
    raw = (f.value or "").strip()
    if f.op in ("min", "max"):
        if t in NUMERIC:
            n = _number(raw)
            num = cast(scalar_text(value), Numeric)
            cmp = num >= n if f.op == "min" else num <= n
            return valued(func.jsonb_typeof(value) == "number", cmp)
        if t == "date":
            d = _date(raw)
            txt = scalar_text(value)
            return valued(txt >= d if f.op == "min" else txt <= d)
        raise ValidationFailed(f'"{name}" isn\'t a number or a date', code="invalid_field_filter")
    # has
    if t not in ("text", "url"):
        raise ValidationFailed(f'"{name}" isn\'t a text field', code="invalid_field_filter")
    like = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return valued(scalar_text(value).ilike(f"%{like}%", escape="\\"))


async def field_conditions(
    session: AsyncSession, ctx: Ctx, filters: list[FieldFilter]
) -> list[ColumnElement[bool]]:
    """One SQL condition per filter (AND them), after checking each field is the workspace's own
    and the filter suits its type."""
    if not filters:
        return []
    ids = {f.field_id for f in filters}
    fields = {
        fd.id: fd
        for fd in (
            await session.execute(
                select(FieldDef).where(
                    FieldDef.id.in_(ids),
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.deleted_at.is_(None),
                )
            )
        ).scalars()
    }
    out: list[ColumnElement[bool]] = []
    for f in filters:
        field = fields.get(f.field_id)
        if field is None:
            raise ValidationFailed("That custom field doesn't exist", code="invalid_field_filter")
        out.append(_condition(field, f))
    return out or [true()]
