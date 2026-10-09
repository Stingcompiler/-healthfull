"""The shape every report shares: filters in, metrics and sections of typed rows out.

A report is plain data (dataclasses, Decimals, dates, bilingual names), so one serializer
(``apps.reports.api``), one Excel writer (``apps.reports.export``) and one screen serve every
report. Column, section, metric and report titles live in ``apps.reports.labels`` (Arabic
and English), keyed by the ``key`` fields below.

Cell values by column ``kind``:

* ``money``: ``Decimal`` (2 places, ``domain.money``); serialized as a string.
* ``int`` / ``days`` / ``minutes``: ``int``. ``percent``: ``Decimal`` (one place) or ``None``.
* ``date`` / ``datetime``: ``date`` / aware ``datetime``.
* ``text`` / ``code``: ``str`` (``code``: an identifier shown left to right, e.g. a file no).
* ``name``: a bilingual ``{"ar": ..., "en": ...}`` mapping (departments, people, services).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from django.utils import timezone

from domain.errors import DomainError
from domain.money import ZERO, money

ColumnKind = Literal[
    "text", "code", "name", "money", "int", "days", "minutes", "percent", "date", "datetime"
]
MetricTone = Literal["neutral", "primary", "success", "warning", "danger", "info"]
FilterName = Literal["dates", "department", "user", "days"]

#: Longest period one report covers (a year and a day, for leap years).
MAX_RANGE_DAYS = 366
#: Most detail rows one section returns; the screen and the export say when rows were cut.
MAX_ROWS = 2000

Name = dict[str, str]
Cell = Decimal | int | str | date | datetime | Name | None


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    kind: ColumnKind = "text"


@dataclass(slots=True)
class Section:
    key: str
    columns: list[Column]
    rows: list[dict[str, Cell]] = field(default_factory=list)
    totals: dict[str, Cell] | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    value: Cell
    kind: ColumnKind = "money"
    tone: MetricTone = "neutral"


@dataclass(frozen=True, slots=True)
class Option:
    id: int
    name: Name


@dataclass(frozen=True, slots=True)
class Filters:
    """What a report is asked for. Dates are local (Africa/Khartoum) calendar days."""

    date_from: date
    date_to: date
    department_id: int | None = None
    user_id: int | None = None
    days: int | None = None


@dataclass(slots=True)
class Report:
    key: str
    filters: Filters
    metrics: list[Metric] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    departments: list[Option] = field(default_factory=list)
    users: list[Option] = field(default_factory=list)
    generated_at: datetime = field(default_factory=timezone.now)

    def section(self, key: str) -> Section:
        return next(s for s in self.sections if s.key == key)

    def metric(self, key: str) -> Cell:
        return next(m.value for m in self.metrics if m.key == key)


DefaultRange = Literal["today", "week", "month", "none"]


def resolve_filters(
    *,
    date_from: date | None,
    date_to: date | None,
    department_id: int | None = None,
    user_id: int | None = None,
    days: int | None = None,
    default: DefaultRange = "month",
    today: date | None = None,
) -> Filters:
    """Fill the default period and check the range.

    ``today`` and ``week`` end today; ``month`` covers the last 30 days. A missing start takes
    the default length back from the end.

    Raises:
        DomainError: ``INVALID_DATE_RANGE`` (end before start), ``REPORT_RANGE_TOO_LONG``.
    """
    day = today or timezone.localdate()
    end = date_to or (date_from if date_from and date_from > day else day)
    back = {"today": 0, "week": 6, "month": 29, "none": 0}[default]
    start = date_from or (end - timedelta(days=back))
    if end < start:
        raise DomainError("INVALID_DATE_RANGE", "The end date is before the start date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise DomainError(
            "REPORT_RANGE_TOO_LONG",
            f"A report covers at most {MAX_RANGE_DAYS} days",
            max_days=MAX_RANGE_DAYS,
        )
    return Filters(start, end, department_id, user_id, days)


def window(filters: Filters) -> tuple[datetime, datetime]:
    """The half-open local-time window ``[start of date_from, start of the day after date_to)``."""
    tz = timezone.get_current_timezone()
    start = datetime.combine(filters.date_from, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(filters.date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start, end


def name(row: Any, *, ar: str = "name_ar", en: str = "name_en") -> Name:
    """Bilingual name of a model row (each side falls back to the other)."""
    if row is None:
        return {"ar": "", "en": ""}
    a, e = str(getattr(row, ar, "") or ""), str(getattr(row, en, "") or "")
    return {"ar": a or e, "en": e or a}


def person(user: Any) -> Name:
    """Display name of a user (full name, else username)."""
    if user is None:
        return {"ar": "", "en": ""}
    return {"ar": user.display_name_ar, "en": user.display_name_en}


def patient_name(p: Any) -> Name:
    return name(p, ar="full_name_ar", en="full_name_en")


def label(ar: str, en: str) -> Name:
    return {"ar": ar, "en": en}


def m(value: Decimal | int | None) -> Decimal:
    """Money from a possibly empty aggregate."""
    return money(value if value is not None else ZERO)


def sum_column(rows: list[dict[str, Cell]], key: str) -> Decimal:
    total = ZERO
    for row in rows:
        value = row.get(key)
        if isinstance(value, Decimal):
            total += value
    return money(total)


def count_column(rows: list[dict[str, Cell]], key: str) -> int:
    return sum(int(v) for row in rows if isinstance(v := row.get(key), int))


def totals(rows: list[dict[str, Cell]], columns: list[Column], first: str) -> dict[str, Cell]:
    """A totals row: money and count columns summed, ``first`` left for the label."""
    out: dict[str, Cell] = {}
    for col in columns:
        if col.key == first:
            continue
        if col.kind == "money":
            out[col.key] = sum_column(rows, col.key)
        elif col.kind == "int":
            out[col.key] = count_column(rows, col.key)
    return out


def capped[T](items: list[T]) -> tuple[list[T], bool]:
    """At most ``MAX_ROWS`` items, and whether more existed (fetch ``MAX_ROWS + 1``)."""
    return items[:MAX_ROWS], len(items) > MAX_ROWS


def age_days(since: datetime | date | None, today: date) -> int:
    if since is None:
        return 0
    day = timezone.localdate(since) if isinstance(since, datetime) else since
    return max(0, (today - day).days)
