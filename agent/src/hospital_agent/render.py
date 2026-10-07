"""Turn validated print requests into printer bytes. Pure: no I/O, easy to test.

The agent is a renderer only. Amounts arrive as decimal strings computed by the backend
(the source of truth); the agent formats them for display and never does arithmetic on money.
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from escpos.printer import Dummy

from .config import PrinterConfig

MAX_LINES = 200
MAX_TEXT = 200
MAX_COPIES = 5
_MONEY_RE = re.compile(r"^-?\d{1,12}(\.\d{1,2})?$")
_QTY_RE = re.compile(r"^\d{1,6}(\.\d{1,3})?$")
_BARCODE_RE = re.compile(r"^[\x20-\x7e]{1,48}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# python-escpos logs which barcode renderer it picked on every call; keep our logs clean.
logging.getLogger("escpos").setLevel(logging.WARNING)


class PayloadError(ValueError):
    """A request body field is missing or invalid."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


# ----------------------------------------------------------------------------- payload parsing


def _text(data: dict[str, Any], key: str, *, required: bool = False, where: str = "") -> str:
    name = f"{where}{key}"
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise PayloadError(name, "is required")
        return ""
    if not isinstance(value, str):
        raise PayloadError(name, "must be a string")
    if len(value) > MAX_TEXT:
        raise PayloadError(name, f"must be at most {MAX_TEXT} characters")
    # Control characters would be interpreted as printer commands.
    return _CONTROL_RE.sub(" ", value).strip()


def _money(data: dict[str, Any], key: str, *, required: bool = False, where: str = "") -> str:
    name = f"{where}{key}"
    value = data.get(key)
    if value is None:
        if required:
            raise PayloadError(name, "is required")
        return ""
    if not isinstance(value, str) or not _MONEY_RE.match(value):
        raise PayloadError(name, 'must be a decimal string like "10000.00"')
    return format_money(value)


def format_money(value: str) -> str:
    """Display a decimal string with thousands separators and exactly two places."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise PayloadError("amount", "is not a decimal") from exc
    return f"{amount:,.2f}"


def _copies(data: dict[str, Any]) -> int:
    copies = data.get("copies", 1)
    if isinstance(copies, bool) or not isinstance(copies, int) or not 1 <= copies <= MAX_COPIES:
        raise PayloadError("copies", f"must be an integer between 1 and {MAX_COPIES}")
    return copies


def _object(data: dict[str, Any], key: str, *, required: bool) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        if required:
            raise PayloadError(key, "is required")
        return {}
    if not isinstance(value, dict):
        raise PayloadError(key, "must be an object")
    return value


@dataclass(frozen=True, slots=True)
class ReceiptLine:
    description: str
    qty: str
    amount: str


@dataclass(frozen=True, slots=True)
class Receipt:
    receipt_no: str
    issued_at: str
    center_name: str
    center_address: str
    center_phone: str
    patient_name: str
    patient_file_no: str
    cashier: str
    lines: tuple[ReceiptLine, ...]
    total: str
    paid: str
    method: str
    reference: str
    currency: str
    qr: str
    footer: str
    copies: int


@dataclass(frozen=True, slots=True)
class Label:
    lines: tuple[str, ...]
    barcode: str
    copies: int


def parse_receipt(data: Any) -> Receipt:
    if not isinstance(data, dict):
        raise PayloadError("body", "must be a JSON object")
    center = _object(data, "center", required=True)
    patient = _object(data, "patient", required=False)
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise PayloadError("lines", "must be a non-empty list")
    if len(raw_lines) > MAX_LINES:
        raise PayloadError("lines", f"must have at most {MAX_LINES} entries")
    lines: list[ReceiptLine] = []
    for i, raw in enumerate(raw_lines):
        where = f"lines[{i}]."
        if not isinstance(raw, dict):
            raise PayloadError(f"lines[{i}]", "must be an object")
        qty = raw.get("qty", "1")
        if not isinstance(qty, str) or not _QTY_RE.match(qty):
            raise PayloadError(f"{where}qty", 'must be a decimal string like "1" or "2.5"')
        lines.append(
            ReceiptLine(
                description=_text(raw, "description", required=True, where=where),
                qty=qty,
                amount=_money(raw, "amount", required=True, where=where),
            )
        )
    qr = data.get("qr", "") or ""
    if not isinstance(qr, str) or len(qr) > 300:
        raise PayloadError("qr", "must be a string of at most 300 characters")
    return Receipt(
        receipt_no=_text(data, "receipt_no", required=True),
        issued_at=_text(data, "issued_at", required=True),
        center_name=_text(center, "name", required=True, where="center."),
        center_address=_text(center, "address", where="center."),
        center_phone=_text(center, "phone", where="center."),
        patient_name=_text(patient, "name", where="patient."),
        patient_file_no=_text(patient, "file_no", where="patient."),
        cashier=_text(data, "cashier"),
        lines=tuple(lines),
        total=_money(data, "total", required=True),
        paid=_money(data, "paid"),
        method=_text(data, "method"),
        reference=_text(data, "reference"),
        currency=_text(data, "currency") or "SDG",
        qr=_CONTROL_RE.sub("", qr),
        footer=_text(data, "footer"),
        copies=_copies(data),
    )


def parse_label(data: Any) -> Label:
    if not isinstance(data, dict):
        raise PayloadError("body", "must be a JSON object")
    raw_lines = data.get("lines", [])
    if not isinstance(raw_lines, list) or len(raw_lines) > 6:
        raise PayloadError("lines", "must be a list of at most 6 strings")
    lines: list[str] = []
    for i, value in enumerate(raw_lines):
        if not isinstance(value, str) or len(value) > 64:
            raise PayloadError(f"lines[{i}]", "must be a string of at most 64 characters")
        lines.append(_CONTROL_RE.sub(" ", value).strip())
    barcode = data.get("barcode", "") or ""
    if barcode and (not isinstance(barcode, str) or not _BARCODE_RE.match(barcode)):
        raise PayloadError("barcode", "must be 1-48 printable ASCII characters")
    if not lines and not barcode:
        raise PayloadError("body", "a label needs lines or a barcode")
    return Label(lines=tuple(lines), barcode=barcode, copies=_copies(data))


# ----------------------------------------------------------------------------- layout helpers


def two_columns(left: str, right: str, width: int) -> list[str]:
    """Left text wrapped, right text flush right on the last row. Never exceeds width."""
    right = right[:width]
    room = width - len(right) - 1
    if room < 8:
        return [*(textwrap.wrap(left, width) or [""]), right.rjust(width)]
    wrapped = textwrap.wrap(left, room) or [""]
    *head, last = wrapped
    return [*head, f"{last.ljust(room)} {right}"]


def _rule(width: int, char: str = "-") -> str:
    return char * width


# ----------------------------------------------------------------------------- ESC/POS


def _rows(out: Dummy, rows: list[str]) -> None:
    for row in rows:
        out.textln(row)


def _receipt_header(out: Dummy, receipt: Receipt, width: int) -> None:
    out.set(align="center", bold=True, double_height=True)
    _rows(out, textwrap.wrap(receipt.center_name, width) or [""])
    out.set_with_default(align="center")
    for extra in (receipt.center_address, receipt.center_phone):
        _rows(out, textwrap.wrap(extra, width))
    out.set_with_default()
    out.textln(_rule(width, "="))
    for left, right in (
        ("Receipt", receipt.receipt_no),
        ("Date", receipt.issued_at),
        ("Patient", receipt.patient_name),
        ("File no", receipt.patient_file_no),
        ("Cashier", receipt.cashier),
    ):
        if right:
            _rows(out, two_columns(left, right, width))
    out.textln(_rule(width))


def _receipt_body(out: Dummy, receipt: Receipt, width: int) -> None:
    for line in receipt.lines:
        single = Decimal(line.qty) == 1  # display decision only, not money arithmetic
        label = line.description if single else f"{line.qty} x {line.description}"
        _rows(out, two_columns(label, line.amount, width))
    out.textln(_rule(width))
    out.set(bold=True)
    _rows(out, two_columns(f"TOTAL {receipt.currency}", receipt.total, width))
    out.set_with_default()
    if receipt.paid:
        paid_label = f"Paid ({receipt.method})" if receipt.method else "Paid"
        _rows(out, two_columns(paid_label, receipt.paid, width))
    if receipt.reference:
        _rows(out, two_columns("Reference", receipt.reference, width))


def _receipt_footer(out: Dummy, receipt: Receipt, printer: PrinterConfig, copy: int) -> None:
    width = printer.columns
    if receipt.qr:
        out.ln()
        out.set_with_default(align="center")
        out.qr(receipt.qr, native=printer.qr_native, size=6, center=not printer.qr_native)
        out.set_with_default(align="center")
        out.textln(receipt.receipt_no)
    if receipt.footer:
        out.set_with_default(align="center")
        out.ln()
        _rows(out, textwrap.wrap(receipt.footer, width))
    if receipt.copies > 1:
        out.set_with_default(align="center")
        out.textln(f"copy {copy + 1}/{receipt.copies}")
    out.set_with_default()
    if printer.cut:
        out.cut()
    else:
        out.ln(4)


def receipt_escpos(receipt: Receipt, printer: PrinterConfig) -> bytes:
    """Render an 80mm receipt (48 columns at font A by default) as ESC/POS bytes."""
    out = Dummy(profile=printer.profile)
    for copy in range(receipt.copies):
        out.hw("INIT")
        _receipt_header(out, receipt, printer.columns)
        _receipt_body(out, receipt, printer.columns)
        _receipt_footer(out, receipt, printer, copy)
    return bytes(out.output)


def label_escpos(label: Label, printer: PrinterConfig) -> bytes:
    out = Dummy(profile=printer.profile)
    for _ in range(label.copies):
        out.hw("INIT")
        out.set_with_default(align="center")
        for line in label.lines:
            out.textln(line[: printer.columns])
        if label.barcode:
            # "{B" selects CODE128 code set B, which covers printable ASCII.
            out.barcode("{B" + label.barcode, "CODE128", height=60, width=2, function_type="B")
        if printer.cut:
            out.cut()
        else:
            out.ln(3)
    return bytes(out.output)


# ----------------------------------------------------------------------------- ZPL


def _zpl_field(value: str) -> str:
    """Escape ZPL control characters; used together with ^FH (hex escapes, '_' indicator)."""
    escaped = []
    for ch in value:
        if ch in "^~_\\":
            escaped.append(f"_{ord(ch):02X}")
        else:
            escaped.append(ch)
    return "".join(escaped)


def label_zpl(label: Label, printer: PrinterConfig) -> bytes:
    """Render a sample/specimen label in ZPL II (Zebra and compatible printers)."""
    dots_per_mm = printer.dpi / 25.4
    width = round(printer.width_mm * dots_per_mm)
    height = round(printer.height_mm * dots_per_mm)
    margin = round(2 * dots_per_mm)
    font = max(18, round(height / 8))
    parts = ["^XA", "^CI28", f"^PW{width}", f"^LL{height}", "^LH0,0"]
    y = margin
    for line in label.lines:
        parts.append(f"^FO{margin},{y}^A0N,{font},{font}^FH^FD{_zpl_field(line)}^FS")
        y += font + 4
    if label.barcode:
        bar_height = max(30, height - y - margin - font)
        parts.append(
            f"^FO{margin},{y}^BY2^BCN,{bar_height},Y,N,N^FH^FD{_zpl_field(label.barcode)}^FS"
        )
    parts.append(f"^PQ{label.copies}")
    parts.append("^XZ")
    return ("\n".join(parts) + "\n").encode("utf-8")


def render_label(label: Label, printer: PrinterConfig) -> bytes:
    if printer.language == "zpl":
        return label_zpl(label, printer)
    return label_escpos(label, printer)
