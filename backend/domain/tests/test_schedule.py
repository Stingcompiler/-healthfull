"""A doctor's weekly clinic hours (FEATURES 13.2)."""

from __future__ import annotations

from datetime import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.schedule import (
    MAX_SLOT_MINUTES,
    MIN_SLOT_MINUTES,
    WeeklySession,
    validate_weekly_schedule,
)


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _s(weekday: int, start: str, end: str, slot: int = 15) -> WeeklySession:
    return WeeklySession(weekday=weekday, start=_t(start), end=_t(end), slot_minutes=slot)


def _code(sessions: list[WeeklySession]) -> str:
    with pytest.raises(DomainError) as exc:
        validate_weekly_schedule(sessions)
    return exc.value.code


def test_empty_schedule_is_valid() -> None:
    validate_weekly_schedule([])


def test_seed_like_schedule_is_valid() -> None:
    validate_weekly_schedule(
        [_s(d, "08:00", "14:00") for d in (0, 1, 2, 3, 5, 6)] + [_s(4, "16:00", "20:00")]
    )


def test_two_sessions_on_one_day_may_touch() -> None:
    validate_weekly_schedule([_s(0, "08:00", "12:00"), _s(0, "12:00", "14:00")])


def test_overlap_on_the_same_day_is_refused() -> None:
    with pytest.raises(DomainError) as exc:
        validate_weekly_schedule([_s(2, "08:00", "12:00"), _s(2, "11:30", "14:00")])
    assert exc.value.code == "SCHEDULE_OVERLAP"
    assert exc.value.details == {"weekday": 2, "start": "11:30", "end": "12:00"}


def test_same_hours_on_different_days_are_fine() -> None:
    validate_weekly_schedule([_s(0, "08:00", "12:00"), _s(1, "08:00", "12:00")])


@pytest.mark.parametrize("weekday", [-1, 7, 10])
def test_weekday_out_of_range(weekday: int) -> None:
    assert _code([_s(weekday, "08:00", "09:00")]) == "SCHEDULE_INVALID_WEEKDAY"


@pytest.mark.parametrize(("start", "end"), [("09:00", "09:00"), ("10:00", "09:00")])
def test_end_must_follow_start(start: str, end: str) -> None:
    assert _code([_s(0, start, end)]) == "SCHEDULE_INVALID_SPAN"


@pytest.mark.parametrize("slot", [0, MIN_SLOT_MINUTES - 1, MAX_SLOT_MINUTES + 1])
def test_slot_length_out_of_range(slot: int) -> None:
    assert _code([_s(0, "08:00", "20:00", slot)]) == "SCHEDULE_INVALID_SLOT"


def test_slot_longer_than_the_session_is_refused() -> None:
    assert _code([_s(0, "08:00", "08:30", 45)]) == "SCHEDULE_INVALID_SLOT"


def test_too_many_sessions_are_refused() -> None:
    sessions = [_s(d % 7, f"{h:02d}:00", f"{h:02d}:30") for d in range(7) for h in range(8, 16)]
    assert len(sessions) > 50
    assert _code(sessions) == "SCHEDULE_TOO_LONG"


minutes = st.integers(min_value=0, max_value=24 * 60 - 1)


@st.composite
def sessions(draw: st.DrawFn) -> WeeklySession:
    weekday = draw(st.integers(min_value=0, max_value=6))
    a = draw(minutes)
    b = draw(minutes.filter(lambda m: m != a))
    lo, hi = min(a, b), max(a, b)
    slot = draw(st.integers(min_value=MIN_SLOT_MINUTES, max_value=MAX_SLOT_MINUTES))
    return WeeklySession(weekday, time(lo // 60, lo % 60), time(hi // 60, hi % 60), slot)


def _overlaps(a: WeeklySession, b: WeeklySession) -> bool:
    return a.weekday == b.weekday and a.start < b.end and b.start < a.end


def _span(s: WeeklySession) -> int:
    return (s.end.hour * 60 + s.end.minute) - (s.start.hour * 60 + s.start.minute)


@given(st.lists(sessions(), max_size=8))
def test_valid_exactly_when_no_overlap_and_slots_fit(items: list[WeeklySession]) -> None:
    expected_ok = all(s.slot_minutes <= _span(s) for s in items) and not any(
        _overlaps(a, b) for i, a in enumerate(items) for b in items[i + 1 :]
    )
    if expected_ok:
        validate_weekly_schedule(items)
    else:
        with pytest.raises(DomainError) as exc:
            validate_weekly_schedule(items)
        assert exc.value.code in {"SCHEDULE_OVERLAP", "SCHEDULE_INVALID_SLOT"}


@given(st.lists(sessions(), max_size=8))
def test_order_does_not_matter(items: list[WeeklySession]) -> None:
    """Per-session checks run before the overlap check, so the outcome is order-free."""

    def outcome(xs: list[WeeklySession]) -> str:
        try:
            validate_weekly_schedule(xs)
        except DomainError as exc:
            return exc.code
        return "ok"

    assert outcome(items) == outcome(list(reversed(items)))
