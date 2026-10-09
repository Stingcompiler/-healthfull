"""Patient import rows that need no database (FEATURES 1.8).

A spreadsheet of patients (exported from an old system or typed by the clinic) is matched to
the patient fields by its header row, then each row is read into registration data with its
errors. Duplicates against existing files are found by the service (they need the
database); this module finds rows that repeat an earlier row of the same file.

* Headers match in English or Arabic, ignoring case, spaces, ``_`` and ``-``
  (``full_name_ar``, ``Name (Arabic)``, ``الاسم بالعربية``). Unknown columns are ignored.
* A name (Arabic or English) and the sex are required. Sex reads ``male``/``female``,
  ``m``/``f``, ``ذكر``/``أنثى`` (``unknown`` is for emergency files only, never imported).
* The date of birth reads a spreadsheet date or ``YYYY-MM-DD``, ``DD/MM/YYYY`` and
  ``DD-MM-YYYY``; without one an age in years estimates it, like registration.
* Error codes are the registration ones (``NAME_REQUIRED``, ``INVALID_SEX``,
  ``INVALID_DATE_OF_BIRTH``, ``INVALID_AGE``) plus ``VALUE_TOO_LONG``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

__all__ = [
    "COLUMNS",
    "REQUIRED_HEADERS",
    "Column",
    "ParsedRow",
    "match_headers",
    "missing_headers",
    "parse_row",
    "repeated_rows",
]


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    label_en: str
    label_ar: str
    max_length: int = 200
    aliases: tuple[str, ...] = ()


#: Template order. ``key`` is the patient field (``age_years`` estimates a date of birth).
COLUMNS: tuple[Column, ...] = (
    Column("full_name_ar", "Name (Arabic)", "الاسم بالعربية", 200, ("arabic name", "الاسم")),
    Column("full_name_en", "Name (English)", "الاسم بالإنجليزية", 200, ("english name", "name")),
    Column("sex", "Sex", "الجنس", 10, ("gender", "النوع")),
    Column("date_of_birth", "Date of birth", "تاريخ الميلاد", 20, ("dob", "birth date")),
    Column("age_years", "Age (years)", "العمر (سنوات)", 5, ("age", "العمر")),
    Column("phone", "Phone", "الهاتف", 30, ("mobile", "phone number", "رقم الهاتف")),
    Column("phone_alt", "Other phone", "هاتف آخر", 30, ("phone 2", "alternate phone")),
    Column("address", "Address", "العنوان", 300),
    Column("national_id", "National ID", "الرقم الوطني", 50, ("nid", "id number")),
    Column(
        "emergency_contact_name",
        "Emergency contact",
        "جهة الاتصال للطوارئ",
        200,
        ("emergency contact name",),
    ),
    Column(
        "emergency_contact_phone",
        "Emergency contact phone",
        "هاتف الطوارئ",
        30,
        ("emergency phone",),
    ),
    Column("notes", "Notes", "ملاحظات", 1000),
)

#: Header groups of which at least one column must be present.
REQUIRED_HEADERS: tuple[tuple[str, ...], ...] = (("full_name_ar", "full_name_en"), ("sex",))

_SEX = {
    "male": "male",
    "m": "male",
    "ذكر": "male",
    "female": "female",
    "f": "female",
    "انثى": "female",
    "أنثى": "female",
    "انثي": "female",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")
_SPACES = re.compile(r"\s+")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _header_key(text: Any) -> str:
    raw = "" if text is None else str(text)
    return _SPACES.sub("", raw.strip().lower().replace("_", "").replace("-", ""))


def _header_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for column in COLUMNS:
        for name in (column.key, column.label_en, column.label_ar, *column.aliases):
            index.setdefault(_header_key(name), column.key)
    return index


_HEADERS = _header_index()


def match_headers(header_row: Iterable[Any]) -> dict[int, str]:
    """Column position to field key for the recognised headers (the first match wins)."""
    found: dict[int, str] = {}
    taken: set[str] = set()
    for position, cell in enumerate(header_row):
        key = _HEADERS.get(_header_key(cell))
        if key is not None and key not in taken:
            found[position] = key
            taken.add(key)
    return found


def missing_headers(matched: Mapping[int, str]) -> list[str]:
    """The required header groups the sheet lacks, as ``a|b`` strings."""
    present = set(matched.values())
    return ["|".join(group) for group in REQUIRED_HEADERS if not present & set(group)]


@dataclass(slots=True)
class ParsedRow:
    """One sheet row read into registration fields, with its error codes."""

    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    #: Fields the errors concern, parallel to ``errors``.
    error_fields: list[str] = field(default_factory=list)

    def add_error(self, code: str, field_name: str) -> None:
        self.errors.append(code)
        self.error_fields.append(field_name)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # a phone typed as a number arrives as 912345678.0
    return " ".join(str(value).split())


def _parse_date(value: Any) -> date | None:
    """A date, or None when unreadable. Raises ``ValueError`` for an unreadable text."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value).translate(_ARABIC_DIGITS)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a calendar date
        except ValueError:
            continue
    raise ValueError(text)


def _parse_age(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(value)
    if isinstance(value, int | float):
        number = float(value)
    else:
        number = float(_text(value).translate(_ARABIC_DIGITS))
    if not number.is_integer():
        raise ValueError(value)
    return int(number)


def parse_row(cells: Mapping[str, Any], *, today: date) -> ParsedRow | None:
    """Read one row (field key to cell value) into registration data and error codes.

    Returns None for a blank row (skipped, like the empty rows at the end of a sheet).
    """
    if not any(_text(v) for v in cells.values()):
        return None
    row = ParsedRow()
    by_key = {c.key: c for c in COLUMNS}
    for key, column in by_key.items():
        if key in ("sex", "date_of_birth", "age_years"):
            continue
        value = _text(cells.get(key))
        if len(value) > column.max_length:
            row.add_error("VALUE_TOO_LONG", key)
            value = value[: column.max_length]
        row.data[key] = value

    raw_sex = _text(cells.get("sex")).lower()
    sex = _SEX.get(raw_sex, "")
    row.data["sex"] = sex
    if not sex:
        row.add_error("INVALID_SEX", "sex")

    if not (row.data["full_name_ar"] or row.data["full_name_en"]):
        row.add_error("NAME_REQUIRED", "full_name_ar")

    row.data["date_of_birth"] = None
    row.data["age_years"] = None
    try:
        dob = _parse_date(cells.get("date_of_birth"))
    except ValueError:
        row.add_error("INVALID_DATE_OF_BIRTH", "date_of_birth")
        dob = None
    if dob is not None:
        if dob > today or dob.year < today.year - 130:
            row.add_error("INVALID_DATE_OF_BIRTH", "date_of_birth")
        else:
            row.data["date_of_birth"] = dob
    if row.data["date_of_birth"] is None and "date_of_birth" not in row.error_fields:
        try:
            age = _parse_age(cells.get("age_years"))
        except ValueError:
            row.add_error("INVALID_AGE", "age_years")
            age = None
        if age is not None:
            if 0 <= age <= 130:
                row.data["age_years"] = age
            else:
                row.add_error("INVALID_AGE", "age_years")
    return row


def repeated_rows(keys: Iterable[tuple[int, set[str]]]) -> dict[int, int]:
    """Rows whose identity keys (normalized phones, national ID) repeat an earlier row.

    ``keys`` gives each row number with its keys; the result maps a repeating row to the
    first row that had one of its keys.
    """
    first: dict[str, int] = {}
    repeats: dict[int, int] = {}
    for row_no, row_keys in keys:
        earlier = sorted(first[k] for k in row_keys if k in first)
        if earlier:
            repeats[row_no] = earlier[0]
        for k in row_keys:
            first.setdefault(k, row_no)
    return repeats
