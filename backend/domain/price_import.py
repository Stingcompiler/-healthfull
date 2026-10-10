"""Price list import rows (FEATURES 5.2 with the 8.13 import flow), no database.

A sheet of service codes and prices goes into one dated version of one price list that has
not started yet (invariant 6: an effective version never changes; ADR 0014). The version and
list are chosen when the file is uploaded; each row only names a service and its price.

``services`` maps existing catalog codes (upper case) to their id and ``current`` maps a
service id to its price in the version the import builds on, so the preview can show the
change. Errors: ``CODE_REQUIRED``, ``SERVICE_UNKNOWN``, ``INVALID_PRICE``,
``VALUE_TOO_LONG``, ``FORMULA_NOT_ALLOWED``. Hints: ``in_file`` (the code repeats an earlier
row, so the later price would replace it) and ``unchanged`` (the price equals the current
one).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from domain import sheet
from domain.sheet import Column

__all__ = ["COLUMNS", "PriceRow", "parse_rows"]

COLUMNS: tuple[Column, ...] = (
    Column("service_code", "Service code", "رمز الخدمة", 40, ("code",), True),
    Column("price", "Price (SDG)", "السعر (جنيه)", 20, ("price", "unit price", "السعر"), True),
    Column("name", "Service name (for reference)", "اسم الخدمة (للمرجع)", 200, ("name",)),
)


@dataclass(slots=True)
class PriceRow:
    row_no: int
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def add_error(self, code: str, field_name: str) -> None:
        entry = {"code": code, "field": field_name}
        if entry not in self.errors:
            self.errors.append(entry)


def parse_rows(
    rows: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    services: Mapping[str, int],
    current: Mapping[int, Decimal],
) -> list[PriceRow]:
    """Read every non-blank row of a price sheet (``(sheet row number, key to cell)``)."""
    out: list[PriceRow] = []
    seen: dict[int, int] = {}
    for row_no, cells in rows:
        if all(sheet.text(v) == "" for v in cells.values()):
            continue
        row = PriceRow(row_no)
        values: dict[str, Any] = {}
        for column in COLUMNS:
            raw = cells.get(column.key)
            if sheet.is_formula(raw):
                row.add_error("FORMULA_NOT_ALLOWED", column.key)
                raw = None
            if column.key == "price" and isinstance(raw, int | float | Decimal):
                values[column.key] = raw
                continue
            value = sheet.text(raw)
            if len(value) > column.max_length:
                row.add_error("VALUE_TOO_LONG", column.key)
                value = value[: column.max_length]
            values[column.key] = value
        code = str(values["service_code"]).upper()
        row.data = {"service_code": code, "name": values["name"], "service_id": None}
        service_id = services.get(code) if code else None
        if not code:
            row.add_error("CODE_REQUIRED", "service_code")
        elif service_id is None:
            row.add_error("SERVICE_UNKNOWN", "service_code")
        row.data["service_id"] = service_id
        try:
            price = sheet.parse_decimal(values["price"], places=2)
        except ValueError:
            price = None
            row.add_error("INVALID_PRICE", "price")
        if price is None and not any(e["field"] == "price" for e in row.errors):
            row.add_error("INVALID_PRICE", "price")
        row.data["price"] = str(price) if price is not None else None
        before = current.get(service_id) if service_id is not None else None
        row.data["current_price"] = str(before) if before is not None else None
        if not row.errors and service_id is not None:
            if service_id in seen:
                row.warnings.append({"code": "in_file", "row_no": seen[service_id]})
            else:
                seen[service_id] = row_no
            if before is not None and price == before:
                row.warnings.append({"code": "unchanged"})
        out.append(row)
    return out
