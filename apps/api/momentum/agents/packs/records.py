"""Phase 7.6 S76-04 (spec §6.1): record types, as packs declare them (``momentum.sdk.RecordType``).

A pack's record model is an ordinary pydantic model (``RecordModel``: unknown keys refused). Money
fields are ``Money``: ``Decimal`` in code, a string in JSON ("1250.00"), so no float ever touches
an amount. ``RecordType`` adds what the platform needs: the title template, identity, money,
date, array and search paths, columns, task fields, the data classification, and an optional
``recheck`` (pure code, no model) re-run after every correction.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer

from momentum.domain.records.paths import PATH

Classification = Literal["public", "internal", "financial", "personal"]


def _money(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ValueError("expected an amount")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = re.sub(r"[\s£$€¥]", "", value).replace(",", "")
        try:
            return Decimal(text)
        except InvalidOperation:
            pass
    raise ValueError(f"not an amount: {value!r}")


Money = Annotated[
    Decimal,
    BeforeValidator(_money),
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]


class RecordModel(BaseModel):
    """Base for a pack's record model (e.g. ``InvoiceV1``)."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class RecordType:
    """A pack's record type (``Pack(record_types=(INVOICE,))``). Paths are into the model's
    JSON (``vendor.name``, ``lines[].amount``)."""

    key: str
    version: int
    model: type[RecordModel]
    label: str
    title: str = ""
    identity: tuple[str, ...] = ()
    money: tuple[str, ...] = ()
    currency_field: str | None = None
    dates: tuple[str, ...] = ()
    arrays: Mapping[str, str] = field(default_factory=dict)
    columns: tuple[str, ...] = ()
    task_fields: Mapping[str, str] = field(default_factory=dict)
    classification: Classification = "internal"
    search: tuple[str, ...] = ()
    amount: str | None = None  # the main money field (default: the first top-level money path)
    occurred_on: str | None = None  # the main date (default: the first top-level date path)
    recheck_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None

    def __post_init__(self) -> None:
        if not re.match(r"^[a-z][a-z0-9_]{0,59}$", self.key):
            raise ValueError(f"Record type key {self.key!r} isn't a lower-case key")
        if self.version < 1:
            raise ValueError("Record type versions start at 1")
        named = [
            *self.identity,
            *self.money,
            *self.dates,
            *self.columns,
            *self.search,
            *self.task_fields.values(),
            *([self.currency_field] if self.currency_field else []),
        ]
        for path in named:
            if not PATH.match(path):
                raise ValueError(f"{self.key}: not a field path: {path!r}")

    # ---------- what the domain asks of a type (RecordTypeImpl) ----------

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """The data as the model accepts it (raises ``ValidationError``), as JSON."""
        return self.model.model_validate(data).model_dump(mode="json")

    def recheck(self, data: dict[str, Any]) -> list[dict[str, Any]] | None:
        return self.recheck_fn(data) if self.recheck_fn is not None else None

    def display(self) -> dict[str, Any]:
        top_money = [p for p in self.money if "[" not in p]
        top_dates = [p for p in self.dates if "[" not in p]
        return {
            "title": self.title,
            "identity": list(self.identity),
            "money": list(self.money),
            "currency_field": self.currency_field,
            "dates": list(self.dates),
            "arrays": dict(self.arrays),
            "columns": list(self.columns),
            "task_fields": dict(self.task_fields),
            "search": list(self.search),
            "amount": self.amount or (top_money[0] if top_money else None),
            "occurred_on": self.occurred_on or (top_dates[0] if top_dates else None),
        }

    def json_schema(self) -> dict[str, Any]:
        return self.model.model_json_schema()
