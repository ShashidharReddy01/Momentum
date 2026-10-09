"""Vendor recognition (spec §9.3.7): folder hint, tax id, letterhead, before any model call; a
brand named in a line never counts."""

from __future__ import annotations

from typing import Any

from momentum_pack_bernie import vendors


class E:
    def __init__(
        self, id: str, name: str, aliases: list[str] | None = None, **attributes: Any
    ) -> None:
        self.id, self.name, self.aliases, self.attributes = id, name, aliases or [], attributes


KNOWN = [
    E(
        "1",
        "Northwind Data Ltd",
        ["Northwind"],
        tax_ids=["GB123456789"],
        folder_names=["northwind_data"],
    ),
    E("2", "Bloomberg Finance LP"),
    E("3", "Acme Analytics Inc", ["ACME Analytics"], tax_ids=["94-1234567"]),
]


def test_folder_hint_wins() -> None:
    assert vendors.recognise("anything", "northwind_data", KNOWN).method == "folder"
    assert (
        vendors.recognise("anything", "acme_analytics", KNOWN).entity_id == "3"
    )  # an alias's slug


def test_tax_id_on_page_one() -> None:
    r = vendors.recognise("SOMEONE NEW LTD\nVAT No: GB 123 456 789\nInvoice", None, KNOWN)
    assert (r.entity_id, r.method) == ("1", "tax_id")


def test_letterhead_and_ambiguity() -> None:
    r = vendors.recognise("ACME ANALYTICS INC\n500 Market Street\nINVOICE", None, KNOWN)
    assert (r.entity_id, r.method) == ("3", "letterhead")
    both = vendors.recognise("Northwind Data Ltd resells Acme Analytics Inc products", None, KNOWN)
    assert both.entity_id is None and both.candidates == ["1", "3"]
    assert vendors.recognise("Totally Unknown GmbH", None, KNOWN).entity_id is None


def test_brands_in_lines_beyond_the_letterhead_dont_count() -> None:
    page = "RESELLER CO\n" + "x" * 1600 + "\nBloomberg Finance LP terminal"
    assert vendors.recognise(page, None, KNOWN).entity_id is None


def test_the_models_closed_list() -> None:
    pool = vendors.candidates_for_model("NORTHWIND DATA LIMITED\nLondon", KNOWN)
    assert [e.id for e in pool] == ["1"]
    prompt = vendors.model_prompt("NORTHWIND DATA LIMITED", pool)
    assert (
        'id "1": Northwind Data Ltd (also Northwind)' in prompt and "<untrusted_document>" in prompt
    )
