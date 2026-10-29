"""Appointment states, online requests and their expiry (FEATURES 2.5; ADR 0029 C, E). Pure.

State machine (ADR 0029 E), every other edge refused:

* ``requested -> booked`` (reception approves) ``| cancelled`` (rejected, expired, cancelled
  by the booker or on their behalf);
* ``booked -> arrived | rescheduled | cancelled | no_show``.

``arrived``, ``cancelled``, ``no_show`` and ``rescheduled`` are terminal. A ``requested``
booking holds its slot like a ``booked`` one until it expires: ``expires_at`` is
``min(created_at + request_ttl, starts_at - lead)`` (ADR 0029 A8) and a request is refused
when reception would have less than ``min_review`` to answer it (ADR 0029 C). Urgent patients
are never squeezed in: the slot rule is absolute (no overbooking, owner decision of
2026-10-29); they come as walk-in visits through the queue.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from domain.errors import DomainError

__all__ = [
    "EDGES",
    "HOLDS_SLOT",
    "AppointmentState",
    "can_transition",
    "check_approval",
    "check_review_window",
    "check_transition",
    "holds_slot",
    "is_expired",
    "request_expiry",
]


class AppointmentState(StrEnum):
    REQUESTED = "requested"
    BOOKED = "booked"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"


S = AppointmentState

#: The allowed edges (ADR 0029 E).
EDGES: Mapping[AppointmentState, frozenset[AppointmentState]] = MappingProxyType(
    {
        S.REQUESTED: frozenset({S.BOOKED, S.CANCELLED}),
        S.BOOKED: frozenset({S.ARRIVED, S.RESCHEDULED, S.CANCELLED, S.NO_SHOW}),
    }
)

#: States that keep the doctor's slot taken (the database exclusion constraint names them).
HOLDS_SLOT: frozenset[AppointmentState] = frozenset({S.REQUESTED, S.BOOKED})


def can_transition(current: str, target: str) -> bool:
    return S(target) in EDGES.get(S(current), frozenset())


def check_transition(current: str, target: str) -> None:
    """Raises:
    DomainError: ``APPOINTMENT_NOT_REQUESTED`` (approving anything but a request),
        ``APPOINTMENT_NOT_BOOKED`` (any other refused edge: the booking is not open).
    """
    if can_transition(current, target):
        return
    if S(target) == S.BOOKED:
        raise DomainError(
            "APPOINTMENT_NOT_REQUESTED", "Only a booking waiting for approval can be approved"
        )
    raise DomainError("APPOINTMENT_NOT_BOOKED", "The appointment is not open")


def _aware(*values: datetime) -> None:
    if any(v.tzinfo is None for v in values):
        raise ValueError("datetimes must be timezone-aware")


def request_expiry(
    created_at: datetime, starts_at: datetime, *, ttl: timedelta, lead: timedelta
) -> datetime:
    """When an unanswered request lapses: ``ttl`` after it was made, never later than the
    booking lead time before the slot (ADR 0029 A8)."""
    _aware(created_at, starts_at)
    return min(created_at + ttl, starts_at - lead)


def check_review_window(expires_at: datetime, *, now: datetime, min_review: timedelta) -> None:
    """Refuse a request reception could not answer in time (ADR 0029 C, at least
    ``min_review`` between now and its expiry).

    Raises:
        DomainError: ``ONLINE_REVIEW_WINDOW_TOO_SHORT`` (``details.minutes``).
    """
    _aware(expires_at, now)
    if expires_at - now < min_review:
        raise DomainError(
            "ONLINE_REVIEW_WINDOW_TOO_SHORT",
            "That time is too close for reception to confirm; choose a later time",
            minutes=int(min_review.total_seconds() // 60),
        )


def is_expired(expires_at: datetime | None, *, now: datetime) -> bool:
    return expires_at is not None and expires_at <= now


def holds_slot(status: str, expires_at: datetime | None, *, now: datetime) -> bool:
    """Whether the booking keeps its slot now: booked, or requested and not yet expired."""
    state = S(status)
    if state == S.REQUESTED:
        return not is_expired(expires_at, now=now)
    return state in HOLDS_SLOT


def check_approval(status: str, expires_at: datetime | None, *, now: datetime) -> None:
    """Reception approves a request: only a ``requested`` one that has not expired, whether
    or not the expiry sweep has run (ADR 0029 C).

    Raises:
        DomainError: ``APPOINTMENT_NOT_REQUESTED``, ``ONLINE_REQUEST_EXPIRED``.
    """
    check_transition(status, S.BOOKED)
    if is_expired(expires_at, now=now):
        raise DomainError("ONLINE_REQUEST_EXPIRED", "The request expired before it was approved")
