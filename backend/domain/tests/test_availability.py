"""Free slots = schedule sessions minus held bookings minus time off (ADR 0029 C)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.availability import Session, free_slots, overlaps

DAY = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def at(minute: int) -> datetime:
    return DAY + timedelta(minutes=minute)


@st.composite
def sessions(draw: st.DrawFn) -> list[Session]:
    """Up to three non-overlapping sessions of one day (the schedule rule)."""
    count = draw(st.integers(0, 3))
    cuts = sorted(draw(st.lists(st.integers(0, 24 * 60), min_size=2 * count, max_size=2 * count)))
    out = []
    for i in range(count):
        start, end = cuts[2 * i], cuts[2 * i + 1]
        if end > start:
            out.append(Session(at(start), at(end), timedelta(minutes=draw(st.integers(5, 60)))))
    return out


ranges = st.lists(
    st.tuples(st.integers(0, 24 * 60), st.integers(1, 240)).map(
        lambda t: (at(t[0]), at(t[0] + t[1]))
    ),
    max_size=8,
)


@given(day=sessions(), bookings=ranges, time_off=ranges)
def test_no_offered_slot_overlaps_anything(
    day: list[Session],
    bookings: list[tuple[datetime, datetime]],
    time_off: list[tuple[datetime, datetime]],
) -> None:
    busy = bookings + time_off
    offered = free_slots(day, busy)
    for start, end in offered:
        assert end > start
        assert not any(overlaps(start, end, s, e) for s, e in busy)
        # Inside one session, on its grid.
        assert any(
            s.start <= start
            and end <= s.end
            and (start - s.start) % s.step == timedelta(0)
            and end - start == s.step
            for s in day
        )
    # Offered slots never overlap each other.
    for i, (a0, a1) in enumerate(offered):
        for b0, b1 in offered[i + 1 :]:
            assert not overlaps(a0, a1, b0, b1)


@given(day=sessions(), bookings=ranges, time_off=ranges)
def test_every_free_whole_slot_is_offered(
    day: list[Session],
    bookings: list[tuple[datetime, datetime]],
    time_off: list[tuple[datetime, datetime]],
) -> None:
    busy = bookings + time_off
    offered = set(free_slots(day, busy))
    for s in day:
        start = s.start
        while start + s.step <= s.end:
            end = start + s.step
            free = not any(overlaps(start, end, b0, b1) for b0, b1 in busy)
            assert ((start, end) in offered) is free
            start = end


def test_back_to_back_ranges_do_not_overlap() -> None:
    assert not overlaps(at(0), at(15), at(15), at(30))
    assert overlaps(at(0), at(16), at(15), at(30))
    session = Session(at(9 * 60), at(10 * 60), timedelta(minutes=15))
    # A booking 9:15-9:30 and time off from 9:45: 9:00 and 9:30 stay free.
    offered = free_slots([session], [(at(555), at(570)), (at(585), at(24 * 60))])
    assert offered == [(at(540), at(555)), (at(570), at(585))]


def test_session_shape_is_checked() -> None:
    with pytest.raises(ValueError, match="positive"):
        Session(at(0), at(60), timedelta(0))
    with pytest.raises(ValueError, match="aware"):
        Session(datetime(2026, 1, 1), at(60), timedelta(minutes=5))
