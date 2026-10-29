"""Patient reschedule rules (ADR 0029 A7) and the patient-facing booking status (plan 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.appointments import AppointmentState
from domain.errors import DomainError
from domain.portal import BookingRules, can_reschedule, check_reschedule
from domain.portal_status import BookingDisplay, booking_display

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def rules(*, allowed: bool = True, cutoff_hours: int = 2) -> BookingRules:
    return BookingRules(
        lead=timedelta(minutes=60),
        horizon_days=30,
        max_open=3,
        cancel_cutoff=timedelta(hours=2),
        reschedule_allowed=allowed,
        reschedule_cutoff=timedelta(hours=cutoff_hours),
    )


@given(minutes_before=st.integers(-600, 6000), cutoff=st.integers(0, 48))
def test_reschedule_until_the_cutoff(minutes_before: int, cutoff: int) -> None:
    start = T0 + timedelta(minutes=minutes_before)
    r = rules(cutoff_hours=cutoff)
    ok = minutes_before >= cutoff * 60
    assert can_reschedule(start, booked=True, now=T0, rules=r) is ok
    if ok:
        check_reschedule(start, booked=True, now=T0, rules=r)
    else:
        with pytest.raises(DomainError) as exc:
            check_reschedule(start, booked=True, now=T0, rules=r)
        assert exc.value.code == "PORTAL_RESCHEDULE_TOO_LATE"
        assert exc.value.details == {"cutoff_hours": cutoff}


def test_reschedule_switched_off_or_not_booked() -> None:
    start = T0 + timedelta(days=3)
    with pytest.raises(DomainError) as exc:
        check_reschedule(start, booked=True, now=T0, rules=rules(allowed=False))
    assert exc.value.code == "PORTAL_RESCHEDULE_DISABLED"
    assert not can_reschedule(start, booked=True, now=T0, rules=rules(allowed=False))
    with pytest.raises(DomainError) as exc:
        check_reschedule(start, booked=False, now=T0, rules=rules())
    assert exc.value.code == "APPOINTMENT_NOT_BOOKED"


def test_negative_cutoff_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        rules(cutoff_hours=-1)


reasons = st.sampled_from(
    [None, "PATIENT_REQUEST", "ONLINE_REQUEST_EXPIRED", "ONLINE_REJECTED", "DOCTOR_UNAVAILABLE"]
)


@given(
    status=st.sampled_from(list(AppointmentState)),
    reason=reasons,
    was_request=st.booleans(),
    expired=st.booleans(),
)
def test_booking_display_is_total(
    status: AppointmentState, reason: str | None, was_request: bool, expired: bool
) -> None:
    shown = booking_display(status, cancel_reason=reason, was_request=was_request, expired=expired)
    assert shown in set(BookingDisplay)


@pytest.mark.parametrize(
    ("status", "reason", "was_request", "expired", "shown"),
    [
        ("requested", None, True, False, "awaiting_approval"),
        ("requested", None, True, True, "expired"),
        ("booked", None, False, False, "confirmed"),
        ("arrived", None, False, False, "received"),
        ("rescheduled", None, False, False, "moved"),
        ("no_show", None, False, False, "missed"),
        ("cancelled", "PATIENT_REQUEST", True, False, "cancelled_by_you"),
        ("cancelled", "ONLINE_REQUEST_EXPIRED", True, False, "expired"),
        ("cancelled", "ONLINE_REJECTED", True, False, "declined"),
        ("cancelled", "DOCTOR_UNAVAILABLE", True, False, "declined"),
        ("cancelled", "DOCTOR_UNAVAILABLE", False, False, "cancelled_by_center"),
    ],
)
def test_booking_display_examples(
    status: str, reason: str | None, was_request: bool, expired: bool, shown: str
) -> None:
    assert (
        booking_display(status, cancel_reason=reason, was_request=was_request, expired=expired)
        == shown
    )
