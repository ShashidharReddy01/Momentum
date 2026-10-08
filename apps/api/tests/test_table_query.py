"""Phase 7.5 S75-02 (spec §4.5, §11.2): exact table queries over parsed sheets."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from momentum.files.parse import parse_bytes
from momentum.files.tables import QueryError, TableQuery, run_query
from momentum.files.values import infer_decimal, parse_date, parse_number
from tests.fixtures.files import build


@pytest.fixture(scope="module")
def invoices():  # type: ignore[no-untyped-def]
    t = time.monotonic()
    r = parse_bytes(build.xlsx_invoices(5000), "invoices.xlsx", "x")
    elapsed = time.monotonic() - t
    assert elapsed < 3, f"parsing the 5,000-row workbook took {elapsed:.2f}s"
    sheet = r.model.sheets[0]
    return sheet, r.rows[sheet.data_ref], build.invoice_rows(5000)


def q(**kw: object) -> TableQuery:
    return TableQuery.model_validate(kw)


def test_sum_where_matches_python_exactly(invoices) -> None:  # type: ignore[no-untyped-def]
    sheet, rows, data = invoices
    res = run_query(
        sheet,
        rows,
        q(
            filters=[{"column": "Status", "op": "eq", "value": "overdue"}],
            aggregates=[{"fn": "sum", "column": "Amount", "as": "total"}, {"fn": "count"}],
        ),
    )
    expected = sum(r[2] for r in data if r[3] == "Overdue")
    assert res.columns == ["total", "count"]
    assert res.rows[0][0] == pytest.approx(expected, abs=1e-6)
    assert res.rows[0][1] == sum(1 for r in data if r[3] == "Overdue")
    assert res.matched_rows == res.rows[0][1] and res.total_rows == 5000


def test_group_by_sort_limit(invoices) -> None:  # type: ignore[no-untyped-def]
    sheet, rows, data = invoices
    res = run_query(
        sheet,
        rows,
        q(
            group_by=["Customer"],
            aggregates=[
                {"fn": "avg", "column": "Amount", "as": "avg"},
                {"fn": "max", "column": "Due"},
            ],
            sort=[{"by": "avg", "dir": "desc"}],
            limit=2,
        ),
    )
    by: dict[str, list[float]] = {}
    for r in data:
        by.setdefault(r[1], []).append(r[2])
    best = sorted(by, key=lambda k: -sum(by[k]) / len(by[k]))[:2]
    assert [r[0] for r in res.rows] == best
    assert res.rows[0][1] == pytest.approx(sum(by[best[0]]) / len(by[best[0]]))
    assert res.truncated  # 5 groups, limit 2


def test_two_group_columns_and_distinct_count(invoices) -> None:  # type: ignore[no-untyped-def]
    sheet, rows, data = invoices
    res = run_query(sheet, rows, q(group_by=["Customer", "Status"], limit=200))
    assert len(res.rows) == len({(r[1], r[3]) for r in data})
    assert sum(r[2] for r in res.rows) == 5000
    d = run_query(sheet, rows, q(aggregates=[{"fn": "distinct_count", "column": "Customer"}]))
    assert d.rows == [[5]]


def test_filters_numbers_dates_in_contains_letters(invoices) -> None:  # type: ignore[no-untyped-def]
    sheet, rows, data = invoices
    big = run_query(
        sheet,
        rows,
        q(
            filters=[{"column": "Amount", "op": "gte", "value": "4,500.00"}],
            aggregates=[{"fn": "count"}],
        ),
    )
    assert big.rows == [[sum(1 for r in data if r[2] >= 4500)]]
    late = run_query(
        sheet,
        rows,
        q(
            filters=[{"column": "Due", "op": "lt", "value": "2026-02-01"}],
            aggregates=[{"fn": "count"}],
        ),
    )
    assert late.rows == [[sum(1 for r in data if r[4].isoformat() < "2026-02-01")]]
    two = run_query(
        sheet,
        rows,
        q(
            filters=[{"column": "B", "op": "in", "value": ["Contoso", "Fabrikam"]}],
            aggregates=[{"fn": "count"}],
        ),
    )
    assert two.rows == [[2000]]
    has = run_query(
        sheet,
        rows,
        q(
            filters=[{"column": "Invoice", "op": "contains", "value": "INV-100"}],
            aggregates=[{"fn": "count"}],
        ),
    )
    assert has.rows == [[sum(1 for r in data if "INV-100" in r[0])]]
    plain = run_query(sheet, rows, q(sort=[{"by": "Amount", "dir": "desc"}], limit=1))
    assert plain.rows[0][2] == pytest.approx(max(r[2] for r in data))


def test_errors_are_explained(invoices) -> None:  # type: ignore[no-untyped-def]
    sheet, rows, _ = invoices
    with pytest.raises(QueryError, match="No column named 'Price'"):
        run_query(sheet, rows, q(aggregates=[{"fn": "sum", "column": "Price"}]))
    with pytest.raises(QueryError, match="can't be summed"):
        run_query(sheet, rows, q(aggregates=[{"fn": "sum", "column": "Customer"}]))
    with pytest.raises(QueryError, match="isn't a number"):
        run_query(sheet, rows, q(filters=[{"column": "Amount", "op": "gt", "value": "lots"}]))
    with pytest.raises(ValidationError):
        TableQuery.model_validate({"limit": 500})
    with pytest.raises(ValidationError):
        TableQuery.model_validate({"group_by": ["a", "b", "c"]})
    with pytest.raises(ValidationError):
        TableQuery.model_validate({"filters": [], "sql": "drop table"})


def test_locale_numbers_by_column() -> None:
    r = parse_bytes(build.csv_semicolon(), "payments.csv", "text/csv")
    sheet = r.model.sheets[0]
    rows = r.rows[sheet.data_ref]
    total = run_query(sheet, rows, q(aggregates=[{"fn": "sum", "column": "Amount"}]))
    assert total.rows[0][0] == pytest.approx(1234.5 + 2000 - 1234.5 + 99.9 + 0.125)
    unpaid = run_query(
        sheet,
        rows,
        q(filters=[{"column": "Paid", "op": "eq", "value": "no"}], aggregates=[{"fn": "count"}]),
    )
    assert unpaid.rows == [[3]]
    us = b'Item,Amount\nA,"1,234.50"\nB,"(1,234)"\nC,12%\n'
    r2 = parse_bytes(us, "us.csv", "text/csv")
    s2 = r2.model.sheets[0]
    got = run_query(s2, r2.rows[s2.data_ref], q(sort=[{"by": "Item"}]))
    assert [row[1] for row in got.rows] == [1234.5, -1234, 0.12]


@pytest.mark.parametrize(
    ("text", "dec", "expected"),
    [
        ("1,234.50", ".", 1234.5),
        ("1.234,50", ",", 1234.5),
        ("(1,234)", ".", -1234.0),
        ("12%", ".", 0.12),
        ("€ 99,90", ",", 99.9),
        ("$1,000", ".", 1000.0),
        ("-3.5", ".", -3.5),
        ("abc", ".", None),
    ],
)
def test_parse_number(text: str, dec: str, expected: float | None) -> None:
    got = parse_number(text, dec)  # type: ignore[arg-type]
    assert got == (pytest.approx(expected) if expected is not None else None)


def test_column_level_inference() -> None:
    assert infer_decimal(["1.234,50", "2.000,00", "3,1"]) == ","
    assert infer_decimal(["1,234.50", "12.5"]) == "."
    assert str(parse_date("31/12/2026")) == "2026-12-31"
    assert str(parse_date("12/31/2026", day_first=False)) == "2026-12-31"
    assert str(parse_date("2026-03-04 10:00")) == "2026-03-04"


def test_caps_mark_truncation() -> None:
    lines = "n\n" + "\n".join(str(i) for i in range(300))
    r = parse_bytes(lines.encode(), "many.csv", "text/csv", max_rows=100)
    sheet = r.model.sheets[0]
    assert sheet.truncated and r.model.file.truncated
    res = run_query(sheet, r.rows[sheet.data_ref], q(aggregates=[{"fn": "count"}]))
    assert res.truncated and res.note and "cut" in res.note


def test_a_sum_leaves_out_the_sheets_own_total_row() -> None:
    """Live check 2026-10-08: "the total of the quote's line items" came back 102,000, twice the
    51,000, because the sheet's own Total row was summed with the items. Aggregates leave out
    rows labelled Total / Subtotal / Grand total and say so; listing rows still shows them."""
    r = parse_bytes(build.xlsx_quote(), "quote.xlsx", "x")
    sheet = r.model.sheets[0]
    rows = r.rows[sheet.data_ref]
    res = run_query(sheet, rows, q(aggregates=[{"fn": "sum", "column": "Line total"}]))
    assert res.rows[0][0] == pytest.approx(51000)
    assert res.note and "Total" in res.note
    listed = run_query(sheet, rows, q())
    assert any(row[0] == "Total" for row in listed.rows)
