"""Item, batch, opening stock and price import rows (FEATURES 8.13, 5.2): parsing and rules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain import item_import as ii
from domain import price_import as pi
from domain import sheet

TODAY = date(2026, 10, 10)
STORES = frozenset({"PHA", "MAIN"})


def codes(row: ii.ItemRow | pi.PriceRow) -> list[str]:
    return [e["code"] for e in row.errors]


# --- sheet helpers --------------------------------------------------------------------------


def test_headers_match_in_both_languages_and_report_missing_required() -> None:
    matched = sheet.match_headers(ii.COLUMNS, ["Service code", "رقم التشغيلة", " QTY ", "x"])
    assert matched == {0: "service_code", 1: "batch_no", 2: "quantity"}
    assert sheet.missing_headers(ii.COLUMNS, matched) == []
    assert sheet.missing_headers(pi.COLUMNS, sheet.match_headers(pi.COLUMNS, ["code"])) == ["price"]


def test_every_template_label_matches_its_column() -> None:
    for columns in (ii.COLUMNS, pi.COLUMNS):
        for labels in ([c.label_en for c in columns], [c.label_ar for c in columns]):
            assert list(sheet.match_headers(columns, labels).values()) == [c.key for c in columns]


def test_formulas_are_detected_never_evaluated() -> None:
    assert sheet.is_formula(sheet.FORMULA)
    assert sheet.is_formula("=SUM(A1:A3)")
    assert sheet.is_formula("  =1+1")
    assert not sheet.is_formula("+249912345678")
    assert not sheet.is_formula("-5")
    assert not sheet.is_formula(12)
    assert sheet.text(sheet.FORMULA) == ""


def test_numbers_read_from_excel_floats_and_arabic_digits() -> None:
    assert sheet.parse_whole(12.0) == 12
    assert sheet.parse_whole("١٢٠") == 120
    assert sheet.parse_whole("1,200") == 1200
    assert sheet.parse_whole("") is None
    for bad in ("1.5", "-1", "abc", True, "nan"):
        with pytest.raises(ValueError, match=r"."):
            sheet.parse_whole(bad)
    assert sheet.parse_decimal(12.5, places=2) == Decimal("12.50")
    assert sheet.parse_decimal(0.1, places=4) == Decimal("0.1000")
    assert sheet.parse_decimal("١٥٠٠٠٫٥", places=2) == Decimal("15000.50")
    for bad in ("1.234", "-3", "x", "Infinity"):
        with pytest.raises(ValueError, match=r"."):
            sheet.parse_decimal(bad, places=2)


def test_dates_read_from_cells_and_text() -> None:
    assert sheet.parse_date(datetime(2027, 1, 31, 0, 0)) == date(2027, 1, 31)
    assert sheet.parse_date("31/01/2027") == date(2027, 1, 31)
    assert sheet.parse_date("٢٠٢٧-٠١-٣١") == date(2027, 1, 31)
    assert sheet.parse_date(None) is None
    with pytest.raises(ValueError, match=r"."):
        sheet.parse_date("31.01.2027")


@given(st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False))
def test_parse_decimal_round_trips_two_place_amounts(value: Decimal) -> None:
    assert sheet.parse_decimal(str(value), places=2) == value


# --- items, batches, opening stock ----------------------------------------------------------


def parse(
    *rows: dict[str, object], services: dict[str, ii.KnownService] | None = None
) -> list[ii.ItemRow]:
    return ii.parse_rows(
        [(n, r) for n, r in enumerate(rows, start=2)],
        today=TODAY,
        services=services or {},
        stores=STORES,
        default_store="PHA",
    )


NEW_ITEM = {
    "service_code": "drg-zinc20",
    "name_en": "Zinc 20 mg",
    "name_ar": "زنك 20 ملغ",
    "kind": "دواء",
    "generic_name": "Zinc sulfate",
    "form": "Tablet",
    "strength": "20 mg",
    "base_unit_code": "TAB",
    "pack_unit_code": "BOX",
    "pack_factor": 100.0,
    "min_stock": "50",
    "batch_no": "Z-001",
    "expiry_date": datetime(2028, 3, 1),
    "quantity": 200,
    "unit_cost": 12.5,
}


def test_a_full_row_reads_into_a_new_item_with_a_batch() -> None:
    (row,) = parse(NEW_ITEM)
    assert row.errors == []
    assert row.defines_item
    assert row.has_batch
    d = row.data
    assert d["service_code"] == "DRG-ZINC20"
    assert (d["kind"], d["form"], d["storage"]) == ("drug", "tablet", "room")
    assert (d["pack_factor"], d["min_stock"], d["reorder_qty"]) == (100, 50, None)
    assert (d["base_unit_name_en"], d["pack_unit_name_ar"]) == ("TAB", "BOX")
    assert (d["expiry_date"], d["quantity"], d["unit_cost"], d["store"]) == (
        "2028-03-01",
        200,
        "12.5000",
        "PHA",
    )


def test_the_arabic_generic_name_column_is_read() -> None:
    """Pharmacy follow-up: stock lists show the generic name in the screen's language."""
    (row,) = parse({**NEW_ITEM, "generic_name_ar": "  كبريتات الزنك "})
    assert row.errors == []
    assert row.data["generic_name_ar"] == "كبريتات الزنك"
    (plain,) = parse(NEW_ITEM)
    assert plain.data["generic_name_ar"] == ""
    matched = sheet.match_headers(ii.COLUMNS, ["Generic name (Arabic)", "الاسم العلمي بالعربية"])
    assert set(matched.values()) == {"generic_name_ar"}


def test_item_only_rows_have_no_batch() -> None:
    row = {k: v for k, v in NEW_ITEM.items() if k not in ii.BATCH_KEYS}
    (parsed,) = parse(row)
    assert parsed.errors == []
    assert not parsed.has_batch
    assert parsed.data["quantity"] is None
    assert parsed.data["store"] == ""


def test_a_new_service_needs_a_name_and_a_stockable_kind() -> None:
    (row,) = parse({**NEW_ITEM, "name_en": "", "name_ar": "", "kind": "lab"})
    assert "SERVICE_NAME_REQUIRED" in codes(row)
    assert "SERVICE_KIND_UNKNOWN" in codes(row)


def test_an_existing_service_of_another_kind_is_not_stockable() -> None:
    (row,) = parse(NEW_ITEM, services={"DRG-ZINC20": ii.KnownService("lab", False)})
    assert codes(row) == ["SERVICE_NOT_STOCKABLE"]


def test_an_existing_item_keeps_its_master_data() -> None:
    (row,) = parse(
        {
            "service_code": "DRG-ZINC20",
            "batch_no": "Z-9",
            "expiry_date": "2028-01-01",
            "quantity": "5",
        },
        services={"DRG-ZINC20": ii.KnownService("drug", True)},
    )
    assert row.errors == []
    assert row.warnings == [{"code": "item_exists"}]


def test_field_errors_name_their_column() -> None:
    (row,) = parse(
        {
            **NEW_ITEM,
            "base_unit_code": "",
            "form": "powder",
            "storage": "attic",
            "min_stock": "-2",
            "pack_factor": "1",
            "batch_no": "",
            "expiry_date": "2026-10-09",
            "quantity": "0",
            "unit_cost": "abc",
            "store": "LAB",
        }
    )
    fields = {(e["code"], e["field"]) for e in row.errors}
    assert fields >= {
        ("UNIT_REQUIRED", "base_unit_code"),
        ("INVALID_FORM", "form"),
        ("INVALID_STORAGE", "storage"),
        ("INVALID_QUANTITY", "min_stock"),
        ("INVALID_CONVERSION", "pack_factor"),
        ("BATCH_NO_REQUIRED", "batch_no"),
        ("BATCH_EXPIRED", "expiry_date"),
        ("INVALID_QUANTITY", "quantity"),
        ("INVALID_COST", "unit_cost"),
        ("STORE_UNKNOWN", "store"),
    }


def test_expiry_is_required_and_readable_for_a_batch() -> None:
    (missing,) = parse({**NEW_ITEM, "expiry_date": ""})
    (bad,) = parse({**NEW_ITEM, "expiry_date": "soon"})
    assert "EXPIRY_REQUIRED" in codes(missing)
    assert codes(bad) == ["INVALID_EXPIRY_DATE"]
    (today,) = parse({**NEW_ITEM, "expiry_date": TODAY.isoformat()})
    assert today.errors == []  # usable through its expiry date (ARCHITECTURE 4.8)


def test_formula_cells_are_refused_per_column() -> None:
    (row,) = parse({**NEW_ITEM, "quantity": sheet.FORMULA, "name_en": '=HYPERLINK("x")'})
    assert {(e["code"], e["field"]) for e in row.errors} >= {
        ("FORMULA_NOT_ALLOWED", "quantity"),
        ("FORMULA_NOT_ALLOWED", "name_en"),
    }


def test_later_rows_of_a_code_add_batches_and_inherit_the_item() -> None:
    first, second, third = parse(
        NEW_ITEM,
        {
            "service_code": "DRG-ZINC20",
            "batch_no": "Z-002",
            "expiry_date": "2029-01-01",
            "quantity": "10",
            "store": "main",
        },
        {
            "service_code": "DRG-ZINC20",
            "form": "TABLET",
            "batch_no": "Z-003",
            "expiry_date": "2029-02-01",
            "quantity": "10",
        },
    )
    assert first.defines_item
    assert not second.defines_item
    assert second.errors == []
    assert third.errors == []
    assert second.data["generic_name"] == "Zinc sulfate"
    assert second.data["store"] == "MAIN"


def test_a_later_row_that_contradicts_the_item_is_an_error() -> None:
    _, second = parse(NEW_ITEM, {**NEW_ITEM, "strength": "50 mg", "batch_no": "Z-2"})
    assert ("IMPORT_ITEM_CONFLICT", "strength") in {(e["code"], e["field"]) for e in second.errors}


def test_batches_of_an_invalid_item_are_not_importable() -> None:
    _, second = parse(
        {**NEW_ITEM, "base_unit_code": ""},
        {
            "service_code": "DRG-ZINC20",
            "batch_no": "Z-2",
            "expiry_date": "2029-01-01",
            "quantity": "3",
        },
    )
    assert "IMPORT_ITEM_INVALID" in codes(second)


def test_a_repeated_batch_is_flagged_against_its_first_row() -> None:
    _, second = parse(
        NEW_ITEM,
        {
            "service_code": "drg-zinc20",
            "batch_no": "z-001",
            "expiry_date": "2028-03-01",
            "quantity": "1",
        },
    )
    assert second.errors == []
    assert {"code": "in_file", "row_no": 2} in second.warnings


def test_blank_rows_are_skipped() -> None:
    assert parse({"service_code": None, "quantity": ""}) == []


@given(st.integers(min_value=1, max_value=10**7), st.integers(min_value=0, max_value=10**6))
def test_whole_quantities_and_costs_survive_parsing(qty: int, cost_cents: int) -> None:
    cost = Decimal(cost_cents) / 100
    (row,) = parse({**NEW_ITEM, "quantity": str(qty), "unit_cost": str(cost)})
    assert row.errors == []
    assert row.data["quantity"] == qty
    assert Decimal(row.data["unit_cost"]) == cost


# --- prices --------------------------------------------------------------------------------


def prices(*rows: dict[str, object]) -> list[pi.PriceRow]:
    return pi.parse_rows(
        [(n, r) for n, r in enumerate(rows, start=2)],
        services={"CONS-GEN": 1, "LAB-CBC": 2},
        current={1: Decimal("15000.00"), 2: Decimal("12000.00")},
    )


def test_price_rows_read_codes_and_prices() -> None:
    a, b = prices(
        {"service_code": "cons-gen", "price": 16500}, {"service_code": "LAB-CBC", "price": "12000"}
    )
    assert a.errors == []
    assert a.data == {
        "service_code": "CONS-GEN",
        "name": "",
        "service_id": 1,
        "price": "16500.00",
        "current_price": "15000.00",
    }
    assert b.warnings == [{"code": "unchanged"}]


def test_price_row_errors() -> None:
    rows = prices(
        {"service_code": "NOPE", "price": "1"},
        {"service_code": "", "price": "1"},
        {"service_code": "CONS-GEN", "price": "-1"},
        {"service_code": "CONS-GEN", "price": "10.005"},
        {"service_code": "CONS-GEN", "price": ""},
        {"service_code": "CONS-GEN", "price": sheet.FORMULA},
    )
    assert [codes(r) for r in rows] == [
        ["SERVICE_UNKNOWN"],
        ["CODE_REQUIRED"],
        ["INVALID_PRICE"],
        ["INVALID_PRICE"],
        ["INVALID_PRICE"],
        ["FORMULA_NOT_ALLOWED"],
    ]


def test_a_repeated_price_code_points_at_its_first_row() -> None:
    _, second = prices(
        {"service_code": "CONS-GEN", "price": 1}, {"service_code": "CONS-GEN", "price": 2}
    )
    assert second.warnings == [{"code": "in_file", "row_no": 2}]
