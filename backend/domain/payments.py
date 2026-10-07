"""Payment methods, transfer verification and duplicate references (ARCHITECTURE 4.6).

* Methods: ``cash``, ``bank_transfer``, ``qr``, ``card``, ``patient_credit``. Transfers, QR
  and card payments carry a bank and a reference.
* Verification: cash (and spending patient credit, which moves no outside money) is always
  ``confirmed``. Other methods start ``pending``; a user with
  ``payments.confirm_transfer`` moves them to ``confirmed`` or ``rejected`` with an
  :class:`~domain.audit.Approval`. A confirmed transfer can still be rejected later (the
  bank reversed it); ``rejected`` is terminal.
* Pending money settles service lines (the service proceeds) but is never reported as
  confirmed collection (FEATURES 6.4).
* A reference is unique per bank. A duplicate is refused unless a user with the
  ``cashier_supervisor`` override permission approves it with a reason; the payment is
  then stored flagged as a duplicate.

Error codes: ``INVALID_AMOUNT``, ``BANK_REQUIRED``, ``REFERENCE_REQUIRED``,
``PAYMENT_NOT_PENDING``, ``PAYMENT_NOT_REJECTABLE``, ``DUPLICATE_REFERENCE``,
``OVERRIDE_NOT_PERMITTED``, ``REASON_REQUIRED``, ``INVALID_DATE_RANGE``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from domain.audit import Approval
from domain.errors import DomainError
from domain.money import require_positive

__all__ = [
    "REFERENCE_METHODS",
    "PaymentDetails",
    "PaymentMethod",
    "ReferenceCheck",
    "Verification",
    "check_reference",
    "confirm",
    "counts_as_collected",
    "covers_lines",
    "initial_verification",
    "normalize_bank",
    "normalize_reference",
    "pending_age_days",
    "reject",
    "validate_payment",
]


class PaymentMethod(StrEnum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    QR = "qr"
    CARD = "card"
    PATIENT_CREDIT = "patient_credit"


class Verification(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


#: Methods that move outside money through a bank and need ``bank`` + ``reference``.
REFERENCE_METHODS = frozenset({PaymentMethod.BANK_TRANSFER, PaymentMethod.QR, PaymentMethod.CARD})


def initial_verification(method: PaymentMethod) -> Verification:
    return Verification.PENDING if method in REFERENCE_METHODS else Verification.CONFIRMED


def confirm(method: PaymentMethod, verification: Verification, approval: Approval) -> Verification:
    """``pending`` -> ``confirmed`` after checking the bank statement or app."""
    if not isinstance(approval, Approval):
        raise TypeError("confirm() needs an Approval")
    if method not in REFERENCE_METHODS or verification is not Verification.PENDING:
        raise DomainError(
            "PAYMENT_NOT_PENDING",
            "Only a pending transfer can be confirmed",
            method=str(method),
            verification=str(verification),
        )
    return Verification.CONFIRMED


def reject(method: PaymentMethod, verification: Verification, approval: Approval) -> Verification:
    """``pending`` or ``confirmed`` -> ``rejected``. Allocations must then be reversed."""
    if not isinstance(approval, Approval):
        raise TypeError("reject() needs an Approval")
    if method not in REFERENCE_METHODS or verification is Verification.REJECTED:
        raise DomainError(
            "PAYMENT_NOT_REJECTABLE",
            "Only a pending or confirmed transfer can be rejected",
            method=str(method),
            verification=str(verification),
        )
    return Verification.REJECTED


def covers_lines(verification: Verification) -> bool:
    """Money that settles service lines: pending or confirmed."""
    return verification is not Verification.REJECTED


def counts_as_collected(verification: Verification) -> bool:
    """Money reported as confirmed collection: confirmed only."""
    return verification is Verification.CONFIRMED


_ARABIC_DIGITS = str.maketrans(
    {
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)
_SEPARATORS = re.compile(r"[\s\-_/.‐-―]+")


def normalize_reference(reference: str) -> str:
    """Canonical form for uniqueness: NFKC, ASCII digits, no spaces/dashes, upper case."""
    text = unicodedata.normalize("NFKC", reference).translate(_ARABIC_DIGITS)
    return _SEPARATORS.sub("", text).upper()


def normalize_bank(bank: str) -> str:
    """Bank codes compare stripped and upper-case."""
    return bank.strip().upper()


@dataclass(frozen=True, slots=True)
class PaymentDetails:
    method: PaymentMethod
    amount: Decimal
    bank: str | None
    reference: str | None


def validate_payment(
    method: PaymentMethod,
    amount: Decimal,
    *,
    bank: str | None = None,
    reference: str | None = None,
) -> PaymentDetails:
    """Check amount and bank details; return them normalized."""
    value = require_positive(amount, "amount")
    if method not in REFERENCE_METHODS:
        return PaymentDetails(method=method, amount=value, bank=None, reference=None)
    clean_bank = normalize_bank(bank or "")
    if not clean_bank:
        raise DomainError("BANK_REQUIRED", "A bank is required for this payment method")
    clean_ref = normalize_reference(reference or "")
    if not clean_ref:
        raise DomainError("REFERENCE_REQUIRED", "A reference is required for this payment method")
    return PaymentDetails(method=method, amount=value, bank=clean_bank, reference=clean_ref)


@dataclass(frozen=True, slots=True)
class ReferenceCheck:
    """Outcome of the uniqueness rule. ``duplicate`` payments are stored flagged."""

    duplicate: bool
    override: Approval | None = None


def check_reference(
    bank: str,
    reference: str,
    existing: Collection[tuple[str, str]],
    *,
    override: Approval | None = None,
    can_override: bool = False,
) -> ReferenceCheck:
    """Apply "reference unique per bank" against ``existing`` normalized ``(bank, ref)`` pairs.

    Raises:
        DomainError: ``DUPLICATE_REFERENCE`` without an override; ``OVERRIDE_NOT_PERMITTED``
            when the overriding user lacks the permission.
    """
    key = (normalize_bank(bank), normalize_reference(reference))
    if key not in existing:
        return ReferenceCheck(duplicate=False)
    if override is None:
        raise DomainError(
            "DUPLICATE_REFERENCE",
            "This reference was already used for this bank",
            bank=key[0],
            reference=key[1],
        )
    if not can_override:
        raise DomainError(
            "OVERRIDE_NOT_PERMITTED", "Only a cashier supervisor can accept a duplicate reference"
        )
    return ReferenceCheck(duplicate=True, override=override)


def pending_age_days(received_on: date, today: date) -> int:
    """Age in whole days of a pending transfer (FEATURES 6.4 report)."""
    if received_on > today:
        raise DomainError("INVALID_DATE_RANGE", "A payment cannot be received in the future")
    return (today - received_on).days
