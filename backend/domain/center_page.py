"""The public center page of the patient portal: opening hours, today's status, which
announcements are shown, and the contact links built from the numbers staff typed.

Weekdays follow Python's ``date.weekday()`` (0 = Monday ... 6 = Sunday), like doctors'
schedules. A day is either closed or open from ``opens`` to ``closes`` on the same day
(no overnight span). An empty list of hours means the center has not published them.

Error codes: ``CENTER_HOURS_INVALID``, ``ANNOUNCEMENT_DATES_INVALID``,
``CENTER_WHATSAPP_INVALID``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Literal

from domain.errors import DomainError

__all__ = [
    "DayHours",
    "TodayStatus",
    "announcement_visible",
    "hours_json",
    "parse_hours",
    "tel_uri",
    "today_status",
    "validate_announcement_dates",
    "whatsapp_number",
]

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

TodayState = Literal["open", "opens_later", "closed_now", "closed_today"]


@dataclass(frozen=True, slots=True)
class DayHours:
    weekday: int
    closed: bool
    opens: time | None
    closes: time | None


@dataclass(frozen=True, slots=True)
class TodayStatus:
    weekday: int
    state: TodayState
    opens: time | None
    closes: time | None


def _invalid(message: str, **details: Any) -> DomainError:
    return DomainError("CENTER_HOURS_INVALID", message, **details)


def _time(value: object, weekday: int) -> time:
    if not isinstance(value, str) or not (m := _HHMM.match(value)):
        raise _invalid("Opening and closing times are HH:MM", weekday=weekday)
    return time(int(m.group(1)), int(m.group(2)))


def parse_hours(rows: Sequence[object]) -> list[DayHours]:
    """Validate the weekly hours staff entered: none at all, or each weekday exactly once.

    Raises:
        DomainError: ``CENTER_HOURS_INVALID`` (a weekday missing or repeated, a time that is
            not HH:MM, or an open day that does not close after it opens).
    """
    if not rows:
        return []
    days: dict[int, DayHours] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise _invalid("Each day is an object")
        weekday = row.get("weekday")
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise _invalid("Weekday is 0 (Monday) to 6 (Sunday)")
        if weekday in days:
            raise _invalid("A weekday is given twice", weekday=weekday)
        if row.get("closed") is True:
            days[weekday] = DayHours(weekday=weekday, closed=True, opens=None, closes=None)
            continue
        opens = _time(row.get("opens"), weekday)
        closes = _time(row.get("closes"), weekday)
        if closes <= opens:
            raise _invalid("A day closes after it opens", weekday=weekday)
        days[weekday] = DayHours(weekday=weekday, closed=False, opens=opens, closes=closes)
    if len(days) != 7:
        raise _invalid("Give every weekday, open or closed")
    return [days[d] for d in range(7)]


def hours_json(days: Sequence[DayHours]) -> list[dict[str, Any]]:
    """The stored form of parsed hours (``HH:MM`` strings, ``None`` on closed days)."""
    return [
        {
            "weekday": d.weekday,
            "closed": d.closed,
            "opens": f"{d.opens:%H:%M}" if d.opens else None,
            "closes": f"{d.closes:%H:%M}" if d.closes else None,
        }
        for d in days
    ]


def today_status(days: Sequence[DayHours], now: datetime) -> TodayStatus | None:
    """Whether the center is open at ``now`` (local wall time); ``None`` without hours."""
    if not days:
        return None
    day = days[now.weekday()]
    if day.closed or day.opens is None or day.closes is None:
        return TodayStatus(weekday=day.weekday, state="closed_today", opens=None, closes=None)
    moment = now.time().replace(second=0, microsecond=0, tzinfo=None)
    state: TodayState
    if moment < day.opens:
        state = "opens_later"
    elif moment < day.closes:
        state = "open"
    else:
        state = "closed_now"
    return TodayStatus(weekday=day.weekday, state=state, opens=day.opens, closes=day.closes)


def announcement_visible(
    *, active: bool, starts_on: date | None, ends_on: date | None, today: date
) -> bool:
    """An announcement is public while active and ``today`` is inside its dates (inclusive)."""
    if not active:
        return False
    if starts_on is not None and today < starts_on:
        return False
    return ends_on is None or today <= ends_on


def validate_announcement_dates(starts_on: date | None, ends_on: date | None) -> None:
    """Raises: DomainError ``ANNOUNCEMENT_DATES_INVALID`` when it ends before it starts."""
    if starts_on is not None and ends_on is not None and ends_on < starts_on:
        raise DomainError(
            "ANNOUNCEMENT_DATES_INVALID", "An announcement cannot end before it starts"
        )


def whatsapp_number(raw: str) -> str:
    """The international digits a ``wa.me`` link needs. Sudanese numbers may be typed
    locally (``0912 345 678``); ``+`` or ``00`` keeps any other country code. Empty stays
    empty.

    Raises:
        DomainError: ``CENTER_WHATSAPP_INVALID`` (not 8 to 15 digits after folding).
    """
    text = (raw or "").translate(_ARABIC_DIGITS).strip()
    if not text:
        return ""
    compact = re.sub(r"[\s\-().]", "", text)
    if compact.startswith("+"):
        digits = compact[1:]
    elif compact.startswith("00"):
        digits = compact[2:]
    elif compact.startswith("0"):
        digits = "249" + compact[1:]
    elif len(compact) == 9:
        digits = "249" + compact
    else:
        digits = compact
    if not (digits.isascii() and digits.isdigit() and 8 <= len(digits) <= 15):
        raise DomainError(
            "CENTER_WHATSAPP_INVALID", "Give a WhatsApp number like 0912 345 678 or +249..."
        )
    return digits


def tel_uri(raw: str) -> str:
    """A ``tel:`` link from a typed phone (a leading ``+`` and the digits); empty if none."""
    text = (raw or "").translate(_ARABIC_DIGITS).strip()
    digits = "".join(ch for ch in text if "0" <= ch <= "9")
    if not digits:
        return ""
    return f"tel:{'+' if text.startswith('+') else ''}{digits}"
