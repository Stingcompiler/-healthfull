"""A doctor's free slots (FEATURES 2.5; ADR 0029 C). Pure.

Availability = the day's schedule sessions, cut into slots of the session's length, minus
every busy range: appointments that hold a slot (``booked`` and unexpired ``requested``) and
the doctor's time off. Ranges are half-open ``[start, end)`` like the database exclusion
constraint (``tstzrange`` default bounds), so back-to-back slots never conflict.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

__all__ = ["Session", "free_slots", "overlaps"]

Range = tuple[datetime, datetime]


@dataclass(frozen=True, slots=True)
class Session:
    """One schedule session of a day: ``start`` to ``end`` cut into ``step`` slots."""

    start: datetime
    end: datetime
    step: timedelta

    def __post_init__(self) -> None:
        if self.step <= timedelta(0):
            raise ValueError("step must be positive")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open overlap: ``[a_start, a_end)`` and ``[b_start, b_end)`` share an instant."""
    return a_start < b_end and b_start < a_end


def free_slots(sessions: Iterable[Session], busy: Iterable[Range]) -> list[Range]:
    """The slots of ``sessions`` (whole slots only, in order) that overlap no ``busy`` range."""
    taken = list(busy)
    out: list[Range] = []
    for session in sorted(sessions, key=lambda s: s.start):
        start = session.start
        while start + session.step <= session.end:
            end = start + session.step
            if not any(overlaps(start, end, s, e) for s, e in taken):
                out.append((start, end))
            start = end
    return out
