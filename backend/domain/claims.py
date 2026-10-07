"""Payer claim lines (FEATURES 11; FLOW section 10; invariant 7).

One claim line follows the payer share of one invoice line:

``accrued -> claimed -> accepted | rejected | partially_accepted -> paid``;
``rejected -> rebilled | written_off``.

* ``amount`` is the payer share still owed by the payer (credits before claiming reduce it;
  a line credited to zero is ``voided``). Once claimed, the line is locked against credits.
* The payer's response accepts an amount in ``[0, amount]``; the rest is rejected and needs
  the payer's reason.
* Payer payments accumulate in ``paid`` up to ``accepted``; the line is ``paid`` when fully
  paid.
* A rejected part (whole or partial) is resolved once, by rebilling it to the patient or
  writing it off, with an :class:`~domain.audit.Approval`. A fully rejected line moves to
  ``rebilled``/``written_off``; a partly accepted line keeps its status and records the
  resolution.
* ``receivable`` (the AR_PAYER balance of the line) = ``amount - paid`` minus the rejected
  part once resolved. It is never cash until a payer payment is recorded.

Error codes: ``INVALID_AMOUNT``, ``CLAIM_AMOUNT_INVALID``, ``CLAIM_LINE_NOT_ACCRUED``,
``CLAIM_LINE_NOT_CLAIMED``, ``CLAIM_LINE_NOT_ACCEPTED``, ``CLAIM_PAYMENT_EXCEEDS_ACCEPTED``,
``CLAIM_NOTHING_REJECTED``, ``CLAIM_LINE_LOCKED``, ``CLAIM_LINE_UNKNOWN``,
``PAYER_PAYMENT_UNBALANCED``, ``REASON_REQUIRED``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from domain.audit import Approval, require_reason
from domain.errors import DomainError
from domain.money import ZERO, require_non_negative, require_positive

__all__ = [
    "ClaimLine",
    "ClaimLineStatus",
    "Resolution",
    "accrue",
    "is_settled",
    "record_payment",
    "reduce_for_credit",
    "require_creditable",
    "resolve_rejection",
    "respond",
    "submit",
    "validate_payer_payment",
]


class ClaimLineStatus(StrEnum):
    ACCRUED = "accrued"
    CLAIMED = "claimed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_ACCEPTED = "partially_accepted"
    PAID = "paid"
    REBILLED = "rebilled"
    WRITTEN_OFF = "written_off"
    VOIDED = "voided"


class Resolution(StrEnum):
    REBILLED = "rebilled"
    WRITTEN_OFF = "written_off"


S = ClaimLineStatus
_RESPONDED = frozenset(
    {S.ACCEPTED, S.REJECTED, S.PARTIALLY_ACCEPTED, S.PAID, S.REBILLED, S.WRITTEN_OFF}
)


def _bad(message: str, **details: object) -> DomainError:
    return DomainError("CLAIM_AMOUNT_INVALID", message, **details)


@dataclass(frozen=True, slots=True)
class ClaimLine:
    """Snapshot of a claim line; construction checks status/amount consistency."""

    status: ClaimLineStatus
    amount: Decimal
    accepted: Decimal = ZERO
    paid: Decimal = ZERO
    resolution: Resolution | None = None

    def __post_init__(self) -> None:
        amount = require_non_negative(self.amount, "amount")
        accepted = require_non_negative(self.accepted, "accepted")
        paid = require_non_negative(self.paid, "paid")
        st, res = self.status, self.resolution
        ok = {
            S.ACCRUED: amount > 0 and accepted == paid == 0 and res is None,
            S.CLAIMED: amount > 0 and accepted == paid == 0 and res is None,
            S.ACCEPTED: amount > 0 and accepted == amount and paid < accepted and res is None,
            S.PARTIALLY_ACCEPTED: 0 < accepted < amount and paid < accepted,
            S.REJECTED: amount > 0 and accepted == paid == 0 and res is None,
            S.PAID: 0 < accepted <= amount
            and paid == accepted
            and (res is None or accepted < amount),
            S.REBILLED: amount > 0 and accepted == paid == 0 and res is Resolution.REBILLED,
            S.WRITTEN_OFF: amount > 0 and accepted == paid == 0 and res is Resolution.WRITTEN_OFF,
            S.VOIDED: amount == accepted == paid == 0 and res is None,
        }[st]
        if not ok:
            raise _bad(
                "Claim line amounts do not match its status",
                status=str(st),
                amount=str(amount),
                accepted=str(accepted),
                paid=str(paid),
                resolution=str(res) if res else None,
            )

    @property
    def rejected(self) -> Decimal:
        """The part the payer refused (zero before the response)."""
        return self.amount - self.accepted if self.status in _RESPONDED else ZERO

    @property
    def unresolved_rejection(self) -> Decimal:
        return self.rejected if self.resolution is None else ZERO

    @property
    def receivable(self) -> Decimal:
        """What the payer still owes on this line (its AR_PAYER balance)."""
        resolved = self.rejected if self.resolution is not None else ZERO
        return self.amount - self.paid - resolved


def accrue(amount: Decimal) -> ClaimLine:
    """A payer share approved on an invoice line (it is a receivable, never cash)."""
    return ClaimLine(S.ACCRUED, require_positive(amount, "amount"))


def require_creditable(line: ClaimLine | None) -> None:
    """A credit note may touch an invoice line only while its payer share is unclaimed.

    ``None`` means the line has no payer share. Once claimed, corrections of the payer side
    go through the claim (rejection, rebill or write-off).
    """
    if line is not None and line.status is not S.ACCRUED:
        raise DomainError(
            "CLAIM_LINE_LOCKED",
            "The payer share is already claimed; resolve it through the claim",
            status=str(line.status),
        )


def reduce_for_credit(line: ClaimLine, credited: Decimal) -> ClaimLine:
    """A credit note reduced the payer share before it was claimed."""
    value = require_positive(credited, "credited")
    require_creditable(line)
    if value > line.amount:
        raise _bad("Credit exceeds the payer share", credited=str(value), amount=str(line.amount))
    left = line.amount - value
    return ClaimLine(S.ACCRUED, left) if left else ClaimLine(S.VOIDED, ZERO)


def submit(line: ClaimLine) -> ClaimLine:
    if line.status is not S.ACCRUED:
        raise DomainError("CLAIM_LINE_NOT_ACCRUED", "Only accrued lines can be claimed")
    return replace(line, status=S.CLAIMED)


def respond(line: ClaimLine, accepted: Decimal, *, reason: str | None = None) -> ClaimLine:
    """Record the payer's answer. A rejected part needs the payer's reason."""
    if line.status is not S.CLAIMED:
        raise DomainError("CLAIM_LINE_NOT_CLAIMED", "Only claimed lines get a response")
    value = require_non_negative(accepted, "accepted")
    if value > line.amount:
        raise _bad("Accepted is larger than the claimed amount", accepted=str(value))
    if value < line.amount:
        require_reason(reason)
    if value == line.amount:
        status = S.ACCEPTED
    elif value == 0:
        status = S.REJECTED
    else:
        status = S.PARTIALLY_ACCEPTED
    return replace(line, status=status, accepted=value)


def record_payment(line: ClaimLine, amount: Decimal) -> ClaimLine:
    """Apply part of a payer payment to this line."""
    value = require_positive(amount, "amount")
    if line.status not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED):
        raise DomainError("CLAIM_LINE_NOT_ACCEPTED", "Only accepted amounts can be paid")
    if line.paid + value > line.accepted:
        raise DomainError(
            "CLAIM_PAYMENT_EXCEEDS_ACCEPTED",
            "Payment is larger than the accepted amount left",
            left=str(line.accepted - line.paid),
        )
    paid = line.paid + value
    status = S.PAID if paid == line.accepted else line.status
    return replace(line, status=status, paid=paid)


def resolve_rejection(line: ClaimLine, resolution: Resolution, approval: Approval) -> ClaimLine:
    """Rebill the rejected part to the patient or write it off (FEATURES 11.5)."""
    if not isinstance(approval, Approval):
        raise TypeError("resolve_rejection() needs an Approval")
    if line.unresolved_rejection == 0:
        raise DomainError("CLAIM_NOTHING_REJECTED", "There is no unresolved rejected amount")
    if line.status is S.REJECTED:
        status = S.REBILLED if resolution is Resolution.REBILLED else S.WRITTEN_OFF
        return replace(line, status=status, resolution=resolution)
    return replace(line, resolution=resolution)


def is_settled(line: ClaimLine) -> bool:
    """Nothing left to collect or resolve."""
    return line.receivable == 0 and line.unresolved_rejection == 0


def validate_payer_payment(
    amount: Decimal, allocations: Mapping[int, Decimal], lines: Mapping[int, ClaimLine]
) -> None:
    """A payer payment is fully allocated to accepted, unpaid claim-line amounts.

    The chart has no payer advance account, so the allocations must equal the payment.
    """
    total = require_positive(amount, "amount")
    allocated = ZERO
    for line_id, value in allocations.items():
        v = require_positive(value, "allocation")
        line = lines.get(line_id)
        if line is None:
            raise DomainError("CLAIM_LINE_UNKNOWN", "Unknown claim line", claim_line_id=line_id)
        if line.status not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED):
            raise DomainError("CLAIM_LINE_NOT_ACCEPTED", "Only accepted amounts can be paid")
        if line.paid + v > line.accepted:
            raise DomainError(
                "CLAIM_PAYMENT_EXCEEDS_ACCEPTED",
                "Payment is larger than the accepted amount left",
                claim_line_id=line_id,
            )
        allocated += v
    if allocated != total:
        raise DomainError(
            "PAYER_PAYMENT_UNBALANCED",
            "A payer payment must be allocated exactly to claim lines",
            amount=str(total),
            allocated=str(allocated),
        )
