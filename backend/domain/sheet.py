"""Reading spreadsheet rows without the database (FEATURES 1.8, 8.13, 5.2 imports).

Shared by the item and price imports (``domain.item_import``, ``domain.price_import``):

* :class:`Column` describes one template column; :func:`match_headers` finds the columns of
  a header row in English or Arabic, ignoring case, spaces, ``_`` and ``-``.
* Cell readers (:func:`text`, :func:`parse_whole`, :func:`parse_decimal`, :func:`parse_date`)
  accept what Excel or a CSV gives (numbers as floats, Arabic-Indic digits, dates as dates or
  ``YYYY-MM-DD`` / ``DD/MM/YYYY``) and raise ``ValueError`` for anything else.
* Formulas are never evaluated and never trusted (ADR 0014): a cell the reader marks
  :data:`FORMULA`, or text that starts with ``=``, is refused with ``FORMULA_NOT_ALLOWED``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

__all__ = [
    "FORMULA",
    "Column",
    "Formula",
    "RowIssues",
    "header_key",
    "is_formula",
    "match_headers",
    "missing_headers",
    "parse_date",
    "parse_decimal",
    "parse_whole",
    "text",
]

_SPACES = re.compile(r"\s+")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


class Formula:
    """Marker for a cell that holds a formula (never evaluated)."""

    _instance: Formula | None = None

    def __new__(cls) -> Formula:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "FORMULA"


#: The value a reader puts in place of a formula cell.
FORMULA: Final = Formula()


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    label_en: str
    label_ar: str
    max_length: int = 200
    aliases: tuple[str, ...] = ()
    required: bool = False


def header_key(value: Any) -> str:
    raw = "" if value is None else str(value)
    return _SPACES.sub("", raw.strip().lower().replace("_", "").replace("-", ""))


def match_headers(columns: Sequence[Column], header_row: Iterable[Any]) -> dict[int, str]:
    """Column position to field key for the recognised headers (the first match wins)."""
    index: dict[str, str] = {}
    for column in columns:
        for name in (column.key, column.label_en, column.label_ar, *column.aliases):
            index.setdefault(header_key(name), column.key)
    found: dict[int, str] = {}
    taken: set[str] = set()
    for position, cell in enumerate(header_row):
        key = index.get(header_key(cell))
        if key is not None and key not in taken:
            found[position] = key
            taken.add(key)
    return found


def missing_headers(columns: Sequence[Column], matched: Mapping[int, str]) -> list[str]:
    """Keys of the required columns the header row lacks."""
    present = set(matched.values())
    return [c.key for c in columns if c.required and c.key not in present]


def is_formula(value: Any) -> bool:
    """A formula cell, or text that a spreadsheet would run as one (``=...``)."""
    if value is FORMULA:
        return True
    return isinstance(value, str) and value.lstrip().startswith("=")


def text(value: Any) -> str:
    """A cell as single-spaced text; a whole float (a code typed as a number) loses ``.0``."""
    if value is None or value is FORMULA:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def _number_text(value: Any) -> str:
    return text(value).translate(_ARABIC_DIGITS).replace(",", "")


def parse_whole(value: Any, *, minimum: int = 0) -> int | None:
    """A whole number at least ``minimum``, None for an empty cell. Raises ``ValueError``."""
    if value is None or text(value) == "":
        return None
    if isinstance(value, bool):
        raise ValueError(value)
    try:
        number = Decimal(_number_text(value))
    except InvalidOperation as exc:
        raise ValueError(value) from exc
    if not number.is_finite() or number != number.to_integral_value() or number < minimum:
        raise ValueError(value)
    return int(number)


def parse_decimal(value: Any, *, places: int) -> Decimal | None:
    """A non-negative amount with at most ``places`` decimals, None for an empty cell.

    A float from Excel is read through its shortest text form (``12.5``, never
    ``12.4999...``). Raises ``ValueError``.
    """
    if value is None or text(value) == "":
        return None
    if isinstance(value, bool):
        raise ValueError(value)
    raw = repr(value) if isinstance(value, float) else _number_text(value)
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(value) from exc
    if not number.is_finite() or number < 0:
        raise ValueError(value)
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        raise ValueError(value)
    return number.quantize(Decimal(1).scaleb(-places))


def parse_date(value: Any) -> date | None:
    """A calendar date, None for an empty cell. Raises ``ValueError``."""
    if value is None or text(value) == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value).translate(_ARABIC_DIGITS)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()  # noqa: DTZ007 - a calendar date
        except ValueError:
            continue
    raise ValueError(raw)


@dataclass(slots=True)
class RowIssues:
    """Error codes of one row with the fields they concern (``{"code", "field"}``)."""

    errors: list[dict[str, str]] = field(default_factory=list)

    def add(self, code: str, field_name: str) -> None:
        entry = {"code": code, "field": field_name}
        if entry not in self.errors:
            self.errors.append(entry)

    def __bool__(self) -> bool:
        return bool(self.errors)
