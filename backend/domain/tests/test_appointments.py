"""Appointment state machine, request expiry and review window (ADR 0029 A8, C, E)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.appointments import (
    EDGES,
    HOLDS_SLOT,
    AppointmentState,
    can_transition,
    check_approval,
    check_review_window,
    check_transition,
    holds_slot,
    is_expired,
    request_expiry,
)
from domain.errors import DomainError

S = AppointmentState
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
ALLOWED = {
    (S.REQUESTED, S.BOOKED),
    (S.REQUESTED, S.CANCELLED),
    (S.BOOKED, S.ARRIVED),
    (S.BOOKED, S.RESCHEDULED),
    (S.BOOKED, S.CANCELLED),
    (S.BOOKED, S.NO_SHOW),
}


@pytest.mark.parametrize("current", list(S))
@pytest.mark.parametrize("target", list(S))
def test_every_edge_is_allowed_or_refused_as_specified(current: S, target: S) -> None:
    allowed = (current, target) in ALLOWED
    assert can_transition(current, target) is allowed
    if allowed:
        check_transition(current, target)
        return
    with pytest.raises(DomainError) as exc:
        check_transition(current, target)
    expected = "APPOINTMENT_NOT_REQUESTED" if target == S.BOOKED else "APPOINTMENT_NOT_BOOKED"
    assert exc.value.code == expected


def test_edges_table_is_the_specified_one() -> None:
    assert {(a, b) for a, targets in EDGES.items() for b in targets} == ALLOWED
    assert frozenset({S.REQUESTED, S.BOOKED}) == HOLDS_SLOT


def test_terminal_states_have_no_way_out() -> None:
    for state in (S.ARRIVED, S.CANCELLED, S.NO_SHOW, S.RESCHEDULED):
        assert not any(can_transition(state, t) for t in S)


minutes = st.integers(min_value=0, max_value=60 * 24 * 14)


@given(created=minutes, start_after=minutes, ttl_h=st.integers(1, 168), lead_m=minutes)
def test_request_expiry_is_the_earlier_of_ttl_and_lead(
    created: int, start_after: int, ttl_h: int, lead_m: int
) -> None:
    created_at = T0 + timedelta(minutes=created)
    starts_at = created_at + timedelta(minutes=start_after)
    ttl, lead = timedelta(hours=ttl_h), timedelta(minutes=lead_m)
    expires = request_expiry(created_at, starts_at, ttl=ttl, lead=lead)
    assert expires <= created_at + ttl
    assert expires <= starts_at - lead
    assert expires in (created_at + ttl, starts_at - lead)


def test_default_expiry_examples() -> None:
    ttl, lead = timedelta(hours=24), timedelta(minutes=60)
    # A slot three days away: the request lives 24 hours.
    far = T0 + timedelta(days=3)
    assert request_expiry(T0, far, ttl=ttl, lead=lead) == T0 + ttl
    # A slot in five hours: the request lapses at the lead time before it.
    near = T0 + timedelta(hours=5)
    assert request_expiry(T0, near, ttl=ttl, lead=lead) == near - lead


@given(window=st.integers(min_value=-600, max_value=600), floor=st.integers(0, 600))
def test_review_window_floor(window: int, floor: int) -> None:
    expires = T0 + timedelta(minutes=window)
    if window >= floor:
        check_review_window(expires, now=T0, min_review=timedelta(minutes=floor))
    else:
        with pytest.raises(DomainError) as exc:
            check_review_window(expires, now=T0, min_review=timedelta(minutes=floor))
        assert exc.value.code == "ONLINE_REVIEW_WINDOW_TOO_SHORT"
        assert exc.value.details == {"minutes": floor}


def test_a_request_is_never_born_expired() -> None:
    """With the floor, a slot just past the lead time cannot be requested (ADR 0029 C)."""
    lead = timedelta(minutes=60)
    starts = T0 + lead  # the earliest bookable start
    expires = request_expiry(T0, starts, ttl=timedelta(hours=24), lead=lead)
    assert expires == T0
    with pytest.raises(DomainError):
        check_review_window(expires, now=T0, min_review=timedelta(minutes=30))


@given(offset=st.integers(-1000, 1000))
def test_expiry_and_holding(offset: int) -> None:
    expires = T0 + timedelta(minutes=offset)
    expired = offset <= 0
    assert is_expired(expires, now=T0) is expired
    assert holds_slot("requested", expires, now=T0) is not expired
    assert holds_slot("booked", None, now=T0)
    assert not is_expired(None, now=T0)
    for other in ("arrived", "cancelled", "no_show", "rescheduled"):
        assert not holds_slot(other, expires, now=T0)


def test_approval_needs_an_unexpired_request() -> None:
    check_approval("requested", T0 + timedelta(minutes=1), now=T0)
    with pytest.raises(DomainError) as exc:
        check_approval("requested", T0, now=T0)
    assert exc.value.code == "ONLINE_REQUEST_EXPIRED"
    for status in ("booked", "cancelled", "arrived"):
        with pytest.raises(DomainError) as exc:
            check_approval(status, None, now=T0)
        assert exc.value.code == "APPOINTMENT_NOT_REQUESTED"


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        request_expiry(datetime(2026, 1, 1), T0, ttl=timedelta(hours=1), lead=timedelta(minutes=1))
