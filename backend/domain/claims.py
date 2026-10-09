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
* An accepted amount the payer will not pay in full (withholding, deductions) is written off
  with an approval: ``written_off`` grows and the line stops being receivable.
* A payer payment that bounced is reversed: ``paid`` goes back down.
* ``receivable`` (the AR_PAYER balance of the line) = ``amount - paid - written_off`` minus
  the rejected part once resolved. It is never cash until a payer payment is recorded.

Error codes: ``INVALID_AMOUNT``, ``CLAIM_AMOUNT_INVALID``, ``CLAIM_LINE_NOT_ACCRUED``,
``CLAIM_LINE_NOT_CLAIMED``, ``CLAIM_LINE_NOT_ACCEPTED``, ``CLAIM_PAYMENT_EXCEEDS_ACCEPTED``,
``CLAIM_NOTHING_REJECTED``, ``CLAIM_LINE_LOCKED``, ``CLAIM_LINE_UNKNOWN``,
``PAYER_PAYMENT_UNBALANCED``, ``REASON_REQUIRED``, ``CLAIM_NOTHING_UNPAID``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from domain.audit import Approval, require_reason
from domain.errors import DomainError
from domain.money import ZERO, require_non_negative, require_positive

__all__ = [
    "AGING_BUCKETS",
    "RESPONSE_OUTCOMES",
    "ClaimLine",
    "ClaimLineStatus",
    "Resolution",
    "accrue",
    "aging_bucket",
    "allocate_oldest_first",
    "allocate_to_claims",
    "is_settled",
    "record_payment",
    "reduce_for_credit",
    "require_creditable",
    "resolve_rejection",
    "respond",
    "response_amount",
    "reverse_payment",
    "submit",
    "validate_payer_payment",
    "withdraw_for_credit",
    "write_off_shortfall",
]

#: Aging buckets in days since invoice approval (upper bounds; the last is open-ended).
AGING_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("0_30", 30),
    ("31_60", 60),
    ("61_90", 90),
    ("over_90", None),
)


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
    """Snapshot of a claim line; construction checks status/amount consistency.

    ``written_off`` is the part of the accepted amount written off as short-paid.
    """

    status: ClaimLineStatus
    amount: Decimal
    accepted: Decimal = ZERO
    paid: Decimal = ZERO
    resolution: Resolution | None = None
    written_off: Decimal = ZERO

    def __post_init__(self) -> None:
        amount = require_non_negative(self.amount, "amount")
        accepted = require_non_negative(self.accepted, "accepted")
        paid = require_non_negative(self.paid, "paid")
        off = require_non_negative(self.written_off, "written_off")
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
        if off > 0 and (st not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED) or paid + off > accepted):
            ok = False
        if not ok:
            raise _bad(
                "Claim line amounts do not match its status",
                status=str(st),
                amount=str(amount),
                accepted=str(accepted),
                paid=str(paid),
                written_off=str(off),
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
    def unpaid(self) -> Decimal:
        """Accepted money the payer still owes (not paid, not written off)."""
        return max(self.accepted - self.paid - self.written_off, ZERO)

    @property
    def receivable(self) -> Decimal:
        """What the payer still owes on this line (its AR_PAYER balance)."""
        resolved = self.rejected if self.resolution is not None else ZERO
        return self.amount - self.paid - resolved - self.written_off


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


def withdraw_for_credit(line: ClaimLine, credit: Decimal) -> ClaimLine:
    """A credit note takes back ``credit`` of a claimed payer share by withdrawing its line.

    * An unanswered (claimed) line is withdrawn for any credit; what is left of the payer
      share becomes claimable again in a later batch.
    * An answered line is withdrawn only when nothing was paid, resolved or written off on
      it and the credit takes its whole claimed amount (a service that was not given).

    Anything else raises ``CLAIM_LINE_LOCKED``: the payer side is corrected through the
    claim (rejection, rebill, write-off).
    """
    value = require_positive(credit, "credit")
    if line.status is S.CLAIMED:
        return ClaimLine(S.VOIDED, ZERO)
    answered = line.status in (S.ACCEPTED, S.PARTIALLY_ACCEPTED, S.REJECTED)
    untouched = line.paid == 0 and line.resolution is None and line.written_off == 0
    if answered and untouched and value >= line.amount:
        return ClaimLine(S.VOIDED, ZERO)
    raise DomainError(
        "CLAIM_LINE_LOCKED",
        "The payer share is claimed and answered; correct it through the claim",
        status=str(line.status),
        credit=str(value),
        claimed=str(line.amount),
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


#: How the accountant enters a payer's answer for one line (FEATURES 11.4).
RESPONSE_OUTCOMES = ("accepted", "rejected", "partial")


def response_amount(outcome: str, claimed: Decimal, accepted: Decimal | None) -> Decimal:
    """The accepted amount of a line answered ``outcome``: all of it, nothing, or a part.

    A partial answer names the accepted part, strictly between nothing and the whole claimed
    amount; an amount given with a whole answer is ignored.

    Raises:
        DomainError: ``CLAIM_AMOUNT_INVALID`` (unknown outcome, partial without a part, or a
            part that is not strictly inside the claimed amount).
    """
    whole = require_positive(claimed, "claimed")
    if outcome == "accepted":
        return whole
    if outcome == "rejected":
        return ZERO
    if outcome != "partial":
        raise _bad("Unknown response outcome", outcome=outcome)
    if accepted is None or not ZERO < accepted < whole:
        raise _bad(
            "A partial answer accepts more than nothing and less than the claimed amount",
            claimed=str(whole),
            accepted=None if accepted is None else str(accepted),
        )
    return accepted


def record_payment(line: ClaimLine, amount: Decimal) -> ClaimLine:
    """Apply part of a payer payment to this line."""
    value = require_positive(amount, "amount")
    if line.status not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED):
        raise DomainError("CLAIM_LINE_NOT_ACCEPTED", "Only accepted amounts can be paid")
    if value > line.unpaid:
        raise DomainError(
            "CLAIM_PAYMENT_EXCEEDS_ACCEPTED",
            "Payment is larger than the accepted amount left",
            left=str(line.unpaid),
        )
    paid = line.paid + value
    status = S.PAID if paid == line.accepted else line.status
    return replace(line, status=status, paid=paid)


def reverse_payment(line: ClaimLine, amount: Decimal, status: ClaimLineStatus) -> ClaimLine:
    """Take back part of a payer payment from this line (the payment bounced).

    ``status`` is the line's answered status (accepted or partially accepted) it returns to.
    """
    value = require_positive(amount, "amount")
    if status not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED) or value > line.paid:
        raise _bad("Cannot reverse more than was paid", paid=str(line.paid), amount=str(value))
    return replace(line, status=status, paid=line.paid - value)


def write_off_shortfall(line: ClaimLine, amount: Decimal, approval: Approval) -> ClaimLine:
    """Write off accepted money the payer will not pay (FEATURES 11.5-11.7, invariant 4)."""
    if not isinstance(approval, Approval):
        raise TypeError("write_off_shortfall() needs an Approval")
    value = require_positive(amount, "amount")
    if line.status not in (S.ACCEPTED, S.PARTIALLY_ACCEPTED) or line.unpaid == 0:
        raise DomainError("CLAIM_NOTHING_UNPAID", "No accepted amount is left unpaid")
    if value > line.unpaid:
        raise _bad(
            "The write-off is larger than the unpaid accepted amount",
            unpaid=str(line.unpaid),
            amount=str(value),
        )
    return replace(line, written_off=line.written_off + value)


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
        if v > line.unpaid:
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


def allocate_oldest_first(
    amount: Decimal, dues: Iterable[tuple[int, Decimal]]
) -> dict[int, Decimal]:
    """Spread a payer payment over claim lines in the given order (oldest claims first).

    ``dues`` are ``(claim line id, unpaid accepted amount)``; lines owing nothing are
    skipped. The parts never exceed a line's due; what is left over stays unallocated (the
    caller's balance check then refuses the payment).
    """
    left = require_positive(amount, "amount")
    out: dict[int, Decimal] = {}
    for line_id, due in dues:
        if left == 0:
            break
        owed = require_non_negative(due, "due")
        if owed > 0:
            take = min(owed, left)
            out[line_id] = take
            left -= take
    return out


def allocate_to_claims(
    amounts: Mapping[int, Decimal], dues: Mapping[int, Sequence[tuple[int, Decimal]]]
) -> dict[int, Decimal]:
    """Spread the amount paid for each claim over that claim's own lines, oldest first.

    ``amounts`` maps a claim id to what the payer paid for it (a remittance advice lists
    payments per claim batch). ``dues`` maps a claim id to its ``(claim line id, unpaid
    accepted amount)`` rows in claim order. The result maps claim line ids to their part;
    each claim's parts add up exactly to its amount.

    Raises:
        DomainError: ``INVALID_AMOUNT`` (an amount not positive), ``CLAIM_NOTHING_UNPAID``
            (the claim has no accepted amount left unpaid), ``CLAIM_PAYMENT_EXCEEDS_ACCEPTED``
            (more than the claim still owes).
    """
    out: dict[int, Decimal] = {}
    for claim_id, amount in amounts.items():
        value = require_positive(amount, "amount")
        rows = list(dues.get(claim_id, ()))
        owed = sum((require_non_negative(due, "due") for _, due in rows), ZERO)
        if owed == 0:
            raise DomainError(
                "CLAIM_NOTHING_UNPAID", "No accepted amount is left unpaid", claim_id=claim_id
            )
        if value > owed:
            raise DomainError(
                "CLAIM_PAYMENT_EXCEEDS_ACCEPTED",
                "Payment is larger than the accepted amount left",
                claim_id=claim_id,
                left=str(owed),
            )
        out.update(allocate_oldest_first(value, rows))
    return out


def aging_bucket(age_days: int) -> str:
    """The aging bucket (FEATURES 11.7) of a receivable ``age_days`` old."""
    if age_days < 0:
        raise DomainError("INVALID_DATE_RANGE", "An age cannot be negative", age_days=age_days)
    for name, upper in AGING_BUCKETS:
        if upper is None or age_days <= upper:
            return name
    raise AssertionError("unreachable: the last bucket is open-ended")  # pragma: no cover
