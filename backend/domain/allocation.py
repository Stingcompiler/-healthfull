"""Allocation of patient payments to invoices (ARCHITECTURE 4.6, FEATURES 6.5, 6.6).

* A payment is allocated to invoices (the patient side). The allocations sum to at most the
  payment; the remainder is patient credit. Each allocation is at most the invoice's
  outstanding. Without ``Policy.allow_partial_payment`` an allocation must clear the invoice.
* Spending patient credit (method ``patient_credit``) must be allocated in full.
* Allocation rows are append-only: a reversal is a new negative row. A payment's net
  allocation per invoice never goes below zero.
* Rejecting a transfer reverses all of its net allocations. Its whole amount then leaves
  patient credit; if that credit was already spent (possible only after the transfer had
  been confirmed), credit-funded allocations are taken back newest first. Whatever cannot
  be recovered (it was refunded in cash) is reported as ``uncovered``: the patient owes it.
* When a credit note leaves an invoice over-allocated, the excess is de-allocated from
  pending payments first (so the credit created is not spendable until confirmed), then
  from the newest allocations.
* Spendable credit (for credit payments and refunds) excludes the unallocated part of
  pending payments. Allocating an earlier payment's remainder later is capped by the
  pooled credit balance (and, for confirmed money, by spendable credit).

Error codes: ``INVALID_AMOUNT``, ``INVOICE_NOT_OPEN``, ``DUPLICATE_ALLOCATION``,
``ALLOCATION_EXCEEDS_OUTSTANDING``, ``ALLOCATION_EXCEEDS_PAYMENT``,
``PARTIAL_PAYMENT_NOT_ALLOWED``, ``ALLOCATION_INCOMPLETE``,
``DEALLOCATION_EXCEEDS_ALLOCATED``, ``INSUFFICIENT_CREDIT``, ``REFUND_EXCEEDS_SOURCE``,
``REFUND_EXCEEDS_CREDIT``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from domain.audit import Approval
from domain.errors import DomainError
from domain.money import ZERO, require_money, require_non_negative, require_positive

__all__ = [
    "AllocationDraft",
    "AllocationPlan",
    "AllocationRecord",
    "AllocationRequest",
    "OpenInvoice",
    "RejectionPlan",
    "auto_allocate",
    "deallocate_excess",
    "later_allocation_limit",
    "net_by_invoice",
    "net_by_payment",
    "plan_rejection",
    "refund_source_available",
    "reverse_payment",
    "spendable_credit",
    "unallocated",
    "validate_allocations",
    "validate_credit_spend",
    "validate_refund",
]


@dataclass(frozen=True, slots=True)
class AllocationRequest:
    invoice_id: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    allocations: tuple[AllocationRequest, ...]
    unallocated: Decimal

    @property
    def allocated(self) -> Decimal:
        return sum((a.amount for a in self.allocations), ZERO)


@dataclass(frozen=True, slots=True)
class OpenInvoice:
    """An approved invoice of the patient with patient outstanding."""

    invoice_id: int
    approved_at: datetime
    outstanding: Decimal


@dataclass(frozen=True, slots=True)
class AllocationRecord:
    """A stored allocation row (signed). ``seq`` orders rows by creation.

    ``pending``: the payment is a transfer still awaiting verification.
    ``from_credit``: the payment spent patient credit (method ``patient_credit``).
    """

    payment_id: int
    invoice_id: int
    amount: Decimal
    seq: int
    pending: bool = False
    from_credit: bool = False


@dataclass(frozen=True, slots=True)
class AllocationDraft:
    """A new allocation row to store; negative amounts reverse or de-allocate."""

    payment_id: int
    invoice_id: int
    amount: Decimal


def validate_allocations(
    payment_amount: Decimal,
    requests: Sequence[AllocationRequest],
    outstanding: Mapping[int, Decimal],
    *,
    allow_partial: bool,
    require_full: bool = False,
) -> AllocationPlan:
    """Check explicit allocations of one payment against the invoices' outstanding.

    Args:
        payment_amount: The payment (positive).
        requests: One request per invoice, positive amounts.
        outstanding: Patient outstanding of each open invoice of the patient.
        allow_partial: ``Policy.allow_partial_payment``.
        require_full: The whole payment must be allocated (credit spending).
    """
    total = require_positive(payment_amount, "payment_amount")
    seen: set[int] = set()
    for r in requests:
        if r.invoice_id in seen:
            raise DomainError(
                "DUPLICATE_ALLOCATION", "One allocation per invoice", invoice_id=r.invoice_id
            )
        seen.add(r.invoice_id)
    allocated = ZERO
    for r in requests:
        amount = require_positive(r.amount, "allocation")
        if r.invoice_id not in outstanding:
            raise DomainError(
                "INVOICE_NOT_OPEN", "The invoice has nothing to pay", invoice_id=r.invoice_id
            )
        due = require_non_negative(outstanding[r.invoice_id], "outstanding")
        if amount > due:
            raise DomainError(
                "ALLOCATION_EXCEEDS_OUTSTANDING",
                "Allocation is larger than the invoice outstanding",
                invoice_id=r.invoice_id,
                amount=str(amount),
                outstanding=str(due),
            )
        if not allow_partial and amount != due:
            raise DomainError(
                "PARTIAL_PAYMENT_NOT_ALLOWED",
                "The center does not allow partial payment of an invoice",
                invoice_id=r.invoice_id,
                outstanding=str(due),
            )
        allocated += amount
    if allocated > total:
        raise DomainError(
            "ALLOCATION_EXCEEDS_PAYMENT",
            "Allocations are larger than the payment",
            allocated=str(allocated),
            payment=str(total),
        )
    if require_full and allocated != total:
        raise DomainError(
            "ALLOCATION_INCOMPLETE",
            "Spending patient credit must be allocated in full",
            allocated=str(allocated),
            payment=str(total),
        )
    return AllocationPlan(allocations=tuple(requests), unallocated=total - allocated)


def auto_allocate(
    payment_amount: Decimal, invoices: Iterable[OpenInvoice], *, allow_partial: bool
) -> AllocationPlan:
    """Allocate a payment oldest invoice first (approval time, then id).

    With partial payment allowed, money fills invoices strictly in order and the last one
    reached may be paid partly. Without it, each invoice is paid in full or skipped when it
    does not fit in what is left (a newer, smaller invoice may still be paid).
    """
    left = require_positive(payment_amount, "payment_amount")
    out: list[AllocationRequest] = []
    for inv in sorted(invoices, key=lambda i: (i.approved_at, i.invoice_id)):
        due = require_non_negative(inv.outstanding, "outstanding")
        if left == 0:
            break
        if due == 0:
            continue
        if due <= left:
            out.append(AllocationRequest(inv.invoice_id, due))
            left -= due
        elif allow_partial:
            out.append(AllocationRequest(inv.invoice_id, left))
            left = ZERO
    return AllocationPlan(allocations=tuple(out), unallocated=left)


def net_by_invoice(records: Iterable[AllocationRecord]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for r in records:
        out[r.invoice_id] += require_money(r.amount, "allocation")
    return dict(out)


def net_by_payment(records: Iterable[AllocationRecord]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for r in records:
        out[r.payment_id] += require_money(r.amount, "allocation")
    return dict(out)


def unallocated(payment_amount: Decimal, records: Iterable[AllocationRecord]) -> Decimal:
    """What is left of a payment after its (signed) allocation rows."""
    total = require_positive(payment_amount, "payment_amount")
    used = sum((require_money(r.amount, "allocation") for r in records), ZERO)
    if used > total:
        raise DomainError(
            "ALLOCATION_EXCEEDS_PAYMENT",
            "Allocations are larger than the payment",
            allocated=str(used),
        )
    return total - used


def _nets(
    records: Iterable[AllocationRecord],
) -> dict[tuple[int, int], tuple[Decimal, int, bool, bool]]:
    """Net per (payment, invoice) with the newest seq and the payment flags."""
    out: dict[tuple[int, int], tuple[Decimal, int, bool, bool]] = {}
    for r in records:
        key = (r.payment_id, r.invoice_id)
        net, seq, pending, credit = out.get(key, (ZERO, r.seq, r.pending, r.from_credit))
        out[key] = (net + require_money(r.amount, "allocation"), max(seq, r.seq), pending, credit)
    return out


def reverse_payment(
    payment_id: int, records: Iterable[AllocationRecord]
) -> tuple[AllocationDraft, ...]:
    """Negative rows that bring every net allocation of ``payment_id`` back to zero."""
    nets = _nets(r for r in records if r.payment_id == payment_id)
    return tuple(
        AllocationDraft(payment_id, invoice_id, -net)
        for (_, invoice_id), (net, _, _, _) in sorted(nets.items(), key=lambda kv: kv[1][1])
        if net > 0
    )


def _take(
    candidates: list[tuple[tuple[int, int], Decimal]], amount: Decimal
) -> tuple[list[AllocationDraft], Decimal]:
    drafts: list[AllocationDraft] = []
    left = amount
    for (payment_id, invoice_id), net in candidates:
        if left == 0:
            break
        take = min(net, left)
        if take > 0:
            drafts.append(AllocationDraft(payment_id, invoice_id, -take))
            left -= take
    return drafts, left


def deallocate_excess(
    invoice_id: int, records: Iterable[AllocationRecord], excess: Decimal
) -> tuple[AllocationDraft, ...]:
    """Negative rows on ``invoice_id`` totalling ``excess``.

    Pending payments are de-allocated first, then the newest allocations.
    """
    amount = require_non_negative(excess, "excess")
    nets = _nets(r for r in records if r.invoice_id == invoice_id)
    candidates = [
        (key, net)
        for key, (net, _, _, _) in sorted(nets.items(), key=lambda kv: (not kv[1][2], -kv[1][1]))
        if net > 0
    ]
    drafts, left = _take(candidates, amount)
    if left > 0:
        raise DomainError(
            "DEALLOCATION_EXCEEDS_ALLOCATED",
            "Cannot de-allocate more than is allocated to the invoice",
            invoice_id=invoice_id,
            excess=str(amount),
        )
    return tuple(drafts)


def later_allocation_limit(
    payment_unallocated: Decimal,
    *,
    pending: bool,
    credit_balance: Decimal,
    spendable: Decimal,
) -> Decimal:
    """How much of an earlier payment's unallocated remainder may still be allocated.

    Patient credit is one pooled balance: spending it (method ``patient_credit``) or a
    refund does not say which payment's remainder it used. So a later allocation is capped
    by the pool, and a confirmed payment's remainder also by spendable credit (it must not
    use pending money). A pending payment may allocate its own remainder, since pending
    money settles lines and rejecting it reverses that allocation.
    """
    remainder = require_non_negative(payment_unallocated, "payment_unallocated")
    pool = max(require_money(credit_balance, "credit_balance"), ZERO)
    cap = min(remainder, pool)
    if pending:
        return cap
    return min(cap, require_non_negative(spendable, "spendable"))


def spendable_credit(credit_balance: Decimal, pending_unallocated: Iterable[Decimal]) -> Decimal:
    """Patient credit that may be spent or refunded: the balance less pending money."""
    balance = require_money(credit_balance, "credit_balance")
    pending = sum((require_non_negative(p, "pending") for p in pending_unallocated), ZERO)
    return max(balance - pending, ZERO)


def validate_credit_spend(amount: Decimal, spendable: Decimal) -> None:
    """A ``patient_credit`` payment may not exceed spendable credit."""
    value = require_positive(amount, "amount")
    if value > require_non_negative(spendable, "spendable"):
        raise DomainError(
            "INSUFFICIENT_CREDIT",
            "The patient does not have enough confirmed credit",
            amount=str(value),
            spendable=str(spendable),
        )


def refund_source_available(deallocated: Iterable[Decimal], refunds: Iterable[Decimal]) -> Decimal:
    """Credit a credit note created (its de-allocation rows, negative) less live refunds of it.

    ``deallocated`` are the signed de-allocation amounts the note wrote; ``refunds`` the
    amounts of its refunds that are not rejected.
    """
    created = -sum((require_money(a, "deallocation") for a in deallocated), ZERO)
    used = sum((require_positive(r, "refund") for r in refunds), ZERO)
    return created - used


def validate_refund(
    amount: Decimal, *, source_available: Decimal, spendable: Decimal, approval: Approval
) -> None:
    """A refund is limited by the credit its credit note created and by spendable credit.

    It needs a supervisor's :class:`~domain.audit.Approval` (invariant 4); the service checks
    the permission and pays it in cash from the current shift.
    """
    if not isinstance(approval, Approval):
        raise TypeError("validate_refund() needs an Approval")
    value = require_positive(amount, "amount")
    if value > require_non_negative(source_available, "source_available"):
        raise DomainError(
            "REFUND_EXCEEDS_SOURCE",
            "A refund cannot exceed the credit created by its credit note",
            amount=str(value),
            available=str(source_available),
        )
    if value > require_non_negative(spendable, "spendable"):
        raise DomainError(
            "REFUND_EXCEEDS_CREDIT",
            "A refund cannot exceed the patient's confirmed credit",
            amount=str(value),
            spendable=str(spendable),
        )


@dataclass(frozen=True, slots=True)
class RejectionPlan:
    """What rejecting a transfer stores.

    ``reversals``: negative rows on the rejected payment's own allocations.
    ``recovery``: negative rows on credit-funded allocations taken back, newest first.
    ``uncovered``: credit that could not be recovered (left as a negative patient balance).
    """

    reversals: tuple[AllocationDraft, ...]
    recovery: tuple[AllocationDraft, ...]
    uncovered: Decimal


def plan_rejection(
    payment_id: int,
    payment_amount: Decimal,
    records: Sequence[AllocationRecord],
    *,
    credit_balance: Decimal,
) -> RejectionPlan:
    """Plan the allocation side of rejecting payment ``payment_id``.

    Args:
        payment_id: The transfer being rejected.
        payment_amount: Its amount.
        records: All allocation rows of the patient.
        credit_balance: Patient credit balance before the rejection.
    """
    amount = require_positive(payment_amount, "payment_amount")
    balance = require_money(credit_balance, "credit_balance")
    reversals = reverse_payment(payment_id, records)
    after = balance - sum((d.amount for d in reversals), ZERO) - amount
    if after >= 0:
        return RejectionPlan(reversals=reversals, recovery=(), uncovered=ZERO)
    nets = _nets(r for r in records if r.from_credit and r.payment_id != payment_id)
    candidates = [
        (key, net)
        for key, (net, _, _, _) in sorted(nets.items(), key=lambda kv: -kv[1][1])
        if net > 0
    ]
    recovery, left = _take(candidates, -after)
    return RejectionPlan(reversals=reversals, recovery=tuple(recovery), uncovered=left)
