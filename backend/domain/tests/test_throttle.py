from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.throttle import WindowState, hit, is_limited, retry_after_seconds

T0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=15)
gaps = st.lists(st.integers(min_value=0, max_value=1200), min_size=1, max_size=60)


def _replay(gap_seconds: list[int]) -> list[tuple[datetime, WindowState]]:
    state = WindowState()
    now = T0
    out: list[tuple[datetime, WindowState]] = []
    for g in gap_seconds:
        now += timedelta(seconds=g)
        state = hit(state, now, window=WINDOW)
        out.append((now, state))
    return out


def test_empty_state_is_never_limited() -> None:
    assert not is_limited(WindowState(), T0, limit=1, window=WINDOW)
    assert retry_after_seconds(WindowState(), T0, window=WINDOW) == 0


@given(gaps)
def test_count_equals_events_inside_the_current_window(gap_seconds: list[int]) -> None:
    """The count is exactly the number of events since the window opened."""
    history = _replay(gap_seconds)
    for i, (now, state) in enumerate(history):
        assert state.window_started_at is not None
        assert state.window_started_at <= now < state.window_started_at + WINDOW
        in_window = [t for t, _ in history[: i + 1] if t >= state.window_started_at]
        assert state.count == len(in_window)


@given(gaps, st.integers(min_value=1, max_value=20))
def test_limited_exactly_when_window_holds_limit_events(gap_seconds: list[int], limit: int) -> None:
    for now, state in _replay(gap_seconds):
        assert is_limited(state, now, limit=limit, window=WINDOW) == (state.count >= limit)


@given(st.integers(min_value=1, max_value=50))
def test_window_end_lifts_the_limit_and_restarts_the_count(limit: int) -> None:
    state = WindowState()
    for _ in range(limit):
        state = hit(state, T0, window=WINDOW)
    assert is_limited(state, T0, limit=limit, window=WINDOW)
    assert is_limited(state, T0 + WINDOW - timedelta(microseconds=1), limit=limit, window=WINDOW)
    assert not is_limited(state, T0 + WINDOW, limit=limit, window=WINDOW)
    assert hit(state, T0 + WINDOW, window=WINDOW) == WindowState(1, T0 + WINDOW)


@given(st.integers(min_value=0, max_value=int(WINDOW.total_seconds()) - 1))
def test_retry_after_counts_down_to_the_window_end(elapsed: int) -> None:
    state = hit(WindowState(), T0, window=WINDOW)
    now = T0 + timedelta(seconds=elapsed)
    assert retry_after_seconds(state, now, window=WINDOW) == WINDOW.total_seconds() - elapsed
    assert retry_after_seconds(state, T0 + WINDOW, window=WINDOW) == 0


def test_rules_and_clock_are_validated() -> None:
    with pytest.raises(ValueError, match="limit"):
        is_limited(WindowState(), T0, limit=0, window=WINDOW)
    with pytest.raises(ValueError, match="window"):
        hit(WindowState(), T0, window=timedelta(0))
    with pytest.raises(ValueError, match="timezone-aware"):
        hit(WindowState(), datetime(2026, 1, 1), window=WINDOW)
