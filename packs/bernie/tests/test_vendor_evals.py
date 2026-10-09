"""The `bernie_vendor` eval cases (evals/bernie_vendor.yaml): vendor recognition before any model
call, every case right."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from momentum_pack_bernie import vendors

EVALS = Path(vendors.__file__).parent / "evals" / "bernie_vendor.yaml"
DATA = yaml.safe_load(EVALS.read_text(encoding="utf-8"))


class E:
    def __init__(self, row: dict[str, Any]) -> None:
        self.id, self.name = row["id"], row["name"]
        self.aliases = row.get("aliases") or []
        self.attributes = {k: row[k] for k in ("tax_ids", "folder_names") if k in row}


KNOWN = [E(r) for r in DATA["known"]]


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
def test_vendor_case(case: dict[str, Any]) -> None:
    page = case["page"].replace("<pad>", "x" * 1600)
    got = vendors.recognise(page, case.get("hint"), KNOWN)
    if case["expect"] == "candidates":
        assert got.entity_id is None and len(got.candidates) >= 2
    else:
        assert got.entity_id == case["expect"], got
    if case.get("method"):
        assert got.method == case["method"]
    if "model_pool" in case:
        assert len(vendors.candidates_for_model(page, KNOWN)) == case["model_pool"]


def test_there_are_at_least_ten_cases() -> None:
    assert len(DATA["cases"]) >= 10
