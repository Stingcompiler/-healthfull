"""Laboratory rules: reference ranges, flags and result versions (FEATURES 9).

Reference ranges:

* A range may depend on sex and on an age band ``[age_min_days, age_max_days)``. The range
  used for a patient is the most specific applicable one: the narrowest age band first,
  then a sex-specific range over a sex-neutral one; ties go to the earlier range. With
  unknown sex or age only ranges that do not depend on it apply.
* Flags: ``critical_low`` when ``value <= critical_low``, ``critical_high`` when
  ``value >= critical_high``, ``low`` below ``low``, ``high`` above ``high``, else
  ``normal`` (the normal range is inclusive). Without a range the flag is ``none``.

Result versions:

* Version 1 is a draft entered by the technician. A lab supervisor approves it; an approved
  version never changes. Only approved versions are visible to doctors and patients.
* A correction after approval starts a new draft version that amends the previous one, with
  a reason; the original is retained. Only one draft exists at a time.
* The first approval performs the service line.

Bench (FEATURES 9.2, 9.8):

* A test's work-list stage: to collect (no usable sample), to receive (collected outside the
  lab), to enter (sample in the lab, values missing), to approve (a complete draft, first
  result or amendment), done (approved) or cancelled.
* Turnaround is summarised per test with nearest-rank percentiles; the mean rounds half up.

Error codes: ``INVALID_REFERENCE_RANGE``, ``INVALID_DATE_RANGE``, ``RESULT_NOT_DRAFT``,
``RESULT_APPROVED_IMMUTABLE``, ``RESULT_NOT_APPROVED``, ``AMENDMENT_IN_PROGRESS``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from domain.audit import Approval
from domain.errors import DomainError

__all__ = [
    "Flag",
    "ReferenceRange",
    "ResultStatus",
    "ResultVersion",
    "SampleState",
    "Sex",
    "Stage",
    "TurnaroundStats",
    "age_in_days",
    "approve_version",
    "first_version",
    "flag",
    "needs_critical_alert",
    "performs_line",
    "require_editable",
    "select_range",
    "stage",
    "start_amendment",
    "turnaround_stats",
    "visible_version",
]


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Flag(StrEnum):
    NONE = "none"
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"


def _bad_range(message: str) -> DomainError:
    return DomainError("INVALID_REFERENCE_RANGE", message)


def _lt(a: Decimal | None, b: Decimal | None) -> bool:
    return a is None or b is None or a < b


@dataclass(frozen=True, slots=True)
class ReferenceRange:
    low: Decimal | None = None
    high: Decimal | None = None
    critical_low: Decimal | None = None
    critical_high: Decimal | None = None
    sex: Sex | None = None
    age_min_days: int | None = None
    age_max_days: int | None = None

    def __post_init__(self) -> None:
        if not (self.low is None or self.high is None or self.low <= self.high):
            raise _bad_range("low must not exceed high")
        if not (_lt(self.critical_low, self.low) and _lt(self.high, self.critical_high)):
            raise _bad_range("critical limits must lie outside the normal range")
        if not _lt(self.critical_low, self.critical_high):
            raise _bad_range("critical_low must be below critical_high")
        if self.age_min_days is not None and self.age_min_days < 0:
            raise _bad_range("age_min_days must not be negative")
        lo = self.age_min_days or 0
        if self.age_max_days is not None and self.age_max_days <= lo:
            raise _bad_range("age_max_days must be greater than age_min_days")

    @property
    def has_age_band(self) -> bool:
        return self.age_min_days is not None or self.age_max_days is not None

    def applies_to(self, sex: Sex | None, age_days: int | None) -> bool:
        if self.sex is not None and self.sex is not sex:
            return False
        if not self.has_age_band:
            return True
        if age_days is None:
            return False
        if self.age_min_days is not None and age_days < self.age_min_days:
            return False
        return self.age_max_days is None or age_days < self.age_max_days

    def _specificity(self) -> tuple[float, bool]:
        """Smaller is more specific: (age band width, sex-neutral)."""
        width = (
            float("inf")
            if self.age_max_days is None
            else float(self.age_max_days - (self.age_min_days or 0))
        )
        return (width, self.sex is None)


def age_in_days(birth_date: date, on: date) -> int:
    if birth_date > on:
        raise DomainError("INVALID_DATE_RANGE", "Birth date is after the sample date")
    return (on - birth_date).days


def select_range(
    ranges: Iterable[ReferenceRange], sex: Sex | None, age_days: int | None
) -> ReferenceRange | None:
    best: ReferenceRange | None = None
    for r in ranges:
        if r.applies_to(sex, age_days) and (best is None or r._specificity() < best._specificity()):
            best = r
    return best


def flag(value: Decimal, rng: ReferenceRange | None) -> Flag:
    if rng is None:
        return Flag.NONE
    if rng.critical_low is not None and value <= rng.critical_low:
        return Flag.CRITICAL_LOW
    if rng.critical_high is not None and value >= rng.critical_high:
        return Flag.CRITICAL_HIGH
    if rng.low is not None and value < rng.low:
        return Flag.LOW
    if rng.high is not None and value > rng.high:
        return Flag.HIGH
    return Flag.NORMAL


def needs_critical_alert(flags: Iterable[Flag]) -> bool:
    return any(f in (Flag.CRITICAL_LOW, Flag.CRITICAL_HIGH) for f in flags)


# --- result versions -----------------------------------------------------------------------


class ResultStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


@dataclass(frozen=True, slots=True)
class ResultVersion:
    number: int
    status: ResultStatus = ResultStatus.DRAFT
    amends: int | None = None


def first_version() -> ResultVersion:
    return ResultVersion(1)


def require_editable(version: ResultVersion) -> None:
    """Values may be entered or changed only on a draft."""
    if version.status is ResultStatus.APPROVED:
        raise DomainError(
            "RESULT_APPROVED_IMMUTABLE",
            "An approved result cannot change; start an amendment",
            version=version.number,
        )


def approve_version(version: ResultVersion) -> ResultVersion:
    """Supervisor approval (permission checked by the service)."""
    if version.status is not ResultStatus.DRAFT:
        raise DomainError(
            "RESULT_NOT_DRAFT", "Only a draft can be approved", version=version.number
        )
    return replace(version, status=ResultStatus.APPROVED)


def start_amendment(versions: Sequence[ResultVersion], approval: Approval) -> ResultVersion:
    """New draft amending the latest approved version (FEATURES 9.5)."""
    if not isinstance(approval, Approval):
        raise TypeError("start_amendment() needs an Approval")
    approved = visible_version(versions)
    if approved is None:
        raise DomainError("RESULT_NOT_APPROVED", "Only an approved result can be amended")
    if any(v.status is ResultStatus.DRAFT for v in versions):
        raise DomainError("AMENDMENT_IN_PROGRESS", "Finish or approve the open draft first")
    number = max(v.number for v in versions) + 1
    return ResultVersion(number, ResultStatus.DRAFT, amends=approved.number)


def visible_version(versions: Iterable[ResultVersion]) -> ResultVersion | None:
    """The latest approved version (what doctor and patient see)."""
    approved = [v for v in versions if v.status is ResultStatus.APPROVED]
    return max(approved, key=lambda v: v.number) if approved else None


def performs_line(before: Iterable[ResultVersion], approved: ResultVersion) -> bool:
    """Whether approving ``approved`` is the first approval (the line becomes performed)."""
    return approved.status is ResultStatus.APPROVED and visible_version(before) is None


# --- bench ---------------------------------------------------------------------------------


class SampleState(StrEnum):
    COLLECTED = "collected"
    RECEIVED = "received"
    REJECTED = "rejected"


class Stage(StrEnum):
    TO_COLLECT = "to_collect"
    TO_RECEIVE = "to_receive"
    TO_ENTER = "to_enter"
    TO_APPROVE = "to_approve"
    DONE = "done"
    CANCELLED = "cancelled"


def stage(
    *,
    sample: SampleState | None,
    cancelled: bool = False,
    approved: bool = False,
    draft: bool = False,
    entered: int = 0,
    expected: int = 0,
) -> Stage:
    """Where a test stands on the bench.

    ``sample`` is the state of its current sample (None before one is collected); ``draft``
    says whether an open draft version exists, with ``entered`` of its ``expected`` values.
    """
    if entered < 0 or expected < 0:
        raise ValueError("entered and expected must not be negative")
    if entered and not draft:
        raise ValueError("values are entered only on a draft")
    if cancelled:
        return Stage.CANCELLED
    if draft:
        return Stage.TO_APPROVE if expected > 0 and entered >= expected else Stage.TO_ENTER
    if approved:
        return Stage.DONE
    if sample is None or sample is SampleState.REJECTED:
        return Stage.TO_COLLECT
    if sample is SampleState.COLLECTED:
        return Stage.TO_RECEIVE
    return Stage.TO_ENTER


@dataclass(frozen=True, slots=True)
class TurnaroundStats:
    """Minutes from sample receipt to first approval, over the completed tests of a period."""

    count: int
    mean: int | None
    median: int | None
    p90: int | None
    maximum: int | None
    within_target: int

    @property
    def within_target_percent(self) -> int | None:
        if self.count == 0:
            return None
        share = Decimal(self.within_target * 100) / Decimal(self.count)
        return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _nearest_rank(ordered: Sequence[int], percent: int) -> int:
    rank = max(1, math.ceil(percent * len(ordered) / 100))
    return ordered[rank - 1]


def turnaround_stats(minutes: Sequence[int], *, target: int) -> TurnaroundStats:
    """Count, mean, median, 90th percentile, maximum and how many met ``target`` minutes."""
    if target < 1:
        raise ValueError("target must be at least one minute")
    if any(m < 0 for m in minutes):
        raise ValueError("turnaround minutes must not be negative")
    if not minutes:
        return TurnaroundStats(0, None, None, None, None, 0)
    ordered = sorted(minutes)
    mean = (Decimal(sum(ordered)) / Decimal(len(ordered))).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return TurnaroundStats(
        count=len(ordered),
        mean=int(mean),
        median=_nearest_rank(ordered, 50),
        p90=_nearest_rank(ordered, 90),
        maximum=ordered[-1],
        within_target=sum(1 for m in ordered if m <= target),
    )
