"""A simulated clock for building dated demo history through the services (ADR 0017).

Every service reads the time from ``django.utils.timezone.now`` (and ``localdate``, which
calls it), and model ``auto_now`` fields do too. :func:`simulated_time` swaps that function
for a :class:`DemoClock` while the demo's past days are played, so a shift opened "on the
3rd at 08:00" really carries that time, and the price list, coverage and stock rules judge
each step on its own day. Nothing else changes: the services, their checks and the database
guards run exactly as in production.

Database-side times are not simulated: ``pghistory`` audit rows and
``StockBalance.updated_at`` use PostgreSQL ``now()`` and show when the seed ran.

Each reading advances the clock by one millisecond, so rows written in one step keep their
order, and a run with the same seed and start day writes the same times.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from django.utils import timezone

__all__ = ["DemoClock", "simulated_time"]

_TICK = timedelta(milliseconds=1)


class DemoClock:
    """A settable clock in the center's time zone."""

    def __init__(self, start: datetime) -> None:
        if timezone.is_naive(start):
            raise ValueError("DemoClock needs an aware datetime")
        self._now = start

    def now(self) -> datetime:
        current = self._now
        self._now = current + _TICK
        return current

    def peek(self) -> datetime:
        return self._now

    def today(self) -> date:
        return timezone.localtime(self._now).date()

    def set(self, when: datetime) -> None:
        """Move to ``when``; the clock never goes back (rows keep their order)."""
        if when > self._now:
            self._now = when

    def at(self, day: date, hour: int, minute: int = 0) -> None:
        """Move to ``hour:minute`` local time on ``day`` (never backwards)."""
        local = datetime.combine(day, time(hour, minute), tzinfo=timezone.get_current_timezone())
        self.set(local)

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


@contextmanager
def simulated_time(clock: DemoClock) -> Iterator[DemoClock]:
    """Make ``timezone.now()`` (and so ``localdate()`` and ``auto_now``) read ``clock``."""
    real = timezone.now
    timezone.now = clock.now
    try:
        yield clock
    finally:
        timezone.now = real
