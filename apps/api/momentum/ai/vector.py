"""A minimal SQLAlchemy type for pgvector's ``vector(n)`` column.

pgvector accepts and returns the text form ``[0.1,0.2,…]``, so binding a Python list as that
string (and parsing it back) is all Momentum needs; this avoids a dependency for one column type.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            if len(value) != self.dim:
                raise ValueError(f"expected a {self.dim}-dimension vector, got {len(value)}")
            return "[" + ",".join(repr(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(v) for v in value.strip("[]").split(",") if v]

        return process


def vector_literal(value: list[float]) -> str:
    """The text form, for ``CAST(:q AS vector)`` in hand-written queries."""
    return "[" + ",".join(repr(float(v)) for v in value) + "]"
