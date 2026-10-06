"""Failed-login lockout policy (FEATURES 14.4).

After ``MAX_FAILED_ATTEMPTS`` consecutive failures the account is locked for
``LOCK_DURATION``. While locked, attempts are refused without checking the password and
do not extend the lock. Once the lock expires the counter starts again from zero.
A successful login resets the counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

__all__ = [
    "LOCK_DURATION",
    "MAX_FAILED_ATTEMPTS",
    "LockState",
    "attempts_remaining",
    "is_locked",
    "normalize",
    "register_failure",
    "register_success",
]

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class LockState:
    """Persisted lockout fields of an account."""

    failed_count: int = 0
    locked_until: datetime | None = None


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def is_locked(state: LockState, now: datetime) -> bool:
    """True while ``now`` is before ``locked_until``."""
    _require_aware(now)
    return state.locked_until is not None and now < state.locked_until


def normalize(state: LockState, now: datetime) -> LockState:
    """Clear an expired lock (and its counter); otherwise return ``state`` unchanged."""
    _require_aware(now)
    if state.locked_until is not None and now >= state.locked_until:
        return LockState()
    return state


def register_failure(
    state: LockState,
    now: datetime,
    *,
    max_attempts: int = MAX_FAILED_ATTEMPTS,
    lock_for: timedelta = LOCK_DURATION,
) -> LockState:
    """Return the state after one more failed attempt at ``now``.

    A currently locked account is returned unchanged (the lock is not extended).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    current = normalize(state, now)
    if is_locked(current, now):
        return current
    count = current.failed_count + 1
    if count >= max_attempts:
        return LockState(failed_count=count, locked_until=now + lock_for)
    return LockState(failed_count=count, locked_until=None)


def register_success() -> LockState:
    """State after a successful login: counter and lock cleared."""
    return LockState()


def attempts_remaining(state: LockState, *, max_attempts: int = MAX_FAILED_ATTEMPTS) -> int:
    """How many more failures are allowed before the account locks."""
    return max(0, max_attempts - state.failed_count)
