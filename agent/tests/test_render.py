from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from escpos.printer import Dummy

from hospital_agent.config import PrinterConfig
from hospital_agent.render import (
    PayloadError,
    format_money,
    label_zpl,
    parse_label,
    parse_receipt,
    receipt_escpos,
    render_label,
    two_columns,
)

from .conftest import receipt_payload

ESC_INIT = b"\x1b@"
CUT = b"\x1dV"


def test_format_money_keeps_exact_decimal_places() -> None:
    assert format_money("10000") == "10,000.00"
    assert format_money("4500.5") == "4,500.50"
    assert format_money("-12.34") == "-12.34"
    assert format_money("999999999999.99") == "999,999,999,999.99"


@pytest.mark.parametrize("width", [32, 42, 48])
def test_two_columns_never_exceeds_width(width: int) -> None:
    left = "Very long service description that will certainly need wrapping " * 2
    rows = two_columns(left, "1,234,567.89", width)
    assert all(len(row) <= width for row in rows)
    assert rows[-1].endswith("1,234,567.89")
    assert len(rows) > 1


def test_receipt_bytes_contain_text_amounts_qr_and_cut(receipt_printer: PrinterConfig) -> None:
    data = receipt_escpos(parse_receipt(receipt_payload()), receipt_printer)
    assert data.startswith(ESC_INIT)
    assert b"Test Medical Center" in data
    assert b"RC-2026-000123" in data
    assert b"10,000.00" in data
    assert b"14,500.50" in data
    assert b"TOTAL SDG" in data
    assert b"\x1d(k" in data  # native QR command
    assert data.rstrip().endswith(CUT + b"\x00") or CUT in data[-8:]


@pytest.mark.parametrize("columns", [32, 48])
def test_receipt_text_rows_fit_paper_width(
    receipt_printer: PrinterConfig, monkeypatch: pytest.MonkeyPatch, columns: int
) -> None:
    rows: list[str] = []
    original = Dummy.textln

    def capture(self: Dummy, txt: str = "") -> None:
        rows.append(txt)
        original(self, txt)

    monkeypatch.setattr(Dummy, "textln", capture)
    long_line = {"description": "Ultrasound abdomen and pelvis " * 3, "qty": "2", "amount": "1.00"}
    payload = receipt_payload(lines=[long_line], footer="Thank you for choosing us " * 4)
    receipt_escpos(parse_receipt(payload), replace(receipt_printer, columns=columns))
    assert rows, "renderer printed nothing"
    assert max(len(row) for row in rows) <= columns
    assert any(row.startswith("2 x Ultrasound") for row in rows)


def test_receipt_copies_repeat_the_document(receipt_printer: PrinterConfig) -> None:
    data = receipt_escpos(parse_receipt(receipt_payload(copies=2)), receipt_printer)
    assert data.count(ESC_INIT) == 2
    assert b"copy 2/2" in data


def test_receipt_without_cut_feeds_paper(receipt_printer: PrinterConfig) -> None:
    printer = replace(receipt_printer, cut=False)
    data = receipt_escpos(parse_receipt(receipt_payload(qr="")), printer)
    assert CUT not in data


def test_control_characters_cannot_inject_printer_commands(receipt_printer: PrinterConfig) -> None:
    payload = receipt_payload(cashier="ok\x1b@\x1dV\x00evil")
    receipt = parse_receipt(payload)
    assert "\x1b" not in receipt.cashier
    data = receipt_escpos(receipt, receipt_printer)
    assert data.count(ESC_INIT) == 1


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"total": 14500.5}, "total"),
        ({"total": "14500.505"}, "total"),
        ({"total": "abc"}, "total"),
        ({"lines": []}, "lines"),
        ({"lines": [{"description": "x", "amount": "1.00", "qty": "-1"}]}, "lines[0].qty"),
        ({"lines": [{"amount": "1.00"}]}, "lines[0].description"),
        ({"center": None}, "center"),
        ({"receipt_no": ""}, "receipt_no"),
        ({"copies": 0}, "copies"),
        ({"copies": True}, "copies"),
        ({"qr": "x" * 301}, "qr"),
    ],
)
def test_invalid_receipts_name_the_field(override: dict[str, Any], field: str) -> None:
    with pytest.raises(PayloadError) as info:
        parse_receipt(receipt_payload(**override))
    assert info.value.field == field


def test_label_payload_validation() -> None:
    with pytest.raises(PayloadError):
        parse_label({})
    with pytest.raises(PayloadError):
        parse_label({"barcode": "non-ascii-\u0661"})
    with pytest.raises(PayloadError):
        parse_label({"lines": ["x"] * 7})
    label = parse_label({"lines": ["Patient"], "barcode": "S-000123", "copies": 2})
    assert label.copies == 2


def test_zpl_label_escapes_control_characters(config: Any) -> None:
    printer: PrinterConfig = config.label
    label = parse_label({"lines": ["A^B~C_D"], "barcode": "S-000123", "copies": 3})
    zpl = label_zpl(label, printer).decode()
    assert zpl.startswith("^XA") and zpl.rstrip().endswith("^XZ")
    assert "^CI28" in zpl  # UTF-8 so Arabic names survive
    assert "A_5EB_7EC_5FD" in zpl
    assert "^BCN" in zpl and "S-000123" in zpl
    assert "^PQ3" in zpl
    assert "^PW400" in zpl  # 50 mm at 203 dpi


def test_escpos_label_uses_code128(config: Any) -> None:
    printer = replace(config.label, language="escpos")
    data = render_label(parse_label({"lines": ["Sample"], "barcode": "S-1"}), printer)
    assert b"{BS-1" in data
    assert b"Sample" in data
