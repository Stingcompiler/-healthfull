"""A doctor's weekly clinic hours (FEATURES 13.2).

A schedule is a list of weekly sessions: a weekday (0 = Monday ... 6 = Sunday, as Python's
``date.weekday()``), a start and end time, and the appointment slot length. Sessions of one
weekday may touch (08:00-12:00 and 12:00-14:00) but never overlap, so a time of day belongs
to at most one session and appointment slots are never offered twice.

Error codes: ``SCHEDULE_INVALID_WEEKDAY``, ``SCHEDULE_INVALID_SPAN``,
``SCHEDULE_INVALID_SLOT``, ``SCHEDULE_OVERLAP``, ``SCHEDULE_TOO_LONG``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from itertools import pairwise

from domain.errors import DomainError

__all__ = [
    "MAX_SESSIONS",
    "MAX_SLOT_MINUTES",
    "MIN_SLOT_MINUTES",
    "WeeklySession",
    "validate_weekly_schedule",
]

MIN_SLOT_MINUTES = 5
MAX_SLOT_MINUTES = 240
#: More sessions than this is a data-entry mistake (seven days of several sessions each).
MAX_SESSIONS = 50


@dataclass(frozen=True, slots=True)
class WeeklySession:
    weekday: int
    start: time
    end: time
    slot_minutes: int


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _check_session(session: WeeklySession) -> None:
    if not 0 <= session.weekday <= 6:
        raise DomainError(
            "SCHEDULE_INVALID_WEEKDAY",
            "Weekday must be 0 (Monday) to 6 (Sunday)",
            weekday=session.weekday,
        )
    if session.end <= session.start:
        raise DomainError(
            "SCHEDULE_INVALID_SPAN",
            "A session must end after it starts",
            weekday=session.weekday,
            start=_hhmm(session.start),
            end=_hhmm(session.end),
        )
    span = _minutes(session.end) - _minutes(session.start)
    if not MIN_SLOT_MINUTES <= session.slot_minutes <= min(MAX_SLOT_MINUTES, span):
        raise DomainError(
            "SCHEDULE_INVALID_SLOT",
            "Slot length must be 5-240 minutes and fit in the session",
            weekday=session.weekday,
            slot_minutes=session.slot_minutes,
        )


def validate_weekly_schedule(sessions: Sequence[WeeklySession]) -> None:
    """Check every session, then that no two sessions of a weekday overlap.

    Raises:
        DomainError: see the module docstring. ``SCHEDULE_OVERLAP`` names the weekday and the
            overlapping time range.
    """
    if len(sessions) > MAX_SESSIONS:
        raise DomainError(
            "SCHEDULE_TOO_LONG", "Too many sessions in one schedule", maximum=MAX_SESSIONS
        )
    for session in sessions:
        _check_session(session)
    ordered = sorted(sessions, key=lambda s: (s.weekday, s.start, s.end))
    for before, after in pairwise(ordered):
        if before.weekday == after.weekday and after.start < before.end:
            raise DomainError(
                "SCHEDULE_OVERLAP",
                "Two sessions on the same day overlap",
                weekday=after.weekday,
                start=_hhmm(after.start),
                end=_hhmm(min(before.end, after.end)),
            )
