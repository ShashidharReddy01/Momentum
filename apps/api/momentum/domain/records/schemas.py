"""Phase 7.6 S76-04 (spec §6): what the records API takes and returns, and the record type
contract the domain needs from a pack (``RecordTypeImpl``, which ``momentum.sdk.RecordType``
implements)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from momentum.domain.records.paths import PATH

PathStr = Annotated[str, Field(pattern=PATH.pattern, max_length=200)]
SetStatus = Literal["approved", "rejected", "void", "needs_review", "ready"]


class RecordTypeImpl(Protocol):
    """What the domain asks of a record type: validating data (every write), the deterministic
    re-checks after a correction, and the display spec (paths) stored at install."""

    @property
    def key(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def label(self) -> str: ...

    @property
    def classification(self) -> str: ...

    def validate(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def recheck(self, data: dict[str, Any]) -> list[dict[str, Any]] | None: ...

    def display(self) -> dict[str, Any]: ...

    def json_schema(self) -> dict[str, Any]: ...


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetOp(_Op):
    op: Literal["set"]
    path: PathStr
    value: Any = None


class AddItemOp(_Op):
    op: Literal["add_item"]
    array: PathStr
    item: dict[str, Any]
    at: int | None = Field(default=None, ge=0)


class RemoveItemOp(_Op):
    op: Literal["remove_item"]
    array: PathStr
    index: int = Field(ge=0)


class MoveItemOp(_Op):
    op: Literal["move_item"]
    array: PathStr
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DistributeOp(_Op):
    op: Literal["distribute"]
    array: PathStr
    field: Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_]*$")]
    total: Decimal


class SetStatusOp(_Op):
    op: Literal["set_status"]
    status: SetStatus
    reason: str | None = Field(default=None, max_length=1000)


class LinkEntityOp(_Op):
    op: Literal["link_entity"]
    role: Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_]*$")]
    entity_id: uuid.UUID


Op = Annotated[
    SetOp | AddItemOp | RemoveItemOp | MoveItemOp | DistributeOp | SetStatusOp | LinkEntityOp,
    Field(discriminator="op"),
]


class RecordPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[Op] = Field(min_length=1, max_length=50)
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class RecordVersionOut(BaseModel):
    version: int
    status: str
    changed_by: uuid.UUID | None
    via: str
    change: dict[str, Any]
    reason: str | None
    created_at: datetime


class RecordOut(BaseModel):
    id: uuid.UUID
    type: str
    type_version: int
    type_label: str
    classification: str
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    source_attachment_id: uuid.UUID | None
    source_locator: str | None
    run_id: uuid.UUID | None
    status: str
    title: str
    data: dict[str, Any]
    provenance: dict[str, Any]
    checks: list[dict[str, Any]]
    decision: dict[str, Any] | None
    confidence: Decimal | None
    amount: Decimal | None
    currency: str | None
    occurred_on: date | None
    entity_ids: list[uuid.UUID]
    version: int
    created_via: str
    created_at: datetime
    updated_at: datetime


class RecordDetailOut(RecordOut):
    versions: list[RecordVersionOut]
    duplicates: list[uuid.UUID] = Field(
        default_factory=list, description="Other records with the same identity (you can see)"
    )
