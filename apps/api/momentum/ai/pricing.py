"""Cost estimates for llm_calls from MOMENTUM_LLM_PRICE_TABLE.

The table is keyed by the *resolved* model name (what the gateway was asked for), because the
same alias can point at different models over time and old rows must keep their old price.
Models missing from the table cost 0 — an estimate, not a bill; the usage page (S3.5.2) shows
token counts, which are exact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    in_per_mtok: Decimal
    out_per_mtok: Decimal


class PriceTable:
    def __init__(self, prices: dict[str, Price]) -> None:
        self._prices = prices

    @classmethod
    def parse(cls, raw: str) -> PriceTable:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as e:
            raise ValueError("MOMENTUM_LLM_PRICE_TABLE must be a JSON object") from e
        if not isinstance(data, dict):
            raise ValueError("MOMENTUM_LLM_PRICE_TABLE must be a JSON object")
        prices: dict[str, Price] = {}
        for model, entry in data.items():
            if not isinstance(entry, dict):
                raise ValueError(f"MOMENTUM_LLM_PRICE_TABLE[{model!r}] must be an object")
            try:
                prices[model] = Price(
                    in_per_mtok=Decimal(str(entry.get("in_per_mtok", 0))),
                    out_per_mtok=Decimal(str(entry.get("out_per_mtok", 0))),
                )
            except ArithmeticError as e:
                raise ValueError(f"MOMENTUM_LLM_PRICE_TABLE[{model!r}] has a bad price") from e
        return cls(prices)

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> Decimal:
        price = self._prices.get(model)
        if price is None:
            return Decimal(0)
        total = (price.in_per_mtok * tokens_in + price.out_per_mtok * tokens_out) / MTOK
        return total.quantize(Decimal("0.000001"))
