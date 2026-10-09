"""Report arithmetic (FEATURES 12.x, FLOW "reports"): pure rules over aggregates.

* Net revenue is gross less discounts less what approved credit notes took back (their gross
  less their discount), the same split the ledger books as REVENUE less DISCOUNT.
* Collections: cash and confirmed transfers are collected; pending transfers are kept apart
  and never counted as collected (FEATURES 6.4, 12.1); rejected transfers and spent patient
  credit (no new money) are neither.
* Shift variances split into shortages (negative) and overages (positive).
* Ages fall into fixed buckets for the aging sections.

Error codes: ``INVALID_DATE_RANGE``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from domain.errors import DomainError
from domain.money import ZERO
from domain.payments import REFERENCE_METHODS, PaymentMethod, Verification

__all__ = [
    "AGE_BUCKET_KEYS",
    "Collections",
    "RevenueTotals",
    "Variances",
    "add_revenue",
    "age_bucket",
    "bucket_bounds",
    "collections",
    "share_percent",
    "variances",
]

#: Aging buckets with inclusive upper bounds in days; the last is open-ended.
_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("age_0_1", 1),
    ("age_2_3", 3),
    ("age_4_7", 7),
    ("age_8_30", 30),
    ("age_over_30", None),
)
AGE_BUCKET_KEYS: tuple[str, ...] = tuple(key for key, _ in _BUCKETS)


def age_bucket(days: int) -> str:
    """The bucket of an age in whole days."""
    if days < 0:
        raise DomainError("INVALID_DATE_RANGE", "An age cannot be negative", days=days)
    for key, upper in _BUCKETS:
        if upper is None or days <= upper:
            return key
    raise AssertionError("the last bucket is open-ended")  # pragma: no cover


def bucket_bounds(key: str) -> tuple[int, int | None]:
    """Inclusive ``(lower, upper)`` days of a bucket (``upper`` ``None`` = no limit)."""
    lower = 0
    for name, upper in _BUCKETS:
        if name == key:
            return lower, upper
        lower = (upper or 0) + 1
    raise KeyError(key)


@dataclass(frozen=True, slots=True)
class RevenueTotals:
    """Billed revenue of a group: invoice lines approved and credit-note lines approved."""

    gross: Decimal = ZERO
    discount: Decimal = ZERO
    credited: Decimal = ZERO
    credited_discount: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.gross - self.discount - (self.credited - self.credited_discount)


def add_revenue(rows: Iterable[RevenueTotals]) -> RevenueTotals:
    gross = discount = credited = credited_discount = ZERO
    for r in rows:
        gross += r.gross
        discount += r.discount
        credited += r.credited
        credited_discount += r.credited_discount
    return RevenueTotals(gross, discount, credited, credited_discount)


@dataclass(frozen=True, slots=True)
class Collections:
    cash: Decimal = ZERO
    bank_confirmed: Decimal = ZERO
    pending: Decimal = ZERO
    rejected: Decimal = ZERO
    credit_used: Decimal = ZERO

    @property
    def confirmed(self) -> Decimal:
        """Money reported as collected: cash and confirmed transfers, never pending."""
        return self.cash + self.bank_confirmed


def collections(rows: Iterable[tuple[str, str, Decimal]]) -> Collections:
    """Totals of ``(method, verification, amount)`` patient payments."""
    cash = bank = pending = rejected = credit = ZERO
    for method_code, verification_code, amount in rows:
        method = PaymentMethod(method_code)
        verification = Verification(verification_code)
        if method is PaymentMethod.CASH:
            cash += amount
        elif method is PaymentMethod.PATIENT_CREDIT:
            credit += amount
        elif method in REFERENCE_METHODS:
            if verification is Verification.CONFIRMED:
                bank += amount
            elif verification is Verification.PENDING:
                pending += amount
            else:
                rejected += amount
    return Collections(cash, bank, pending, rejected, credit)


@dataclass(frozen=True, slots=True)
class Variances:
    short: Decimal
    over: Decimal
    count_short: int
    count_over: int

    @property
    def net(self) -> Decimal:
        return self.short + self.over


def variances(values: Iterable[Decimal]) -> Variances:
    """Shift variances (counted − expected) split into shortages and overages."""
    short = over = ZERO
    n_short = n_over = 0
    for v in values:
        if v < 0:
            short += v
            n_short += 1
        elif v > 0:
            over += v
            n_over += 1
    return Variances(short, over, n_short, n_over)


def share_percent(part: int | Decimal, whole: int | Decimal) -> Decimal | None:
    """``part`` as a percentage of ``whole``, one decimal, half up; ``None`` when empty."""
    if not whole:
        return None
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
