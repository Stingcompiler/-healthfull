from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.lockout import (
    LOCK_DURATION,
    MAX_FAILED_ATTEMPTS,
    LockState,
    attempts_remaining,
    is_locked,
    normalize,
    register_failure,
    register_success,
)

T0 = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
gaps = st.lists(st.integers(min_value=0, max_value=60), min_size=1, max_size=20)


def _fail_n(n: int, start: datetime = T0, gap: timedelta = timedelta(seconds=1)) -> LockState:
    state = LockState()
    now = start
    for _ in range(n):
        state = register_failure(state, now)
        now += gap
    return state


@given(st.integers(min_value=0, max_value=MAX_FAILED_ATTEMPTS - 1))
def test_fewer_than_max_failures_never_lock(n: int) -> None:
    state = _fail_n(n)
    assert state.failed_count == n
    assert state.locked_until is None
    assert attempts_remaining(state) == MAX_FAILED_ATTEMPTS - n


def test_fifth_failure_locks_for_fifteen_minutes() -> None:
    state = _fail_n(MAX_FAILED_ATTEMPTS, gap=timedelta(0))
    assert state.failed_count == MAX_FAILED_ATTEMPTS
    assert state.locked_until == T0 + LOCK_DURATION
    assert timedelta(minutes=15) == LOCK_DURATION
    assert is_locked(state, T0)
    assert is_locked(state, T0 + LOCK_DURATION - timedelta(microseconds=1))
    assert not is_locked(state, T0 + LOCK_DURATION)
    assert attempts_remaining(state) == 0


@given(st.integers(min_value=0, max_value=10_000))
def test_failures_while_locked_do_not_extend_the_lock(seconds: int) -> None:
    locked = _fail_n(MAX_FAILED_ATTEMPTS, gap=timedelta(0))
    now = T0 + timedelta(seconds=seconds)
    after = register_failure(locked, now)
    if now < T0 + LOCK_DURATION:
        assert after == locked
    else:
        # Lock expired: counter restarts, this failure is the first of a new run.
        assert after == LockState(failed_count=1, locked_until=None)


def test_normalize_clears_only_expired_locks() -> None:
    locked = _fail_n(MAX_FAILED_ATTEMPTS, gap=timedelta(0))
    assert normalize(locked, T0) == locked
    assert normalize(locked, T0 + LOCK_DURATION) == LockState()
    partial = LockState(failed_count=3)
    assert normalize(partial, T0) == partial


@given(gaps, st.integers(min_value=0, max_value=10_000))
def test_failure_after_success_starts_a_fresh_count(gap_seconds: list[int], later: int) -> None:
    """Whatever came before, a success means the next failure is the first of a new run."""
    state = LockState()
    now = T0
    for g in gap_seconds:
        now += timedelta(seconds=g)
        state = register_failure(state, now)
    # The service only reaches register_success() for an unlocked account (a locked one is
    # refused before the password is checked), so model the success at an unlocked moment.
    unlocked_at = max(now, state.locked_until or now)
    assert not is_locked(normalize(state, unlocked_at), unlocked_at)
    after_success = register_success()
    assert attempts_remaining(after_success) == MAX_FAILED_ATTEMPTS
    nxt = register_failure(after_success, unlocked_at + timedelta(seconds=later))
    assert nxt == LockState(failed_count=1, locked_until=None)


@given(gaps)
def test_counter_is_bounded_and_lock_is_consistent(gap_seconds: list[int]) -> None:
    state = LockState()
    now = T0
    for g in gap_seconds:
        now += timedelta(seconds=g)
        state = register_failure(state, now)
        assert 1 <= state.failed_count <= MAX_FAILED_ATTEMPTS
        assert (state.locked_until is not None) == (state.failed_count >= MAX_FAILED_ATTEMPTS)
        if state.locked_until is not None:
            assert now < state.locked_until <= now + LOCK_DURATION


def test_custom_policy() -> None:
    state = register_failure(LockState(), T0, max_attempts=1, lock_for=timedelta(minutes=1))
    assert state.locked_until == T0 + timedelta(minutes=1)
    with pytest.raises(ValueError, match="max_attempts"):
        register_failure(LockState(), T0, max_attempts=0)


def test_naive_datetimes_are_rejected() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        is_locked(LockState(), naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        register_failure(LockState(), naive)
