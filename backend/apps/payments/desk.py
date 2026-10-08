"""The cashier desk's money commands (FEATURES 6.x, 7.x).

Each command runs one ``apps.payments.services`` operation and returns what the screen shows
next (``apps.payments.queries``), so a router makes one call. Rules, locks, ledger postings and
audit context stay in the engine; this module resolves references (bank and till codes, the
actor's open shift) and the supervisor who approves at the desk (ADR 0007).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from apps.billing.models import CreditNote
from apps.core.models import User
from apps.patients.models import Patient
from apps.payments import queries
from apps.payments import services as pay
from apps.payments.approvals import ApproverLogin, resolve_approver
from apps.payments.models import Bank, CashHandover, Payment, Refund, Shift, Till
from domain.errors import DomainError

__all__ = [
    "allocate",
    "approve_refund",
    "cancel_handover",
    "close_shift",
    "confirm_transfer",
    "hand_over",
    "open_shift",
    "pay_refund",
    "receive_handover",
    "reject_refund",
    "reject_transfer",
    "request_refund",
    "review_shift",
    "take_payment",
]


def _bank(code: str | None) -> Bank | None:
    if not code:
        return None
    found = Bank.objects.filter(code__iexact=code.strip()).first()
    if found is None:
        raise DomainError("BANK_REQUIRED", "Choose a bank from the list", bank=code)
    return found


def _own_open_shift(actor: User) -> Shift:
    shift = pay.current_shift(actor)
    if shift is None:
        raise DomainError("SHIFT_NOT_OPEN", "Open a shift first")
    return shift


# --- shifts ----------------------------------------------------------------------------------


def open_shift(
    actor: User, *, opening_float: Decimal, till: str | None, note: str
) -> dict[str, Any]:
    """Open the actor's shift with an opening float (FEATURES 7.1)."""
    till_row = Till.objects.get(code__iexact=till.strip(), active=True) if till else None
    shift = pay.open_shift(actor, opening_float, till=till_row, note=note)
    return queries.shift_report(shift.pk, viewer=actor)


def close_shift(
    shift_id: int, *, actor: User, counted: Decimal, reason: str | None, note: str
) -> dict[str, Any]:
    """Close a shift with the counted cash; a variance needs an explanation (FEATURES 7.2)."""
    pay.close_shift(Shift.objects.get(pk=shift_id), counted, actor=actor, reason=reason, note=note)
    return queries.shift_report(shift_id, viewer=actor)


def review_shift(shift_id: int, *, actor: User, outcome: str, note: str) -> dict[str, Any]:
    """A manager's sign-off of a closed shift (FEATURES 7.5)."""
    pay.review_shift(Shift.objects.get(pk=shift_id), actor=actor, outcome=outcome, note=note)
    return queries.shift_report(shift_id, viewer=actor)


# --- payments --------------------------------------------------------------------------------


def take_payment(
    actor: User,
    *,
    patient_id: int,
    method: str,
    amount: Decimal,
    bank: str | None,
    reference: str,
    transfer_date: date | None,
    sender_name: str,
    allocations: Sequence[tuple[int, Decimal]] | None,
    auto: bool,
    visit_id: int | None,
    note: str,
    override_reason: str | None,
    override_note: str,
    approver: ApproverLogin | None,
) -> dict[str, Any]:
    """Take money into the actor's own open shift and allocate it (FEATURES 6.1-6.5).

    A reference already used for the bank is refused (``DUPLICATE_REFERENCE``) unless an
    override reason comes with a supervisor: the actor holding
    ``payments.override_duplicate``, or another user who approves at the desk.
    """
    approving = resolve_approver(approver, actor=actor) if override_reason else None
    payment = pay.record_payment(
        _own_open_shift(actor),
        Patient.objects.get(pk=patient_id),
        method,
        amount,
        actor=actor,
        bank=_bank(bank),
        reference=reference,
        transfer_date=transfer_date,
        sender_name=sender_name,
        override_reason=override_reason or None,
        override_note=override_note,
        override_approver=approving,
        allocations=list(allocations) if allocations else None,
        auto=auto,
        auto_visit_id=visit_id,
        note=note,
    )
    return queries.payment_detail(payment.pk)


def allocate(
    payment_id: int,
    *,
    actor: User,
    allocations: Sequence[tuple[int, Decimal]] | None,
    auto: bool,
    visit_id: int | None = None,
) -> dict[str, Any]:
    """Allocate a payment's remainder to open invoices (FEATURES 6.5)."""
    payment = Payment.objects.get(pk=payment_id)
    if allocations:
        pay.allocate(payment, list(allocations), actor=actor)
    elif auto:
        pay.auto_allocate(payment, actor=actor, visit_id=visit_id)
    else:
        raise DomainError(
            "ALLOCATION_REQUIRED", "Choose the invoices to pay, or allocate automatically"
        )
    return queries.payment_detail(payment_id)


def confirm_transfer(payment_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """Confirm a pending transfer after checking the bank (FEATURES 6.3)."""
    pay.confirm_transfer(Payment.objects.get(pk=payment_id), actor=actor, note=note)
    return queries.payment_detail(payment_id)


def reject_transfer(payment_id: int, *, actor: User, reason: str, note: str) -> dict[str, Any]:
    """Reject a transfer; after its shift closed the reversal lands in the actor's shift."""
    rejection = pay.reject_transfer(
        Payment.objects.get(pk=payment_id), actor=actor, reason=reason, note=note
    )
    return queries.rejection_json(rejection)


# --- refunds ---------------------------------------------------------------------------------


def request_refund(
    actor: User,
    *,
    credit_note_id: int,
    patient_id: int | None,
    amount: Decimal,
    reason: str,
    note: str,
) -> dict[str, Any]:
    """Open a refund request from credit a credit note created (FEATURES 6.7)."""
    cn = CreditNote.objects.get(pk=credit_note_id)
    patient = Patient.objects.get(pk=patient_id if patient_id is not None else cn.patient_id)
    refund = pay.request_refund(
        patient, amount, credit_note=cn, actor=actor, reason=reason, note=note
    )
    return queries.refund_detail(refund.pk)


def approve_refund(refund_id: int, *, actor: User, note: str) -> dict[str, Any]:
    pay.approve_refund(Refund.objects.get(pk=refund_id), actor=actor, note=note)
    return queries.refund_detail(refund_id)


def reject_refund(refund_id: int, *, actor: User, note: str) -> dict[str, Any]:
    pay.reject_refund(Refund.objects.get(pk=refund_id), actor=actor, note=note)
    return queries.refund_detail(refund_id)


def pay_refund(refund_id: int, *, actor: User) -> dict[str, Any]:
    """Pay an approved refund in cash from the actor's open shift."""
    pay.pay_refund(Refund.objects.get(pk=refund_id), actor=actor)
    return queries.refund_detail(refund_id)


# --- handovers -------------------------------------------------------------------------------


def hand_over(
    shift_id: int,
    *,
    actor: User,
    amount: Decimal,
    destination: str,
    to_shift_id: int | None,
    to_user_id: int | None,
    bank_reference: str,
    note: str,
) -> dict[str, Any]:
    """Cash leaves the drawer: next shift, safe, bank or a named supervisor (FEATURES 7.6)."""
    handover = pay.cash_handover(
        Shift.objects.get(pk=shift_id),
        amount,
        destination,
        actor=actor,
        to_shift=Shift.objects.get(pk=to_shift_id) if to_shift_id is not None else None,
        to_user=User.objects.get(pk=to_user_id) if to_user_id is not None else None,
        bank_reference=bank_reference,
        note=note,
    )
    return queries.handover_json(_handover(handover.pk))


def _handover(handover_id: int) -> CashHandover:
    return CashHandover.objects.select_related(
        "shift", "to_shift", "to_user", "handed_by", "received_by", "cancelled_by"
    ).get(pk=handover_id)


def receive_handover(handover_id: int, *, actor: User) -> dict[str, Any]:
    pay.receive_handover(CashHandover.objects.get(pk=handover_id), actor=actor)
    return queries.handover_json(_handover(handover_id))


def cancel_handover(handover_id: int, *, actor: User, note: str) -> dict[str, Any]:
    pay.cancel_handover(CashHandover.objects.get(pk=handover_id), actor=actor, note=note)
    return queries.handover_json(_handover(handover_id))
