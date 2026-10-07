"""Fixed-window rate limiting (FEATURES 14.4: login abuse control).

A window opens at the first counted event and lasts ``window``. Events inside it add to
the count; once the count reaches ``limit`` further events are refused until the window
ends. The first event after the window ends opens a new window with a count of one.

Pure functions over a tiny state record, so services can persist the state anywhere
(``apps.core.models.LoginThrottle``) and lock it with ``SELECT ... FOR UPDATE``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

__all__ = ["WindowState", "hit", "is_limited", "retry_after_seconds"]


@dataclass(frozen=True, slots=True)
class WindowState:
    """Persisted counter of one throttle key."""

    count: int = 0
    window_started_at: datetime | None = None


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _require_rule(limit: int, window: timedelta) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if window <= timedelta(0):
        raise ValueError("window must be positive")


def _window_open(state: WindowState, now: datetime, window: timedelta) -> bool:
    return state.window_started_at is not None and now < state.window_started_at + window


def is_limited(state: WindowState, now: datetime, *, limit: int, window: timedelta) -> bool:
    """True while the current window is open and already holds ``limit`` events."""
    _require_aware(now)
    _require_rule(limit, window)
    return _window_open(state, now, window) and state.count >= limit


def hit(state: WindowState, now: datetime, *, window: timedelta) -> WindowState:
    """State after counting one more event at ``now``."""
    _require_aware(now)
    _require_rule(1, window)
    if not _window_open(state, now, window):
        return WindowState(count=1, window_started_at=now)
    return WindowState(count=state.count + 1, window_started_at=state.window_started_at)


def retry_after_seconds(state: WindowState, now: datetime, *, window: timedelta) -> int:
    """Whole seconds until the current window ends (0 when no window is open)."""
    _require_aware(now)
    if not _window_open(state, now, window) or state.window_started_at is None:
        return 0
    return max(1, math.ceil((state.window_started_at + window - now).total_seconds()))
