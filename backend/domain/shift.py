"""Cashier shifts and cash control (ARCHITECTURE 4.6, FEATURES 7; invariant 3).

* A cashier has at most one open shift; money is taken and refunded only in an open shift.
* Expected cash = opening float + confirmed cash in - cash refunds - cash handovers out
  (+ handovers in, when a drawer receives cash from another shift).
* The cashier enters counted cash; variance = counted - expected (positive = over). A
  non-zero variance needs an explanation. A closed shift never changes.
* A later effect of a closed shift's money (a transfer rejected after close) posts to the
  acting user's current open shift, linked to the original.
* The shift report keeps confirmed collection apart from pending transfers.

Error codes: ``SHIFT_NOT_OPEN``, ``SHIFT_CLOSED``, ``SHIFT_ALREADY_OPEN``,
``VARIANCE_EXPLANATION_REQUIRED``, ``CASH_INSUFFICIENT``, ``INVALID_AMOUNT``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from domain.errors import DomainError
from domain.money import ZERO, require_non_negative
from domain.payments import REFERENCE_METHODS, PaymentMethod, Verification

__all__ = [
    "CashMovements",
    "CloseResult",
    "CollectionSummary",
    "ShiftPayment",
    "ShiftRef",
    "ShiftStatus",
    "collection_summary",
    "ensure_cash_available",
    "expected_cash",
    "late_effect_shift",
    "require_open",
    "validate_close",
    "validate_open",
    "variance",
]


class ShiftStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class CashMovements:
    """Cash that moved through one drawer during a shift (all non-negative)."""

    opening_float: Decimal
    cash_in: Decimal
    cash_refunds: Decimal
    handovers_out: Decimal = ZERO
    handovers_in: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("opening_float", "cash_in", "cash_refunds", "handovers_out", "handovers_in"):
            require_non_negative(getattr(self, name), name)


def expected_cash(m: CashMovements) -> Decimal:
    return m.opening_float + m.cash_in - m.cash_refunds - m.handovers_out + m.handovers_in


def variance(counted: Decimal, expected: Decimal) -> Decimal:
    """``counted - expected``: positive is cash over, negative is cash short."""
    return require_non_negative(counted, "counted") - expected


def require_open(status: ShiftStatus | None) -> None:
    """Money moves only in an open shift (``None`` = the user has no shift)."""
    if status is None:
        raise DomainError("SHIFT_NOT_OPEN", "Open a shift first")
    if status is ShiftStatus.CLOSED:
        raise DomainError("SHIFT_CLOSED", "A closed shift cannot change")


def validate_open(open_shifts: int, opening_float: Decimal) -> Decimal:
    """One open shift per cashier; returns the validated opening float."""
    if open_shifts > 0:
        raise DomainError("SHIFT_ALREADY_OPEN", "The cashier already has an open shift")
    return require_non_negative(opening_float, "opening_float")


@dataclass(frozen=True, slots=True)
class CloseResult:
    expected: Decimal
    counted: Decimal
    variance: Decimal
    explanation: str


def validate_close(
    status: ShiftStatus, *, expected: Decimal, counted: Decimal, explanation: str | None
) -> CloseResult:
    """Validate closing an open shift with the counted cash."""
    require_open(status)
    v = variance(counted, expected)
    text = (explanation or "").strip()
    if v != 0 and not text:
        raise DomainError(
            "VARIANCE_EXPLANATION_REQUIRED",
            "Explain the difference between counted and expected cash",
            variance=str(v),
        )
    return CloseResult(expected=expected, counted=counted, variance=v, explanation=text)


def ensure_cash_available(amount: Decimal, cash_on_hand: Decimal) -> None:
    """Cash paid out (refund, handover) cannot exceed the drawer's expected cash."""
    if require_non_negative(amount, "amount") > cash_on_hand:
        raise DomainError(
            "CASH_INSUFFICIENT",
            "Not enough cash in the drawer",
            amount=str(amount),
            available=str(cash_on_hand),
        )


@dataclass(frozen=True, slots=True)
class ShiftRef:
    shift_id: int
    status: ShiftStatus


def late_effect_shift(original: ShiftRef, current: ShiftRef | None) -> int:
    """The shift that receives a later effect of money first taken in ``original``.

    The original shift while it is open; otherwise the acting user's current open shift.
    """
    if original.status is ShiftStatus.OPEN:
        return original.shift_id
    if current is None or current.status is not ShiftStatus.OPEN:
        raise DomainError(
            "SHIFT_NOT_OPEN",
            "The original shift is closed; open a shift to record this",
            original_shift_id=original.shift_id,
        )
    return current.shift_id


@dataclass(frozen=True, slots=True)
class ShiftPayment:
    method: PaymentMethod
    verification: Verification
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    cash_confirmed: Decimal
    bank_confirmed: Decimal
    bank_pending: Decimal
    bank_rejected: Decimal
    credit_used: Decimal

    @property
    def confirmed_collection(self) -> Decimal:
        """Money reported as collected: confirmed only, never pending (FEATURES 6.4)."""
        return self.cash_confirmed + self.bank_confirmed


def collection_summary(payments: Iterable[ShiftPayment]) -> CollectionSummary:
    cash = bank = pending = rejected = credit = ZERO
    for p in payments:
        amount = require_non_negative(p.amount, "amount")
        if p.method is PaymentMethod.CASH:
            cash += amount
        elif p.method is PaymentMethod.PATIENT_CREDIT:
            credit += amount
        elif p.method in REFERENCE_METHODS:
            if p.verification is Verification.CONFIRMED:
                bank += amount
            elif p.verification is Verification.PENDING:
                pending += amount
            else:
                rejected += amount
    return CollectionSummary(
        cash_confirmed=cash,
        bank_confirmed=bank,
        bank_pending=pending,
        bank_rejected=rejected,
        credit_used=credit,
    )
