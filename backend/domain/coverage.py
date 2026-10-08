"""Coverage split of one invoice line between payer and patient (ARCHITECTURE 4.5).

Each line has at most one payer (FEATURES 5.5, 5.6). The payer's share comes from its
coverage rule; the patient pays the rest minus any discount:

* ``percentage``: the payer pays ``payer_percent`` of the gross.
* ``fixed_patient_copay``: the patient pays a fixed ``copay`` per line (at most the gross);
  the payer pays the remainder.
* ``payer_ceiling``: the payer pays ``payer_percent`` of the gross, capped at ``ceiling``
  per line.
* An excluded service (FEATURES 5.7), or a line without a rule (cash), is all patient.

``patient_share = gross - discount - payer_share`` (derived by subtraction, so the three
parts always sum exactly to the gross). Discounts touch only the patient side and never
exceed the patient's pre-discount share (5.9). The per-role discount limit is a percentage
of that pre-discount share, compared exactly (no rounding).

A discount given as a percent is rounded down to the cent (:func:`percent_discount`), so it
never exceeds its percent. A payer's share is billed only inside the payer's contract
window (:func:`require_contract`).

Error codes: ``INVALID_COVERAGE_RULE``, ``DISCOUNT_EXCEEDS_PATIENT_SHARE``,
``DISCOUNT_LIMIT_EXCEEDED``, ``PREAPPROVAL_REQUIRED``, ``REASON_REQUIRED``,
``INVALID_AMOUNT``, ``INVALID_PERCENT``, ``PAYER_CONTRACT_EXPIRED``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from domain.audit import Approval
from domain.errors import DomainError
from domain.money import (
    CENT,
    HUNDRED,
    ZERO,
    allocate,
    is_money,
    percent_of,
    require_non_negative,
)

__all__ = [
    "CoverageKind",
    "CoverageRule",
    "LineSplit",
    "check_discount",
    "check_preapproval",
    "discount_allowed",
    "discount_within_limit",
    "distribute_discount",
    "max_discount_percent",
    "payer_share_for",
    "percent_discount",
    "require_contract",
    "split_line",
]


class CoverageKind(StrEnum):
    PERCENTAGE = "percentage"
    FIXED_PATIENT_COPAY = "fixed_patient_copay"
    PAYER_CEILING = "payer_ceiling"


def _bad_rule(message: str, **details: object) -> DomainError:
    return DomainError("INVALID_COVERAGE_RULE", message, **details)


@dataclass(frozen=True, slots=True)
class CoverageRule:
    """A payer's rule for a line. Use the class-method constructors for clarity."""

    kind: CoverageKind
    payer_percent: Decimal = HUNDRED
    copay: Decimal = ZERO
    ceiling: Decimal = ZERO
    requires_preapproval: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CoverageKind):
            raise _bad_rule("Unknown coverage kind", kind=str(self.kind))
        p = self.payer_percent
        if not isinstance(p, Decimal) or not p.is_finite() or not ZERO <= p <= HUNDRED:
            raise _bad_rule("payer_percent must be between 0 and 100", payer_percent=str(p))
        for name, value in (("copay", self.copay), ("ceiling", self.ceiling)):
            if not is_money(value) or value < 0:
                raise _bad_rule(f"{name} must be a non-negative amount", **{name: str(value)})

    @classmethod
    def percentage(
        cls, payer_percent: Decimal, *, requires_preapproval: bool = False
    ) -> CoverageRule:
        return cls(
            CoverageKind.PERCENTAGE,
            payer_percent=payer_percent,
            requires_preapproval=requires_preapproval,
        )

    @classmethod
    def fixed_copay(cls, copay: Decimal, *, requires_preapproval: bool = False) -> CoverageRule:
        return cls(
            CoverageKind.FIXED_PATIENT_COPAY, copay=copay, requires_preapproval=requires_preapproval
        )

    @classmethod
    def capped(
        cls,
        ceiling: Decimal,
        *,
        payer_percent: Decimal = HUNDRED,
        requires_preapproval: bool = False,
    ) -> CoverageRule:
        return cls(
            CoverageKind.PAYER_CEILING,
            payer_percent=payer_percent,
            ceiling=ceiling,
            requires_preapproval=requires_preapproval,
        )


@dataclass(frozen=True, slots=True)
class LineSplit:
    """Frozen amounts of one line. ``gross == discount + payer_share + patient_share``."""

    gross: Decimal
    discount: Decimal
    payer_share: Decimal
    patient_share: Decimal

    @property
    def patient_before_discount(self) -> Decimal:
        return self.gross - self.payer_share


def payer_share_for(
    gross: Decimal, rule: CoverageRule | None, *, excluded: bool = False
) -> Decimal:
    """The payer's share of ``gross`` under ``rule`` (zero for cash or excluded lines)."""
    amount = require_non_negative(gross, "gross")
    if rule is None or excluded:
        return ZERO
    if rule.kind is CoverageKind.PERCENTAGE:
        return percent_of(amount, rule.payer_percent)
    if rule.kind is CoverageKind.FIXED_PATIENT_COPAY:
        return amount - min(rule.copay, amount)
    return min(percent_of(amount, rule.payer_percent), rule.ceiling)


def split_line(
    gross: Decimal, discount: Decimal, rule: CoverageRule | None, *, excluded: bool = False
) -> LineSplit:
    """Split a line's gross into payer share, discount and patient share.

    Raises:
        DomainError: ``DISCOUNT_EXCEEDS_PATIENT_SHARE`` if the discount is larger than the
            patient's pre-discount share; ``INVALID_AMOUNT`` for negative inputs.
    """
    amount = require_non_negative(gross, "gross")
    disc = require_non_negative(discount, "discount")
    payer = payer_share_for(amount, rule, excluded=excluded)
    before = amount - payer
    if disc > before:
        raise DomainError(
            "DISCOUNT_EXCEEDS_PATIENT_SHARE",
            "A discount cannot exceed the patient's share",
            discount=str(disc),
            patient_share=str(before),
        )
    return LineSplit(gross=amount, discount=disc, payer_share=payer, patient_share=before - disc)


# --- discounts -----------------------------------------------------------------------------


def _percent(value: Decimal | int, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError(f"{name} must be Decimal or int")
    p = Decimal(value)
    if not p.is_finite() or not ZERO <= p <= HUNDRED:
        raise DomainError("INVALID_PERCENT", f"{name} must be between 0 and 100", percent=str(p))
    return p


def discount_within_limit(discount: Decimal, base: Decimal, limit_percent: Decimal | int) -> bool:
    """``discount <= limit_percent% of base``, compared exactly (``discount*100 <= limit*base``)."""
    d = require_non_negative(discount, "discount")
    b = require_non_negative(base, "base")
    return d * HUNDRED <= _percent(limit_percent, "limit_percent") * b


def percent_discount(base: Decimal, percent: Decimal | int) -> Decimal:
    """A discount of ``percent``% of ``base``, rounded down to the cent.

    Rounding down keeps a percent discount within the percent: a discount entered at the
    approver's exact limit always passes :func:`discount_within_limit` (half-up rounding of
    25% of 301.50 would give 75.38, above the limit).
    """
    b = require_non_negative(base, "base")
    p = _percent(percent, "percent")
    return (b * p / HUNDRED).quantize(CENT, rounding=ROUND_DOWN)


def max_discount_percent(roles: Iterable[str], role_limits: Mapping[str, Decimal | int]) -> Decimal:
    """Highest discount percent any of ``roles`` may give (0 when none is listed)."""
    limits = [_percent(role_limits[r], "limit") for r in set(roles) if r in role_limits]
    return max(limits, default=Decimal(0))


def discount_allowed(
    percent: Decimal | int, role_limits: Mapping[str, Decimal | int], roles: Iterable[str]
) -> bool:
    """Whether a discount of ``percent`` is within the best limit among ``roles``."""
    return _percent(percent, "percent") <= max_discount_percent(roles, role_limits)


def check_discount(
    discount: Decimal,
    patient_before_discount: Decimal,
    roles: Iterable[str],
    role_limits: Mapping[str, Decimal | int],
    approval: Approval | None,
) -> None:
    """Validate a discount on a patient share (FEATURES 5.9, invariant 4).

    A non-zero discount needs an :class:`Approval` (approver, time, reason) and must be
    within the approver's role limit, as a percentage of the patient's pre-discount share.
    """
    d = require_non_negative(discount, "discount")
    base = require_non_negative(patient_before_discount, "patient_before_discount")
    if d == 0:
        return
    if d > base:
        raise DomainError(
            "DISCOUNT_EXCEEDS_PATIENT_SHARE",
            "A discount cannot exceed the patient's share",
            discount=str(d),
            patient_share=str(base),
        )
    if approval is None:
        raise DomainError("REASON_REQUIRED", "A discount needs an approver and a reason")
    limit = max_discount_percent(roles, role_limits)
    if not discount_within_limit(d, base, limit):
        raise DomainError(
            "DISCOUNT_LIMIT_EXCEEDED",
            "The discount is above the approver's limit",
            discount=str(d),
            base=str(base),
            limit_percent=str(limit),
        )


def distribute_discount(total: Decimal, bases: Sequence[Decimal]) -> list[Decimal]:
    """Spread an invoice-level discount over lines in proportion to their patient shares.

    Parts sum exactly to ``total`` and none exceeds its base (largest-remainder cents).
    """
    t = require_non_negative(total, "total")
    clean = [require_non_negative(b, "base") for b in bases]
    available = sum(clean, ZERO)
    if t > available:
        raise DomainError(
            "DISCOUNT_EXCEEDS_PATIENT_SHARE",
            "A discount cannot exceed the patient's share",
            discount=str(t),
            patient_share=str(available),
        )
    return allocate(t, clean)


def check_preapproval(
    rule: CoverageRule | None, reference: str | None, *, excluded: bool = False
) -> str | None:
    """Return the stripped pre-approval reference (FEATURES 5.8).

    Raises ``PREAPPROVAL_REQUIRED`` when the payer's rule demands one and none is given.
    """
    ref = (reference or "").strip() or None
    if rule is not None and rule.requires_preapproval and not excluded and ref is None:
        raise DomainError("PREAPPROVAL_REQUIRED", "The payer requires a pre-approval reference")
    return ref


def require_contract(start: date | None, end: date | None, on: date) -> None:
    """A payer's share is billed only inside its contract window (FEATURES 11.1).

    Open ends (``None``) do not limit. Raises ``PAYER_CONTRACT_EXPIRED`` outside the window:
    a receivable booked on an ended contract is one the payer will reject.
    """
    if (start is not None and on < start) or (end is not None and on > end):
        raise DomainError(
            "PAYER_CONTRACT_EXPIRED",
            "The payer's contract does not cover this date",
            on=on.isoformat(),
            contract_start=start.isoformat() if start else None,
            contract_end=end.isoformat() if end else None,
        )
