"""Shared response envelopes (docs/architecture/api-conventions.md §3-4)."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from momentum.core.mutation import Mutation

T = TypeVar("T", bound=BaseModel)


class MutationMeta(BaseModel):
    activity_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    version: int | None = None


class MutationOut(BaseModel, Generic[T]):
    data: T
    meta: MutationMeta

    @classmethod
    def of(cls, m: Mutation[Any], schema: type[T]) -> MutationOut[T]:
        return cls(
            data=schema.model_validate(m.entity),
            meta=MutationMeta(activity_id=m.activity_id, batch_id=m.batch_id, version=m.version),
        )


class ListMeta(BaseModel):
    next_cursor: str | None = None


class ListOut(BaseModel, Generic[T]):
    data: list[T]
    meta: ListMeta = ListMeta()


class OkOut(BaseModel):
    ok: bool = True
