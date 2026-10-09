"""Prescription rules: frequency codes and the quantity to dispense (FEATURES 3.5).

* A frequency code gives the doses per day (``OD`` 1, ``BID`` 2, ``TID`` 3, ``QID`` 4,
  ``Q4H`` 6, ``Q6H`` 4, ``Q8H`` 3, ``Q12H`` 2, ``HS`` 1, ``QOD`` 0.5). ``STAT`` is a single
  dose; ``PRN`` (as needed) has no daily count. A free frequency (no code) gives the doses
  per day directly.
* The quantity to dispense, in base units (tablets, capsules, vials...), is
  ``ceil(dose_quantity x doses per day x days)``: the smallest whole number of units that
  covers the course, never short of it. ``STAT`` gives ``ceil(dose_quantity)``. An
  as-needed prescription has no computed quantity; the prescriber states it.
* A course is at most :data:`MAX_DURATION_DAYS` days and :data:`MAX_DOSES_PER_DAY` doses a
  day; doses and frequencies are positive and finite.
* A quantity the prescriber states may round the course up (a whole pack) but never below
  the computed quantity: the prescription and what is invoiced and dispensed agree.

Error codes: ``UNKNOWN_FREQUENCY``, ``FREQUENCY_MISMATCH``, ``INVALID_PRESCRIPTION``,
``QUANTITY_BELOW_PRESCRIPTION``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from domain.errors import DomainError

__all__ = [
    "AS_NEEDED",
    "FREQUENCIES",
    "MAX_DOSES_PER_DAY",
    "MAX_DURATION_DAYS",
    "ONCE",
    "Prescription",
    "dispense_quantity",
    "frequency_per_day",
    "order_quantity",
    "resolve",
]

ONCE = "STAT"
AS_NEEDED = "PRN"
MAX_DURATION_DAYS = 365
MAX_DOSES_PER_DAY = Decimal(24)

#: Doses per day of each frequency code; ``None`` = no daily count (single dose, as needed).
FREQUENCIES: Mapping[str, Decimal | None] = {
    "OD": Decimal(1),
    "BID": Decimal(2),
    "TID": Decimal(3),
    "QID": Decimal(4),
    "Q4H": Decimal(6),
    "Q6H": Decimal(4),
    "Q8H": Decimal(3),
    "Q12H": Decimal(2),
    "HS": Decimal(1),
    "QOD": Decimal("0.5"),
    ONCE: None,
    AS_NEEDED: None,
}


@dataclass(frozen=True, slots=True)
class Prescription:
    """A prescription's frequency as stored, and the quantity to dispense when computable."""

    frequency_code: str
    frequency_per_day: Decimal | None
    quantity: int | None


def _normalize(code: str) -> str:
    return code.strip().upper()


def _lookup(code: str) -> Decimal | None:
    key = _normalize(code)
    if key not in FREQUENCIES:
        raise DomainError(
            "UNKNOWN_FREQUENCY",
            "Unknown frequency code",
            frequency_code=code,
            known=list(FREQUENCIES),
        )
    return FREQUENCIES[key]


def frequency_per_day(code: str) -> Decimal | None:
    """Doses per day of a frequency code (``None`` for ``STAT`` and ``PRN``).

    Raises:
        DomainError: ``UNKNOWN_FREQUENCY``.
    """
    return _lookup(code)


def _positive(value: Decimal) -> bool:
    return value.is_finite() and value > 0


def dispense_quantity(dose_quantity: Decimal, per_day: Decimal, duration_days: int) -> int:
    """Base units covering ``dose_quantity`` x ``per_day`` x ``duration_days``, rounded up.

    Raises:
        DomainError: ``INVALID_PRESCRIPTION`` for a non-positive or non-finite dose or
            frequency, more than :data:`MAX_DOSES_PER_DAY` doses a day, or a duration outside
            1..:data:`MAX_DURATION_DAYS` days.
    """
    if (
        not _positive(dose_quantity)
        or not _positive(per_day)
        or per_day > MAX_DOSES_PER_DAY
        or isinstance(duration_days, bool)
        or not 1 <= duration_days <= MAX_DURATION_DAYS
    ):
        raise DomainError(
            "INVALID_PRESCRIPTION",
            "Dose, frequency and duration must be positive and plausible",
            max_duration_days=MAX_DURATION_DAYS,
        )
    return max(1, math.ceil(dose_quantity * per_day * duration_days))


def resolve(
    *,
    dose_quantity: Decimal | None,
    frequency_code: str,
    frequency_per_day: Decimal | None,
    duration_days: int | None,
    as_needed: bool = False,
) -> Prescription:
    """The stored frequency and, when it can be counted, the quantity to dispense.

    A known code fills the doses per day; a given ``frequency_per_day`` must then agree with
    it (``FREQUENCY_MISMATCH``). Without a code the given doses per day are used as they are.

    Raises:
        DomainError: ``UNKNOWN_FREQUENCY``, ``FREQUENCY_MISMATCH``, ``INVALID_PRESCRIPTION``.
    """
    code = _normalize(frequency_code)
    per_day = frequency_per_day
    if code:
        known = _lookup(code)
        if per_day is not None and known is not None and per_day != known:
            raise DomainError(
                "FREQUENCY_MISMATCH",
                "The doses per day contradict the frequency code",
                frequency_code=code,
                frequency_per_day=str(per_day),
            )
        if known is not None:
            per_day = known
        elif per_day is not None:
            raise DomainError(
                "FREQUENCY_MISMATCH",
                "A single or as-needed dose has no daily count",
                frequency_code=code,
                frequency_per_day=str(per_day),
            )
    if dose_quantity is not None and not _positive(dose_quantity):
        raise DomainError("INVALID_PRESCRIPTION", "The dose must be positive")
    quantity: int | None = None
    if code == AS_NEEDED or as_needed or dose_quantity is None:
        quantity = None
    elif code == ONCE:
        quantity = max(1, math.ceil(dose_quantity))
    elif per_day is not None and duration_days is not None:
        quantity = dispense_quantity(dose_quantity, per_day, duration_days)
    return Prescription(frequency_code=code, frequency_per_day=per_day, quantity=quantity)


def order_quantity(computed: int | None, stated: int | None) -> int | None:
    """The quantity to order: the stated one, else the computed one.

    A stated quantity may exceed the computed course (rounding up to a pack) but never fall
    short of it, or the prescription would contradict what is dispensed (FEATURES 3.5).

    Raises:
        DomainError: ``QUANTITY_BELOW_PRESCRIPTION`` (details ``quantity``, ``computed``).
    """
    if stated is None:
        return computed
    if computed is not None and stated < computed:
        raise DomainError(
            "QUANTITY_BELOW_PRESCRIPTION",
            "The quantity is less than the prescription needs",
            quantity=stated,
            computed=computed,
        )
    return stated
