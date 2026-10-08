"""Shifts, payments, allocation, verification, refunds and cash handovers (ARCHITECTURE 4.6).

The money side of the engine. Rules come from ``domain.payments``, ``domain.allocation`` and
``domain.shift``; ledger postings from ``domain.ledger`` (stored by ``apps.ledger.services``).

* Money is taken and refunded only in the cashier's own open shift (invariant 3). A cashier
  has one open shift; closing computes expected cash, needs an explanation for a variance and
  posts the variance; a closed shift never changes.
* Cash and spent patient credit are confirmed at once. Transfer, QR and card payments carry
  a bank and a reference that is unique per bank (a supervisor may accept a duplicate with a
  reason) and start pending. Pending money settles lines but is never confirmed collection.
* Allocation applies a payment to invoices' patient side; the remainder is patient credit,
  one pooled balance per patient (ledger ``PATIENT_CREDIT``). Spendable credit excludes the
  unallocated part of pending transfers.
* Rejecting a transfer reverses its allocations (lines may fall back to invoiced) and takes
  its money out of patient credit, recovering spent credit if needed. After its shift closed
  the rejection is booked in the actor's current shift as a negative payment linked to the
  original (FEATURES 6.8), and managers are alerted.
* Refunds come only from credit a credit note created, need a supervisor's approval (never
  the requester's own) and are paid in cash from the current shift.
* Cash outside the drawers (ADR 0006): the opening float comes from the safe, handovers move
  drawer cash to the bank, the safe or another shift (in transit until received), and at
  close the counted cash is swept to the safe; so a shift's ledger CASH is its drawer.
* A closed shift's report is frozen at close (``Shift.close_report``); later confirmations
  and rejections of its transfers are reported in the shift where they are booked.
* One person's merged files (FEATURES 1.4) share their money: balances and open invoices
  cover every file; new money goes to the surviving file only.

Lock order (every service in the engine): shifts (by id), patient, payment, invoice, credit
note, service lines. The patient lock serializes all money work of one patient.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pghistory
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import CreditNote, DocumentStatus, Invoice, InvoiceLine
from apps.core.models import Policy, ReasonCode, User
from apps.core.services import (
    holds_permission,
    next_number,
    notify_roles,
    require_permission,
    resolve_reason,
)
from apps.ledger import services as ledger
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.payments.models import (
    BANK_METHODS,
    Allocation,
    AllocationKind,
    Bank,
    CashHandover,
    HandoverDestination,
    Payment,
    PaymentMethod,
    Refund,
    RefundMethod,
    RefundStatus,
    ReviewOutcome,
    Shift,
    ShiftReview,
    ShiftStatus,
    Till,
    Verification,
)
from domain import allocation as da
from domain import ledger as dl
from domain import payments as dp
from domain import shift as ds
from domain.audit import Approval
from domain.errors import DomainError
from domain.money import ZERO, require_non_negative, require_positive

__all__ = [
    "HANDOVER_RECEIVER_PERMISSIONS",
    "MANAGER_ROLES",
    "PatientBalance",
    "ShiftSummary",
    "acting_shift_id",
    "allocate",
    "approve_refund",
    "auto_allocate",
    "can_receive_for_the_center",
    "cancel_handover",
    "cash_handover",
    "cash_movements",
    "close_shift",
    "confirm_transfer",
    "credit_balance",
    "current_shift",
    "deallocate_for_credit_note",
    "expected_cash",
    "notify_overdue_transfers",
    "open_refund_for_credit_note",
    "open_refunds_for_credit_note",
    "open_shift",
    "patient_balance",
    "pay_refund",
    "receive_handover",
    "record_payment",
    "reject_refund",
    "reject_transfer",
    "request_refund",
    "review_shift",
    "shift_summary",
    "spendable_credit",
]

#: Roles alerted by money exceptions (FLOW 9, FEATURES 6.8, 7.5).
MANAGER_ROLES = ["manager", "cashier_supervisor"]
#: Roles alerted when transfers wait too long for verification (FEATURES 0.13).
VERIFIER_ROLES = ["cashier_supervisor", "accountant"]


# --- shifts ----------------------------------------------------------------------------------


def current_shift(user: User) -> Shift | None:
    """The user's open shift, if any."""
    return Shift.objects.filter(cashier=user, status=ShiftStatus.OPEN).first()


def acting_shift_id(actor: User) -> int | None:
    """The actor's open shift, read ``FOR SHARE`` (inside the caller's transaction).

    A later effect booked into the actor's shift either waits for a concurrent close to
    commit (and then finds no open shift) or holds the close back until it commits, so
    nothing is booked into a shift after it closed (invariant 3).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM payments_shift WHERE cashier_id = %s AND status = 'open' FOR SHARE",
            [actor.pk],
        )
        row = cursor.fetchone()
    return int(row[0]) if row else None


def _share_open_shift(shift_id: int | None) -> int | None:
    """``shift_id`` if that shift is still open, read ``FOR SHARE``; else None."""
    if shift_id is None:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM payments_shift WHERE id = %s AND status = 'open' FOR SHARE",
            [shift_id],
        )
        row = cursor.fetchone()
    return int(row[0]) if row else None


def _lock_shifts(*ids: int | None) -> dict[int, Shift]:
    """Lock shifts ``FOR NO KEY UPDATE`` (id order): writers of one shift serialize, while
    foreign-key checks of rows referencing it (``FOR KEY SHARE``) never wait on the lock."""
    wanted = sorted({i for i in ids if i is not None})
    return {
        s.pk: s
        for s in Shift.objects.select_for_update(no_key=True).filter(pk__in=wanted).order_by("id")
    }


def _own_open(shift: Shift, actor: User) -> Shift:
    ds.require_open(ds.ShiftStatus(shift.status))
    if shift.cashier_id != actor.pk:
        raise DomainError("SHIFT_NOT_YOURS", "Use your own open shift", shift_id=shift.pk)
    return shift


def _lock_own_shift(shift: Shift | None, actor: User) -> Shift:
    chosen = shift or current_shift(actor)
    if chosen is None:
        ds.require_open(None)
        raise DomainError("SHIFT_NOT_OPEN", "Open a shift first")  # unreachable: typing
    return _own_open(_lock_shifts(chosen.pk)[chosen.pk], actor)


def open_shift(
    actor: User, opening_float: Decimal, *, till: Till | None = None, note: str = ""
) -> Shift:
    """Open the actor's shift with an opening float (FEATURES 7.1).

    Raises:
        DomainError: ``SHIFT_ALREADY_OPEN`` (also under a concurrent open), ``INVALID_AMOUNT``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="open shift"):
        # Serialize shift opening per cashier (the partial unique index is the backstop).
        list(User.objects.select_for_update().filter(pk=actor.pk).values_list("pk", flat=True))
        open_count = Shift.objects.filter(cashier=actor, status=ShiftStatus.OPEN).count()
        value = ds.validate_open(open_count, opening_float)
        try:
            with transaction.atomic():
                shift = Shift.objects.create(
                    number=next_number("SH"),
                    cashier=actor,
                    till=till,
                    opened_at=timezone.now(),
                    opening_float=value,
                    note=note.strip()[:500],
                )
        except IntegrityError as exc:
            if "payments_shift_one_open_per_cashier" in str(exc):
                raise DomainError(
                    "SHIFT_ALREADY_OPEN", "The cashier already has an open shift"
                ) from exc
            raise
        # The float leaves the safe for the drawer (ADR 0006).
        ledger.post(dl.post_shift_opening(shift.pk, value), actor=actor, shift_id=shift.pk)
        return shift


def _sum(qs: Iterable[Decimal]) -> Decimal:
    return sum(qs, ZERO)


def _payer_cash(shift: Shift) -> Decimal:
    from apps.claims.models import PayerPayment, PayerPaymentMethod

    total = PayerPayment.objects.filter(shift=shift, method=PayerPaymentMethod.CASH).aggregate(
        s=Sum("amount")
    )["s"]
    return total or ZERO


def cash_movements(shift: Shift) -> ds.CashMovements:
    """Cash through the shift's drawer from its documents.

    Cash payments (always confirmed) and payer cash recorded in the shift, cash refunds
    paid, handovers out that were not cancelled, and handovers in once the receiving
    cashier confirmed them.
    """
    cash_in = Payment.objects.filter(
        shift=shift, method=PaymentMethod.CASH, reversal_of__isnull=True
    ).aggregate(s=Sum("amount"))["s"]
    refunds = Refund.objects.filter(
        shift=shift, status=RefundStatus.PAID, method=RefundMethod.CASH
    ).aggregate(s=Sum("amount"))["s"]
    out = CashHandover.objects.filter(shift=shift, cancelled_at__isnull=True).aggregate(
        s=Sum("amount")
    )["s"]
    received = CashHandover.objects.filter(to_shift=shift, received_at__isnull=False).aggregate(
        s=Sum("amount")
    )["s"]
    return ds.CashMovements(
        opening_float=shift.opening_float,
        cash_in=(cash_in or ZERO) + _payer_cash(shift),
        cash_refunds=refunds or ZERO,
        handovers_out=out or ZERO,
        handovers_in=received or ZERO,
    )


def expected_cash(shift: Shift) -> Decimal:
    """Opening float + confirmed cash in - cash refunds - handovers out (+ received)."""
    return ds.expected_cash(cash_movements(shift))


def close_shift(
    shift: Shift,
    counted: Decimal,
    *,
    actor: User,
    reason: ReasonCode | str | None = None,
    note: str = "",
) -> Shift:
    """Close a shift with the counted cash (FEATURES 7.2, invariant 3).

    A non-zero variance needs a variance reason (and a note when the reason asks for one);
    it is posted CASH vs CASH_OVER_SHORT and managers are alerted. The counted cash then
    leaves the drawer for the safe (ADR 0006), and the shift report is frozen as it stands
    (``Shift.close_report``). Cash handed to this shift must be received first. The cashier
    closes their own shift; a holder of ``payments.view_all_shifts`` may close anyone's.

    Raises:
        DomainError: ``SHIFT_CLOSED``, ``SHIFT_NOT_YOURS``, ``INVALID_AMOUNT``,
            ``VARIANCE_EXPLANATION_REQUIRED``, ``HANDOVER_PENDING``, reason errors.
    """
    counted_cash = require_non_negative(counted, "counted")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="close shift"):
        locked = _lock_shifts(shift.pk)[shift.pk]
        if locked.cashier_id != actor.pk and not holds_permission(
            actor, "payments.view_all_shifts"
        ):
            raise DomainError("SHIFT_NOT_YOURS", "Only the cashier can close this shift")
        status = ds.ShiftStatus(locked.status)
        ds.require_open(status)
        waiting = list(
            CashHandover.objects.filter(
                to_shift=locked, received_at__isnull=True, cancelled_at__isnull=True
            ).values_list("number", flat=True)
        )
        if waiting:
            raise DomainError(
                "HANDOVER_PENDING",
                "Receive (or have the sender cancel) the cash handed to this shift first",
                handovers=waiting,
            )
        expected = expected_cash(locked)
        reason_obj = resolve_reason(reason, "variance", note) if reason else None
        explanation = (note.strip() or reason_obj.code) if reason_obj else ""
        result = ds.validate_close(
            status, expected=expected, counted=counted_cash, explanation=explanation
        )
        ledger.post(
            dl.post_shift_variance(locked.pk, result.variance), actor=actor, shift_id=locked.pk
        )
        ledger.post(dl.post_shift_sweep(locked.pk, result.counted), actor=actor, shift_id=locked.pk)
        report = _summary(
            locked, timezone.localdate(), counted=result.counted, variance=result.variance
        )
        now = timezone.now()  # after the close's own entries: nothing is booked later
        locked.status = ShiftStatus.CLOSED
        locked.closed_at = now
        locked.closed_by = actor
        locked.expected_cash = result.expected
        locked.counted_cash = result.counted
        locked.variance = result.variance
        locked.variance_reason = reason_obj
        locked.variance_note = note.strip()
        locked.close_report = report.to_json()
        locked.save(
            update_fields=[
                "status",
                "closed_at",
                "closed_by",
                "expected_cash",
                "counted_cash",
                "variance",
                "variance_reason",
                "variance_note",
                "close_report",
            ]
        )
        if result.variance != 0:
            notify_roles(
                MANAGER_ROLES,
                "shift_variance",
                shift_id=locked.pk,
                shift_number=locked.number,
                cashier_id=locked.cashier_id,
                variance=str(result.variance),
            )
    return locked


def review_shift(
    shift: Shift, *, actor: User, outcome: str = ReviewOutcome.APPROVED, note: str = ""
) -> ShiftReview:
    """Manager sign-off of a closed shift (FEATURES 7.5); a flag needs a note.

    Raises:
        PermissionRequired: the actor lacks ``payments.review_shift``.
        DomainError: ``SHIFT_NOT_CLOSED``, ``SELF_REVIEW_NOT_ALLOWED``,
            ``INVALID_REVIEW_OUTCOME``, ``REASON_REQUIRED``, ``SHIFT_ALREADY_REVIEWED``.
    """
    require_permission(actor, "payments.review_shift")
    if outcome not in ReviewOutcome.values:
        raise DomainError("INVALID_REVIEW_OUTCOME", "Unknown review outcome", outcome=outcome)
    if outcome == ReviewOutcome.FLAGGED and not note.strip():
        raise DomainError("REASON_REQUIRED", "Say why the shift is flagged")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="review shift"):
        locked = _lock_shifts(shift.pk)[shift.pk]
        if locked.status != ShiftStatus.CLOSED:
            raise DomainError("SHIFT_NOT_CLOSED", "Review a shift after it is closed")
        if locked.cashier_id == actor.pk:
            raise DomainError(
                "SELF_REVIEW_NOT_ALLOWED", "A cashier cannot sign off their own shift"
            )
        if ShiftReview.objects.filter(shift=locked).exists():
            raise DomainError("SHIFT_ALREADY_REVIEWED", "The shift was already reviewed")
        return ShiftReview.objects.create(
            shift=locked, outcome=outcome, note=note.strip(), reviewed_by=actor
        )


# --- patient credit ----------------------------------------------------------------------


def _records(patient_id: int) -> list[da.AllocationRecord]:
    """Every allocation row of the patient's payments, flagged by the payment's state now."""
    rows = (
        Allocation.objects.filter(payment__patient_id=patient_id)
        .order_by("id")
        .values_list(
            "id", "payment_id", "invoice_id", "amount", "payment__verification", "payment__method"
        )
    )
    return [
        da.AllocationRecord(
            payment_id=payment_id,
            invoice_id=invoice_id,
            amount=amount,
            seq=pk,
            pending=verification == Verification.PENDING,
            from_credit=method == PaymentMethod.PATIENT_CREDIT,
        )
        for pk, payment_id, invoice_id, amount, verification, method in rows
    ]


def _invoice_records(invoice_id: int) -> list[da.AllocationRecord]:
    """Every allocation row on one invoice, of any file's payment (merged files)."""
    rows = (
        Allocation.objects.filter(invoice_id=invoice_id)
        .order_by("id")
        .values_list(
            "id", "payment_id", "invoice_id", "amount", "payment__verification", "payment__method"
        )
    )
    return [
        da.AllocationRecord(
            payment_id=payment_id,
            invoice_id=inv,
            amount=amount,
            seq=pk,
            pending=verification == Verification.PENDING,
            from_credit=method == PaymentMethod.PATIENT_CREDIT,
        )
        for pk, payment_id, inv, amount, verification, method in rows
    ]


def credit_balance(patient: Patient | int) -> Decimal:
    """The patient's pooled credit (ledger ``PATIENT_CREDIT``); negative when they owe it."""
    return ledger.account_balance("PATIENT_CREDIT", patient=patient)


def _pending_unallocated(patient_id: int, records: Sequence[da.AllocationRecord]) -> list[Decimal]:
    out = []
    for pk, amount in Payment.objects.filter(
        patient_id=patient_id, verification=Verification.PENDING, reversal_of__isnull=True
    ).values_list("id", "amount"):
        out.append(da.unallocated(amount, [r for r in records if r.payment_id == pk]))
    return out


def spendable_credit(patient: Patient | int) -> Decimal:
    """Credit the patient may spend or have refunded: the pool less pending transfers."""
    pid = patient if isinstance(patient, int) else patient.pk
    records = _records(pid)
    return da.spendable_credit(credit_balance(pid), _pending_unallocated(pid, records))


@dataclass(frozen=True, slots=True)
class OpenInvoiceView:
    invoice_id: int
    number: str
    outstanding: Decimal


@dataclass(frozen=True, slots=True)
class PatientBalance:
    """What the cashier sees for a patient (FEATURES 1.5)."""

    credit: Decimal
    spendable: Decimal
    pending: Decimal
    outstanding: Decimal
    invoices: tuple[OpenInvoiceView, ...]

    @property
    def net(self) -> Decimal:
        """Positive when the patient owes the center, negative when the center owes them."""
        return self.outstanding - self.credit


def patient_balance(patient: Patient) -> PatientBalance:
    """Credit, spendable credit, pending transfer money and open invoices of the person.

    Every file of the person counts: a merged duplicate's credit and open invoices show on
    the surviving file (FEATURES 1.4, 1.5).
    """
    balance = ZERO
    spendable = ZERO
    pending: list[Decimal] = []
    for pid in patients.person_file_ids(patient):
        records = _records(pid)
        file_balance = credit_balance(pid)
        file_pending = _pending_unallocated(pid, records)
        balance += file_balance
        spendable += da.spendable_credit(file_balance, file_pending)
        pending.extend(file_pending)
    opened = billing.open_invoices(patient)
    return PatientBalance(
        credit=balance,
        spendable=spendable,
        pending=_sum(pending),
        outstanding=_sum(pos.outstanding for _, pos in opened),
        invoices=tuple(
            OpenInvoiceView(inv.pk, inv.number or "", pos.outstanding) for inv, pos in opened
        ),
    )


# --- payments ----------------------------------------------------------------------------


def _method(method: str) -> dp.PaymentMethod:
    try:
        return dp.PaymentMethod(method)
    except ValueError:
        raise DomainError(
            "INVALID_PAYMENT_METHOD", "Unknown payment method", method=method
        ) from None


def _duplicate_of(bank: Bank, reference: str) -> Payment | None:
    return (
        Payment.objects.filter(
            bank=bank,
            method__in=BANK_METHODS,
            reversal_of__isnull=True,
            reference_norm=dp.normalize_reference(reference),
        )
        .order_by("id")
        .first()
    )


def record_payment(
    shift: Shift,
    patient: Patient,
    method: str,
    amount: Decimal,
    *,
    actor: User,
    bank: Bank | None = None,
    reference: str = "",
    transfer_date: date | None = None,
    sender_name: str = "",
    override_reason: ReasonCode | str | None = None,
    override_note: str = "",
    override_approver: User | None = None,
    allocations: Sequence[tuple[Invoice | int, Decimal]] | None = None,
    auto: bool = False,
    note: str = "",
) -> Payment:
    """Take money from a patient into the actor's open shift (FEATURES 6.1-6.5).

    Then allocate it: to the given ``allocations``, oldest invoices first with ``auto``, or
    leave it as patient credit. Spending patient credit (``patient_credit``) must be fully
    allocated (oldest first when no allocations are given) and needs spendable credit.

    A reference already used for the bank is accepted only with a reason and a supervisor
    holding ``payments.override_duplicate``: the actor, or ``override_approver`` (the money
    still goes into the actor's own shift, FEATURES 6.2). New money is taken on the surviving
    file of a merged patient; a merged file may only spend the credit it holds.

    Raises:
        PermissionRequired: ``override_approver`` lacks ``payments.override_duplicate``.
        DomainError: ``SHIFT_NOT_OPEN``, ``SHIFT_CLOSED``, ``SHIFT_NOT_YOURS``,
            ``INVALID_PAYMENT_METHOD``, ``INVALID_AMOUNT``, ``BANK_REQUIRED``,
            ``BANK_INACTIVE``, ``REFERENCE_REQUIRED``, ``DUPLICATE_REFERENCE``,
            ``OVERRIDE_NOT_PERMITTED``, ``INSUFFICIENT_CREDIT``, ``PATIENT_MERGED``, and
            allocation errors.
    """
    m = _method(method)
    dp.validate_payment(m, amount, bank=bank.code if bank else None, reference=reference)
    if bank is not None and m in dp.REFERENCE_METHODS and not bank.active:
        raise DomainError("BANK_INACTIVE", "This bank is not in use", bank=bank.code)
    if override_approver is not None:
        require_permission(override_approver, "payments.override_duplicate")
    overrider = override_approver or actor
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"payment {m}"):
        locked_shift = _lock_own_shift(shift, actor)
        locked_patient = orders.lock_patient(patient.pk)
        if locked_patient.merged_into_id is not None and m is not dp.PaymentMethod.PATIENT_CREDIT:
            raise DomainError(
                "PATIENT_MERGED",
                "This file was merged; take the payment on the surviving file",
                surviving_patient_id=patients.resolve(locked_patient).pk,
            )
        now = timezone.now()
        if m is dp.PaymentMethod.PATIENT_CREDIT:
            da.validate_credit_spend(amount, spendable_credit(patient.pk))
        duplicate: Payment | None = None
        check = dp.ReferenceCheck(duplicate=False)
        if m in dp.REFERENCE_METHODS and bank is not None:
            duplicate = _duplicate_of(bank, reference)
            approval = None
            if override_reason:
                reason_obj = resolve_reason(override_reason, "override", override_note)
                approval = Approval(overrider.pk, now, override_note.strip(), reason_obj.code)
            existing = (
                {(dp.normalize_bank(bank.code), dp.normalize_reference(reference))}
                if duplicate is not None
                else set()
            )
            check = dp.check_reference(
                bank.code,
                reference,
                existing,
                override=approval,
                can_override=holds_permission(overrider, "payments.override_duplicate"),
            )
        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    number=next_number("RCP"),
                    shift=locked_shift,
                    patient=patient,
                    method=str(m),
                    amount=amount,
                    bank=bank if m in dp.REFERENCE_METHODS else None,
                    reference=reference.strip()[:100] if m in dp.REFERENCE_METHODS else "",
                    transfer_date=(transfer_date or timezone.localdate())
                    if m in dp.REFERENCE_METHODS
                    else None,
                    sender_name=sender_name.strip()[:200],
                    verification=str(dp.initial_verification(m)),
                    duplicate_override=check.duplicate,
                    duplicate_of=duplicate if check.duplicate else None,
                    override_by=overrider if check.duplicate else None,
                    override_reason=(
                        ReasonCode.objects.get(category="override", code=check.override.reason_code)
                        if check.duplicate and check.override is not None
                        else None
                    ),
                    override_note=override_note.strip() if check.duplicate else "",
                    override_at=now if check.duplicate else None,
                    note=note.strip()[:500],
                    created_by=actor,
                )
        except IntegrityError as exc:
            if "payments_payment_bank_reference_unique" in str(exc):
                raise DomainError(
                    "DUPLICATE_REFERENCE", "This reference was already used for this bank"
                ) from exc
            raise
        ledger.post(
            dl.post_payment_received(payment.pk, patient.pk, m, amount, locked_shift.pk),
            actor=actor,
            shift_id=locked_shift.pk,
        )
        if allocations:
            _allocate(payment, allocations, actor=actor, shift_id=locked_shift.pk)
        elif auto or m is dp.PaymentMethod.PATIENT_CREDIT:
            _auto_allocate(payment, actor=actor, shift_id=locked_shift.pk)
    return payment


def _allocation_limit(payment: Payment, records: Sequence[da.AllocationRecord]) -> Decimal:
    own = [r for r in records if r.payment_id == payment.pk]
    remainder = da.unallocated(payment.amount, own)
    balance = credit_balance(payment.patient_id)
    spendable = da.spendable_credit(balance, _pending_unallocated(payment.patient_id, records))
    return da.later_allocation_limit(
        remainder,
        pending=payment.verification == Verification.PENDING,
        credit_balance=balance,
        spendable=spendable,
    )


def _invoice_patients(invoice_ids: Iterable[int]) -> dict[int, int]:
    """The file each invoice belongs to (the AR_PATIENT dimension of its allocations)."""
    return dict(Invoice.objects.filter(pk__in=set(invoice_ids)).values_list("id", "patient_id"))


def _require_allocatable(payment: Payment) -> None:
    if payment.reversal_of_id is not None or payment.verification == Verification.REJECTED:
        raise DomainError(
            "PAYMENT_NOT_ALLOCATABLE", "A rejected or reversal payment cannot be allocated"
        )


def _allocate(
    payment: Payment,
    requests: Sequence[tuple[Invoice | int, Decimal]],
    *,
    actor: User,
    shift_id: int | None,
) -> list[Allocation]:
    """Validate and store allocations of one payment (caller holds the patient lock)."""
    _require_allocatable(payment)
    reqs = [
        da.AllocationRequest(inv if isinstance(inv, int) else inv.pk, value)
        for inv, value in requests
    ]
    patient = Patient.objects.get(pk=payment.patient_id)
    outstanding = {inv.pk: pos.outstanding for inv, pos in billing.open_invoices(patient)}
    limit = _allocation_limit(payment, _records(payment.patient_id))
    if limit <= 0:
        raise DomainError(
            "ALLOCATION_EXCEEDS_PAYMENT",
            "Nothing of this payment is left to allocate",
            payment_id=payment.pk,
        )
    plan = da.validate_allocations(
        limit,
        reqs,
        outstanding,
        allow_partial=Policy.load().allow_partial_payment,
        require_full=payment.method == PaymentMethod.PATIENT_CREDIT,
    )
    owners = _invoice_patients(r.invoice_id for r in plan.allocations)
    rows = []
    for req in plan.allocations:
        row = Allocation.objects.create(
            payment=payment,
            invoice_id=req.invoice_id,
            kind=AllocationKind.ALLOCATE,
            amount=req.amount,
            shift_id=shift_id,
            created_by=actor,
        )
        ledger.post(
            dl.post_allocation(
                row.pk,
                payment.patient_id,
                req.invoice_id,
                req.amount,
                invoice_patient_id=owners[req.invoice_id],
            ),
            actor=actor,
            shift_id=shift_id,
        )
        rows.append(row)
    for invoice in Invoice.objects.filter(pk__in=[r.invoice_id for r in plan.allocations]):
        billing.refresh_settlement(invoice)
    return rows


def _auto_allocate(payment: Payment, *, actor: User, shift_id: int | None) -> list[Allocation]:
    _require_allocatable(payment)
    patient = Patient.objects.get(pk=payment.patient_id)
    limit = _allocation_limit(payment, _records(payment.patient_id))
    opened = [
        da.OpenInvoice(inv.pk, inv.approved_at or inv.created_at, pos.outstanding)
        for inv, pos in billing.open_invoices(patient)
    ]
    full = payment.method == PaymentMethod.PATIENT_CREDIT
    if limit <= 0:
        if full:
            raise DomainError("ALLOCATION_INCOMPLETE", "Spending patient credit must be allocated")
        return []
    plan = da.auto_allocate(limit, opened, allow_partial=Policy.load().allow_partial_payment)
    if not plan.allocations and not full:
        return []
    return _allocate(
        payment,
        [(a.invoice_id, a.amount) for a in plan.allocations],
        actor=actor,
        shift_id=shift_id,
    )


def allocate(
    payment: Payment, allocations: Sequence[tuple[Invoice | int, Decimal]], *, actor: User
) -> list[Allocation]:
    """Allocate (part of) a payment's remainder to the patient's open invoices (FEATURES 6.5).

    Raises:
        DomainError: ``PAYMENT_NOT_ALLOCATABLE``, ``ALLOCATION_EXCEEDS_PAYMENT``,
            ``INVOICE_NOT_OPEN``, ``DUPLICATE_ALLOCATION``, ``ALLOCATION_EXCEEDS_OUTSTANDING``,
            ``PARTIAL_PAYMENT_NOT_ALLOWED``, ``ALLOCATION_INCOMPLETE``, ``INVALID_AMOUNT``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="allocate payment"):
        shift_id = acting_shift_id(actor)  # FOR SHARE: never a shift that closed meanwhile
        orders.lock_patient(payment.patient_id)
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        return _allocate(locked, allocations, actor=actor, shift_id=shift_id)


def auto_allocate(payment: Payment, *, actor: User) -> list[Allocation]:
    """Allocate a payment's remainder to the patient's open invoices, oldest first."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="auto allocate"):
        shift_id = acting_shift_id(actor)  # FOR SHARE: never a shift that closed meanwhile
        orders.lock_patient(payment.patient_id)
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        return _auto_allocate(locked, actor=actor, shift_id=shift_id)


def deallocate_for_credit_note(
    invoice: Invoice, credit_note: CreditNote, excess: Decimal, *, actor: User
) -> Decimal:
    """Move patient money above an invoice's new due back into patient credit.

    Called by ``apps.billing.services.approve_credit_note`` under the patient lock. Pending
    transfers are de-allocated first, then the newest allocations (``domain.allocation``).
    Returns the amount de-allocated.
    """
    records = _invoice_records(invoice.pk)
    drafts = da.deallocate_excess(invoice.pk, records, excess)
    shift_id = acting_shift_id(actor)
    payers = dict(
        Payment.objects.filter(pk__in={d.payment_id for d in drafts}).values_list(
            "id", "patient_id"
        )
    )
    total = ZERO
    for d in drafts:
        row = Allocation.objects.create(
            payment_id=d.payment_id,
            invoice=invoice,
            kind=AllocationKind.DEALLOCATION,
            amount=d.amount,
            credit_note=credit_note,
            shift_id=shift_id,
            note=f"credit note {credit_note.number}"[:500],
            created_by=actor,
        )
        ledger.post(
            dl.post_allocation(
                row.pk,
                payers[d.payment_id],
                invoice.pk,
                d.amount,
                invoice_patient_id=invoice.patient_id,
            ),
            actor=actor,
            shift_id=shift_id,
        )
        total -= d.amount
    return total


# --- verification ------------------------------------------------------------------------


def _effect_shift_id(entry_shift: Shift, actor: User) -> int | None:
    """Ledger shift of a non-cash later effect: the original while open, else the actor's.

    Both are read ``FOR SHARE``: a shift that closes meanwhile is never chosen.
    """
    original = _share_open_shift(entry_shift.pk)
    return original if original is not None else acting_shift_id(actor)


def confirm_transfer(payment: Payment, *, actor: User, note: str) -> Payment:
    """Confirm a pending transfer after checking the bank statement (FEATURES 6.3).

    ``note`` says what was checked (invariant 4: reason, approver, time).

    Raises:
        PermissionRequired: the actor lacks ``payments.confirm_transfer``.
        DomainError: ``PAYMENT_NOT_PENDING``, ``REASON_REQUIRED``.
    """
    require_permission(actor, "payments.confirm_transfer")
    text = note.strip()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"confirm: {text}"):
        orders.lock_patient(payment.patient_id)
        locked = (
            Payment.objects.select_for_update(of=("self",))
            .select_related("shift")
            .get(pk=payment.pk)
        )
        if locked.reversal_of_id is not None:
            raise DomainError("PAYMENT_NOT_PENDING", "A reversal row is not a transfer")
        now = timezone.now()
        new = dp.confirm(
            dp.PaymentMethod(locked.method),
            dp.Verification(locked.verification),
            Approval(actor.pk, now, text),
        )
        locked.verification = str(new)
        locked.verified_by = actor
        locked.verified_at = now
        locked.save(update_fields=["verification", "verified_by", "verified_at"])
        ledger.post(
            dl.post_transfer_confirmed(locked.pk, locked.amount),
            actor=actor,
            shift_id=_effect_shift_id(locked.shift, actor),
        )
    return locked


@dataclass(frozen=True, slots=True)
class Rejection:
    payment: Payment
    reversal: Payment | None
    allocations: tuple[Allocation, ...]
    uncovered: Decimal


def _latest_allocate_row(payment_id: int, invoice_id: int) -> Allocation:
    """The newest allocation row a reversal of ``(payment, invoice)`` points at."""
    row = (
        Allocation.objects.filter(
            payment_id=payment_id, invoice_id=invoice_id, kind=AllocationKind.ALLOCATE
        )
        .order_by("-id")
        .first()
    )
    if row is None:  # a positive net always has an allocation row behind it
        raise DomainError(
            "ALLOCATION_NOT_FOUND",
            "No allocation to reverse",
            payment_id=payment_id,
            invoice_id=invoice_id,
        )
    return row


def reject_transfer(
    payment: Payment, *, actor: User, reason: ReasonCode | str | None, note: str = ""
) -> Rejection:
    """Reject a pending or confirmed transfer (the money did not arrive or bounced).

    Its allocations are reversed (lines fall back to invoiced), spent credit it funded is
    recovered newest first, and its money leaves patient credit. If its shift is closed the
    effect goes to the actor's current open shift as a negative payment linked to the
    original (FEATURES 6.8). Managers are alerted; a shortfall that could not be recovered
    (the money was refunded) leaves a negative patient balance and a second alert.

    Raises:
        PermissionRequired: the actor lacks ``payments.reject_transfer``.
        DomainError: ``PAYMENT_NOT_REJECTABLE``, ``SHIFT_NOT_OPEN`` (original shift closed and
            the actor has no open shift), reason errors.
    """
    require_permission(actor, "payments.reject_transfer")
    reason_obj = resolve_reason(reason, "transfer_reject", note)
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"reject transfer: {reason_obj.code}"),
    ):
        acting = current_shift(actor)
        shifts = _lock_shifts(payment.shift_id, acting.pk if acting else None)
        orders.lock_patient(payment.patient_id)
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.reversal_of_id is not None:
            raise DomainError("PAYMENT_NOT_REJECTABLE", "A reversal row cannot be rejected")
        now = timezone.now()
        approval = Approval(actor.pk, now, note.strip(), reason_obj.code)
        was = dp.Verification(locked.verification)
        new = dp.reject(dp.PaymentMethod(locked.method), was, approval)
        original = shifts[locked.shift_id]
        current_ref = (
            ds.ShiftRef(acting.pk, ds.ShiftStatus(shifts[acting.pk].status)) if acting else None
        )
        effect = ds.late_effect_shift(
            ds.ShiftRef(original.pk, ds.ShiftStatus(original.status)), current_ref
        )
        after_close = original.status == ShiftStatus.CLOSED

        plan = da.plan_rejection(
            locked.pk,
            locked.amount,
            _records(locked.patient_id),
            credit_balance=credit_balance(locked.patient_id),
        )
        rows: list[Allocation] = []
        steps = (*plan.reversals, *plan.recovery)
        owners = _invoice_patients(d.invoice_id for d in steps)
        payers = dict(
            Payment.objects.filter(pk__in={d.payment_id for d in steps}).values_list(
                "id", "patient_id"
            )
        )
        for d in steps:
            row = Allocation.objects.create(
                payment_id=d.payment_id,
                invoice_id=d.invoice_id,
                kind=AllocationKind.REVERSAL,
                amount=d.amount,
                reversal_of=_latest_allocate_row(d.payment_id, d.invoice_id),
                shift_id=effect,
                note=f"transfer {locked.number} rejected"[:500],
                created_by=actor,
            )
            ledger.post(
                dl.post_allocation(
                    row.pk,
                    payers[d.payment_id],
                    d.invoice_id,
                    d.amount,
                    invoice_patient_id=owners[d.invoice_id],
                ),
                actor=actor,
                shift_id=effect,
            )
            rows.append(row)
        reversal = None
        if after_close:
            reversal = Payment.objects.create(
                number=next_number("RCP"),
                shift_id=effect,
                patient_id=locked.patient_id,
                method=locked.method,
                amount=-locked.amount,
                bank_id=locked.bank_id,
                reference=locked.reference,
                transfer_date=locked.transfer_date,
                sender_name=locked.sender_name,
                verification=Verification.REJECTED,
                verified_by=actor,
                verified_at=now,
                rejection_reason=reason_obj,
                rejection_note=note.strip(),
                reversal_of=locked,
                note=f"reversal of {locked.number}"[:500],
                created_by=actor,
            )
        locked.verification = str(new)
        locked.verified_by = actor
        locked.verified_at = now
        locked.rejection_reason = reason_obj
        locked.rejection_note = note.strip()
        locked.save(
            update_fields=[
                "verification",
                "verified_by",
                "verified_at",
                "rejection_reason",
                "rejection_note",
            ]
        )
        ledger.post(
            dl.post_transfer_rejected(
                locked.pk,
                locked.patient_id,
                locked.amount,
                was_confirmed=was is dp.Verification.CONFIRMED,
            ),
            actor=actor,
            shift_id=effect,
        )
        for invoice in Invoice.objects.filter(pk__in={r.invoice_id for r in rows}).order_by("id"):
            billing.refresh_settlement(invoice, at=now)
        notify_roles(
            MANAGER_ROLES,
            "transfer_rejected",
            payment_id=locked.pk,
            payment_number=locked.number,
            patient_id=locked.patient_id,
            amount=str(locked.amount),
            after_close=after_close,
            reversal_id=reversal.pk if reversal else None,
        )
        if plan.uncovered > 0:
            notify_roles(
                MANAGER_ROLES,
                "patient_credit_negative",
                patient_id=locked.patient_id,
                payment_number=locked.number,
                amount=str(plan.uncovered),
            )
    return Rejection(locked, reversal, tuple(rows), plan.uncovered)


def notify_overdue_transfers(days: int | None = None, *, today: date | None = None) -> int:
    """Alert verifiers about transfers pending more than ``days`` days (FEATURES 0.13, 6.4).

    ``days`` defaults to ``Policy.pending_transfer_alert_days``.
    """
    if days is None:
        days = int(Policy.load().pending_transfer_alert_days)
    day = today or timezone.localdate()
    overdue = []
    for pk, number, amount, created in Payment.objects.filter(
        verification=Verification.PENDING, reversal_of__isnull=True
    ).values_list("id", "number", "amount", "created_at"):
        age = dp.pending_age_days(timezone.localdate(created), day)
        if age > days:
            overdue.append({"payment_id": pk, "number": number, "amount": str(amount), "age": age})
    if not overdue:
        return 0
    return notify_roles(VERIFIER_ROLES, "transfers_pending_overdue", days=days, payments=overdue)


# --- refunds -----------------------------------------------------------------------------


def _source_available(credit_note: CreditNote, *, exclude: int | None = None) -> Decimal:
    """Credit a credit note created (its de-allocations) less refunds already against it
    (``domain.allocation.refund_source_available``)."""
    deallocated = Allocation.objects.filter(credit_note=credit_note).values_list(
        "amount", flat=True
    )
    used = Refund.objects.filter(credit_note=credit_note).exclude(status=RefundStatus.REJECTED)
    if exclude is not None:
        used = used.exclude(pk=exclude)
    return da.refund_source_available(deallocated, used.values_list("amount", flat=True))


def request_refund(
    patient: Patient,
    amount: Decimal,
    *,
    credit_note: CreditNote,
    actor: User,
    reason: ReasonCode | str | None,
    note: str = "",
    service_line: ServiceLine | None = None,
) -> Refund:
    """Open a refund request from credit created by a credit note (FEATURES 6.7, FLOW 8).

    Refunds are paid in cash; spendable credit is checked again at approval and payment.

    Raises:
        PermissionRequired: the actor lacks ``payments.request_refund``.
        DomainError: ``REFUND_SOURCE_INVALID``, ``REFUND_EXCEEDS_SOURCE``, ``INVALID_AMOUNT``,
            reason errors.
    """
    require_permission(actor, "payments.request_refund")
    return open_refund_for_credit_note(
        patient,
        amount,
        credit_note=credit_note,
        requested_by=actor,
        reason=reason,
        note=note,
        service_line=service_line,
    )


def open_refund_for_credit_note(
    patient: Patient,
    amount: Decimal,
    *,
    credit_note: CreditNote,
    requested_by: User,
    reason: ReasonCode | str | None,
    note: str = "",
    service_line: ServiceLine | None = None,
) -> Refund:
    """The refund request a cancellation opens by itself (FLOW 5: "يفتح إجراء استرداد").

    Called by ``apps.billing.services.approve_credit_note`` with the cancelling user as the
    requester, so the refund still needs another person's approval (FLOW 8).
    """
    value = require_positive(amount, "amount")
    reason_obj = resolve_reason(reason, "refund", note)
    actor = requested_by
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="request refund"):
        orders.lock_patient(patient.pk)
        cn = CreditNote.objects.get(pk=credit_note.pk)
        if cn.status != DocumentStatus.APPROVED or patient.pk not in patients.person_file_ids(
            cn.patient_id
        ):
            raise DomainError(
                "REFUND_SOURCE_INVALID", "Refunds come from an approved credit note of the patient"
            )
        available = _source_available(cn)
        # At request time only the source limits the refund (spendable is checked when the
        # money is about to leave: approval and payment).
        da.validate_refund(
            value,
            source_available=available,
            spendable=max(available, ZERO),
            approval=Approval(actor.pk, timezone.now(), note.strip(), reason_obj.code),
        )
        return Refund.objects.create(
            number=next_number("RFD"),
            patient=patient,
            amount=value,
            method=RefundMethod.CASH,
            credit_note=cn,
            service_line=service_line,
            reason_code=reason_obj,
            reason_note=note.strip(),
            requested_by=actor,
        )


def open_refunds_for_credit_note(
    credit_note: CreditNote,
    *,
    requested_by: User,
    reason: ReasonCode | str | None,
    note: str = "",
    service_line: ServiceLine | None = None,
) -> list[Refund]:
    """Refund requests for the credit a credit note's de-allocation created, one per file
    whose payment the money came from (merged files keep their own credit, FEATURES 1.4)."""
    per_file: dict[int, Decimal] = {}
    for pid, amount in Allocation.objects.filter(
        credit_note=credit_note, kind=AllocationKind.DEALLOCATION
    ).values_list("payment__patient_id", "amount"):
        per_file[pid] = per_file.get(pid, ZERO) - amount
    return [
        open_refund_for_credit_note(
            Patient.objects.get(pk=pid),
            amount,
            credit_note=credit_note,
            requested_by=requested_by,
            reason=reason,
            note=note,
            service_line=service_line,
        )
        for pid, amount in sorted(per_file.items())
        if amount > 0
    ]


def _check_refund(refund: Refund, approval: Approval) -> None:
    if refund.credit_note is None:
        raise DomainError("REFUND_SOURCE_INVALID", "A refund needs its credit note")
    da.validate_refund(
        refund.amount,
        source_available=_source_available(refund.credit_note, exclude=refund.pk),
        spendable=spendable_credit(refund.patient_id),
        approval=approval,
    )


def approve_refund(refund: Refund, *, actor: User, note: str = "") -> Refund:
    """Supervisor approval of a refund request (invariant 4, FLOW 8).

    Segregation of duties: nobody approves a refund they requested.

    Raises:
        PermissionRequired: the actor lacks ``payments.approve_refund``.
        DomainError: ``REFUND_NOT_REQUESTED``, ``REFUND_EXCEEDS_SOURCE``,
            ``REFUND_EXCEEDS_CREDIT``, ``SELF_APPROVAL_NOT_ALLOWED``.
    """
    require_permission(actor, "payments.approve_refund")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="approve refund"):
        orders.lock_patient(refund.patient_id)
        locked = (
            Refund.objects.select_for_update(of=("self",))
            .select_related("reason_code", "credit_note")
            .get(pk=refund.pk)
        )
        if locked.status != RefundStatus.REQUESTED:
            raise DomainError("REFUND_NOT_REQUESTED", "The refund is not awaiting approval")
        if locked.requested_by_id == actor.pk:
            raise DomainError(
                "SELF_APPROVAL_NOT_ALLOWED", "Another supervisor must approve your refund request"
            )
        now = timezone.now()
        _check_refund(locked, Approval(actor.pk, now, note.strip(), locked.reason_code.code))
        locked.status = RefundStatus.APPROVED
        locked.decided_by = actor
        locked.decided_at = now
        locked.decision_note = note.strip()
        locked.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    return locked


def reject_refund(refund: Refund, *, actor: User, note: str) -> Refund:
    """Supervisor refusal of a refund request; the money stays as patient credit."""
    require_permission(actor, "payments.approve_refund")
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the refund is refused")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"reject refund: {text}"):
        locked = Refund.objects.select_for_update().get(pk=refund.pk)
        if locked.status not in (RefundStatus.REQUESTED, RefundStatus.APPROVED):
            raise DomainError("REFUND_NOT_REQUESTED", "The refund is already decided")
        locked.status = RefundStatus.REJECTED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.decision_note = text
        locked.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    return locked


def pay_refund(refund: Refund, *, actor: User, shift: Shift | None = None) -> Refund:
    """Pay an approved refund in cash from the actor's open shift (FEATURES 6.7).

    Raises:
        PermissionRequired: the actor lacks ``payments.pay_refund``.
        DomainError: ``SHIFT_NOT_OPEN``, ``SHIFT_NOT_YOURS``, ``REFUND_NOT_APPROVED``,
            ``REFUND_EXCEEDS_CREDIT``, ``REFUND_EXCEEDS_SOURCE``, ``CASH_INSUFFICIENT``.
    """
    require_permission(actor, "payments.pay_refund")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="pay refund"):
        locked_shift = _lock_own_shift(shift, actor)
        orders.lock_patient(refund.patient_id)
        locked = (
            Refund.objects.select_for_update(of=("self",))
            .select_related("reason_code", "credit_note")
            .get(pk=refund.pk)
        )
        if locked.status != RefundStatus.APPROVED:
            raise DomainError("REFUND_NOT_APPROVED", "Only an approved refund can be paid")
        _check_refund(
            locked,
            Approval(
                locked.decided_by_id or actor.pk,
                locked.decided_at or timezone.now(),
                locked.decision_note,
                locked.reason_code.code,
            ),
        )
        ds.ensure_cash_available(locked.amount, expected_cash(locked_shift))
        locked.status = RefundStatus.PAID
        locked.shift = locked_shift
        locked.paid_by = actor
        locked.paid_at = timezone.now()
        locked.save(update_fields=["status", "shift", "paid_by", "paid_at"])
        ledger.post(
            dl.post_refund(locked.pk, locked.patient_id, locked.amount, locked_shift.pk),
            actor=actor,
            shift_id=locked_shift.pk,
        )
    return locked


# --- handovers ---------------------------------------------------------------------------


#: Who may take cash that is not handed to a named person or shift (the safe, a bank deposit)
#: and who may be named as the receiving supervisor: a person outside the sending drawer.
HANDOVER_RECEIVER_PERMISSIONS = ("payments.receive_handover", "payments.view_all_shifts")


def can_receive_for_the_center(user: User) -> bool:
    """Whether ``user`` confirms cash handed to the safe, the bank or a supervisor (7.6)."""
    return user.is_active and all(holds_permission(user, c) for c in HANDOVER_RECEIVER_PERMISSIONS)


def cash_handover(
    shift: Shift,
    amount: Decimal,
    destination: str,
    *,
    actor: User,
    to_shift: Shift | None = None,
    to_user: User | None = None,
    bank_reference: str = "",
    note: str = "",
) -> CashHandover:
    """Cash leaving the drawer: to the next shift, the safe, the bank or a supervisor (7.6).

    A next-shift handover names the receiving shift (its cashier receives it); a supervisor
    handover names the supervisor. Cash to the safe or the bank may name its receiver, and
    otherwise waits for any holder of :data:`HANDOVER_RECEIVER_PERMISSIONS` other than the
    sender. Until someone confirms it, the cash is in transit.

    Posted (ADR 0006): a bank deposit Dr BANK / Cr CASH; anything else Dr CASH_SAFE / Cr CASH
    (cash in the safe, or in transit until the receiving shift takes it).

    Raises:
        DomainError: ``SHIFT_NOT_OPEN``, ``SHIFT_CLOSED``, ``SHIFT_NOT_YOURS``,
            ``INVALID_HANDOVER_DESTINATION``, ``HANDOVER_TARGET_REQUIRED``,
            ``HANDOVER_TO_ITSELF``, ``HANDOVER_RECEIVER_INVALID``, ``INVALID_AMOUNT``,
            ``CASH_INSUFFICIENT``.
    """
    value = require_positive(amount, "amount")
    if destination not in HandoverDestination.values:
        raise DomainError(
            "INVALID_HANDOVER_DESTINATION", "Unknown destination", destination=destination
        )
    if destination == HandoverDestination.NEXT_SHIFT:
        if to_shift is None:
            raise DomainError("HANDOVER_TARGET_REQUIRED", "Name the shift that receives the cash")
        to_user = None
    else:
        to_shift = None
        if destination == HandoverDestination.SUPERVISOR and to_user is None:
            raise DomainError(
                "HANDOVER_TARGET_REQUIRED", "Name the supervisor who receives the cash"
            )
    if to_user is not None:
        if to_user.pk == actor.pk:
            raise DomainError("HANDOVER_TO_ITSELF", "You cannot hand cash to yourself")
        if not can_receive_for_the_center(to_user):
            raise DomainError(
                "HANDOVER_RECEIVER_INVALID",
                "This person cannot receive cash for the center",
                user=to_user.username,
            )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cash handover"):
        shifts = _lock_shifts(shift.pk, to_shift.pk if to_shift else None)
        source = _own_open(shifts[shift.pk], actor)
        if to_shift is not None:
            if to_shift.pk == source.pk:
                raise DomainError("HANDOVER_TO_ITSELF", "A shift cannot hand cash to itself")
            ds.require_open(ds.ShiftStatus(shifts[to_shift.pk].status))
        ds.ensure_cash_available(value, expected_cash(source))
        handover = CashHandover.objects.create(
            number=next_number("HND"),
            shift=source,
            destination=destination,
            to_shift=to_shift,
            to_user=to_user or (to_shift.cashier if to_shift else None),
            amount=value,
            bank_reference=bank_reference.strip()[:100],
            handed_by=actor,
            handed_at=timezone.now(),
            note=note.strip()[:500],
        )
        ledger.post(
            dl.post_cash_handover(
                handover.pk,
                source.pk,
                value,
                to_bank=destination == HandoverDestination.BANK_DEPOSIT,
            ),
            actor=actor,
            shift_id=source.pk,
        )
        return handover


def receive_handover(handover: CashHandover, *, actor: User) -> CashHandover:
    """The receiving cashier (or named user) confirms the cash arrived.

    Never the sender (invariant 4: the cash leaving a drawer is confirmed by someone else).
    Cash handed to nobody in particular (the safe, a bank deposit) is confirmed by a holder of
    :data:`HANDOVER_RECEIVER_PERMISSIONS`. Cash handed to a shift enters its drawer
    (Dr CASH / Cr CASH_SAFE, ADR 0006).

    Raises:
        DomainError: ``HANDOVER_ALREADY_RECEIVED``, ``HANDOVER_CANCELLED``,
            ``HANDOVER_SELF_RECEIPT``, ``HANDOVER_NOT_YOURS``, ``SHIFT_CLOSED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="receive handover"):
        row = CashHandover.objects.get(pk=handover.pk)
        _lock_shifts(row.to_shift_id)
        locked = (
            CashHandover.objects.select_for_update(of=("self",))
            .select_related("to_shift")
            .get(pk=handover.pk)
        )
        if locked.received_at is not None:
            raise DomainError("HANDOVER_ALREADY_RECEIVED", "The cash was already received")
        if locked.cancelled_at is not None:
            raise DomainError("HANDOVER_CANCELLED", "The handover was cancelled")
        sender = Shift.objects.values_list("cashier_id", flat=True).get(pk=locked.shift_id)
        if actor.pk in (sender, locked.handed_by_id):
            raise DomainError(
                "HANDOVER_SELF_RECEIPT", "Someone else must confirm the cash you handed over"
            )
        target = locked.to_user_id or (locked.to_shift.cashier_id if locked.to_shift else None)
        if target is not None and target != actor.pk:
            raise DomainError("HANDOVER_NOT_YOURS", "This cash is handed to someone else")
        if target is None and not can_receive_for_the_center(actor):
            raise DomainError(
                "HANDOVER_NOT_YOURS", "A supervisor or an accountant receives this cash"
            )
        if locked.to_shift is not None:
            ds.require_open(ds.ShiftStatus(locked.to_shift.status))
        locked.received_by = actor
        locked.received_at = timezone.now()
        locked.save(update_fields=["received_by", "received_at"])
        if locked.to_shift_id is not None:
            ledger.post(
                dl.post_handover_received(locked.pk, locked.to_shift_id, locked.amount),
                actor=actor,
                shift_id=locked.to_shift_id,
            )
    return locked


def cancel_handover(handover: CashHandover, *, actor: User, note: str) -> CashHandover:
    """An unreceived handover comes back to the sender's drawer (FEATURES 7.6).

    Only while the sending shift is open, by its cashier or a holder of
    ``payments.view_all_shifts``, with a reason. The cash leaves the safe or transit again
    (or the bank, for a deposit that did not happen).

    Raises:
        DomainError: ``REASON_REQUIRED``, ``HANDOVER_ALREADY_RECEIVED``,
            ``HANDOVER_CANCELLED``, ``SHIFT_CLOSED``, ``SHIFT_NOT_YOURS``.
    """
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the handover is cancelled")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"cancel handover: {text}"):
        row = CashHandover.objects.get(pk=handover.pk)
        source = _lock_shifts(row.shift_id)[row.shift_id]
        ds.require_open(ds.ShiftStatus(source.status))
        if source.cashier_id != actor.pk and not holds_permission(
            actor, "payments.view_all_shifts"
        ):
            raise DomainError("SHIFT_NOT_YOURS", "Only the sender can cancel this handover")
        locked = CashHandover.objects.select_for_update().get(pk=handover.pk)
        if locked.received_at is not None:
            raise DomainError("HANDOVER_ALREADY_RECEIVED", "The cash was already received")
        if locked.cancelled_at is not None:
            raise DomainError("HANDOVER_CANCELLED", "The handover is already cancelled")
        locked.cancelled_at = timezone.now()
        locked.cancelled_by = actor
        locked.cancel_note = text[:500]
        locked.save(update_fields=["cancelled_at", "cancelled_by", "cancel_note"])
        ledger.post(
            dl.post_handover_cancelled(
                locked.pk,
                source.pk,
                locked.amount,
                to_bank=locked.destination == HandoverDestination.BANK_DEPOSIT,
            ),
            actor=actor,
            shift_id=source.pk,
        )
    return locked


# --- shift report ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PendingTransfer:
    payment_id: int
    number: str
    amount: Decimal
    age_days: int


@dataclass(frozen=True, slots=True)
class ConfirmedTransfer:
    payment_id: int
    number: str
    bank: str
    reference: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ApproverTotal:
    user_id: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ReasonTotal:
    reason: str
    count: int
    amount: Decimal


def _money(value: object) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class ShiftSummary:
    """The shift report (FLOW 9, FEATURES 7.3): confirmed money apart from pending.

    ``late_reversals`` and ``late_confirmations`` are transfers of earlier, closed shifts
    rejected or confirmed while this shift was the acting one. ``credit_notes`` and
    ``cancellations`` are the credit notes booked in this shift (by reason);
    ``credit_from_cancellations`` the patient money they turned into credit and
    ``credit_unallocated`` the money taken here and left as patient credit. A closed shift
    is served from the snapshot taken at close (``frozen``), never recomputed (invariant 3).
    """

    shift_id: int
    movements: ds.CashMovements
    expected_cash: Decimal
    counted_cash: Decimal | None
    variance: Decimal | None
    collection: ds.CollectionSummary
    pending: tuple[PendingTransfer, ...]
    late_reversals: Decimal
    refunds_paid: Decimal
    discounts: tuple[ApproverTotal, ...]
    credit_notes: Decimal
    confirmed_transfers: tuple[ConfirmedTransfer, ...] = ()
    late_confirmations: Decimal = ZERO
    cancellations: tuple[ReasonTotal, ...] = ()
    refunds: tuple[ReasonTotal, ...] = ()
    credit_from_cancellations: Decimal = ZERO
    credit_unallocated: Decimal = ZERO
    frozen: bool = False

    def to_json(self) -> dict[str, Any]:
        m, c = self.movements, self.collection
        return {
            "shift_id": self.shift_id,
            "movements": {
                "opening_float": str(m.opening_float),
                "cash_in": str(m.cash_in),
                "cash_refunds": str(m.cash_refunds),
                "handovers_out": str(m.handovers_out),
                "handovers_in": str(m.handovers_in),
            },
            "expected_cash": str(self.expected_cash),
            "counted_cash": None if self.counted_cash is None else str(self.counted_cash),
            "variance": None if self.variance is None else str(self.variance),
            "collection": {
                "cash_confirmed": str(c.cash_confirmed),
                "bank_confirmed": str(c.bank_confirmed),
                "bank_pending": str(c.bank_pending),
                "bank_rejected": str(c.bank_rejected),
                "credit_used": str(c.credit_used),
            },
            "pending": [[p.payment_id, p.number, str(p.amount), p.age_days] for p in self.pending],
            "confirmed_transfers": [
                [t.payment_id, t.number, t.bank, t.reference, str(t.amount)]
                for t in self.confirmed_transfers
            ],
            "late_reversals": str(self.late_reversals),
            "late_confirmations": str(self.late_confirmations),
            "refunds_paid": str(self.refunds_paid),
            "refunds": [[r.reason, r.count, str(r.amount)] for r in self.refunds],
            "discounts": [[d.user_id, str(d.amount)] for d in self.discounts],
            "credit_notes": str(self.credit_notes),
            "cancellations": [[r.reason, r.count, str(r.amount)] for r in self.cancellations],
            "credit_from_cancellations": str(self.credit_from_cancellations),
            "credit_unallocated": str(self.credit_unallocated),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ShiftSummary:
        m: dict[str, Any] = data["movements"]
        c: dict[str, Any] = data["collection"]

        def rows(key: str) -> list[list[Any]]:
            value: list[list[Any]] = data.get(key) or []
            return value

        counted, var = data.get("counted_cash"), data.get("variance")
        return cls(
            shift_id=int(str(data["shift_id"])),
            movements=ds.CashMovements(**{k: _money(v) for k, v in m.items()}),
            expected_cash=_money(data["expected_cash"]),
            counted_cash=None if counted is None else _money(counted),
            variance=None if var is None else _money(var),
            collection=ds.CollectionSummary(**{k: _money(v) for k, v in c.items()}),
            pending=tuple(
                PendingTransfer(int(str(r[0])), str(r[1]), _money(r[2]), int(str(r[3])))
                for r in rows("pending")
            ),
            confirmed_transfers=tuple(
                ConfirmedTransfer(int(str(r[0])), str(r[1]), str(r[2]), str(r[3]), _money(r[4]))
                for r in rows("confirmed_transfers")
            ),
            late_reversals=_money(data["late_reversals"]),
            late_confirmations=_money(data.get("late_confirmations", "0.00")),
            refunds_paid=_money(data["refunds_paid"]),
            refunds=tuple(
                ReasonTotal(str(r[0]), int(str(r[1])), _money(r[2])) for r in rows("refunds")
            ),
            discounts=tuple(ApproverTotal(int(str(r[0])), _money(r[1])) for r in rows("discounts")),
            credit_notes=_money(data["credit_notes"]),
            cancellations=tuple(
                ReasonTotal(str(r[0]), int(str(r[1])), _money(r[2])) for r in rows("cancellations")
            ),
            credit_from_cancellations=_money(data.get("credit_from_cancellations", "0.00")),
            credit_unallocated=_money(data.get("credit_unallocated", "0.00")),
            frozen=True,
        )


def _booked_in(shift: Shift, source_type: str) -> list[int]:
    """Source ids of journal entries of ``source_type`` booked in ``shift``."""
    from apps.ledger.models import JournalEntry

    return list(
        JournalEntry.objects.filter(shift=shift, source_type=source_type).values_list(
            "source_id", flat=True
        )
    )


def _summary(
    shift: Shift,
    day: date,
    *,
    counted: Decimal | None = None,
    variance: Decimal | None = None,
) -> ShiftSummary:
    """The report of a shift from its documents and the ledger's shift attribution."""
    movements = cash_movements(shift)
    payments = Payment.objects.filter(shift=shift)
    originals = payments.filter(reversal_of__isnull=True)
    collection = ds.collection_summary(
        ds.ShiftPayment(dp.PaymentMethod(m), dp.Verification(v), a)
        for m, v, a in originals.values_list("method", "verification", "amount")
    )
    pending = tuple(
        PendingTransfer(pk, number, amount, dp.pending_age_days(timezone.localdate(created), day))
        for pk, number, amount, created in originals.filter(
            verification=Verification.PENDING
        ).values_list("id", "number", "amount", "created_at")
    )
    confirmed = tuple(
        ConfirmedTransfer(pk, number, bank or "", reference, amount)
        for pk, number, bank, reference, amount in originals.filter(
            verification=Verification.CONFIRMED, method__in=BANK_METHODS
        )
        .order_by("id")
        .values_list("id", "number", "bank__code", "reference", "amount")
    )
    late = -(payments.filter(reversal_of__isnull=False).aggregate(s=Sum("amount"))["s"] or ZERO)
    late_confirmed = (
        Payment.objects.filter(pk__in=_booked_in(shift, "transfer_confirm"))
        .exclude(shift=shift)
        .aggregate(s=Sum("amount"))["s"]
        or ZERO
    )
    discounts = tuple(
        ApproverTotal(user_id, total)
        for user_id, total in InvoiceLine.objects.filter(
            invoice_id__in=_booked_in(shift, "invoice"), frozen=True, discount__gt=0
        )
        .values_list("discount_approved_by")
        .annotate(total=Sum("discount"))
        .values_list("discount_approved_by", "total")
        .order_by("discount_approved_by")
    )
    notes = CreditNote.objects.filter(pk__in=_booked_in(shift, "credit_note"))
    cancellations = tuple(
        ReasonTotal(code, count, total)
        for code, count, total in notes.values_list("reason_code__code")
        .annotate(n=Count("id"), total=Sum("gross_total"))
        .values_list("reason_code__code", "n", "total")
        .order_by("reason_code__code")
    )
    refunds = tuple(
        ReasonTotal(code, count, total)
        for code, count, total in Refund.objects.filter(shift=shift, status=RefundStatus.PAID)
        .values_list("reason_code__code")
        .annotate(n=Count("id"), total=Sum("amount"))
        .values_list("reason_code__code", "n", "total")
        .order_by("reason_code__code")
    )
    deallocated = -(
        Allocation.objects.filter(shift=shift, kind=AllocationKind.DEALLOCATION).aggregate(
            s=Sum("amount")
        )["s"]
        or ZERO
    )
    taken = originals.exclude(method=PaymentMethod.PATIENT_CREDIT)
    allocated_here = (
        Allocation.objects.filter(
            payment__in=taken, shift=shift, kind=AllocationKind.ALLOCATE
        ).aggregate(s=Sum("amount"))["s"]
        or ZERO
    )
    unallocated = (taken.aggregate(s=Sum("amount"))["s"] or ZERO) - allocated_here
    return ShiftSummary(
        shift_id=shift.pk,
        movements=movements,
        expected_cash=ds.expected_cash(movements),
        counted_cash=counted if counted is not None else shift.counted_cash,
        variance=variance if variance is not None else shift.variance,
        collection=collection,
        pending=pending,
        late_reversals=late,
        refunds_paid=movements.cash_refunds,
        discounts=discounts,
        credit_notes=notes.aggregate(s=Sum("gross_total"))["s"] or ZERO,
        confirmed_transfers=confirmed,
        late_confirmations=late_confirmed,
        cancellations=cancellations,
        refunds=refunds,
        credit_from_cancellations=deallocated,
        credit_unallocated=max(unallocated, ZERO),
    )


def shift_summary(shift: Shift, *, today: date | None = None) -> ShiftSummary:
    """The report of one shift: live while open, the snapshot taken at close once closed.

    A closed shift's report never changes (invariant 3): a transfer it took that is later
    confirmed or rejected shows in the acting shift's ``late_confirmations`` /
    ``late_reversals``, not in the closed shift.
    """
    fresh = Shift.objects.get(pk=shift.pk)
    if fresh.status == ShiftStatus.CLOSED and fresh.close_report:
        return ShiftSummary.from_json(fresh.close_report)
    return _summary(fresh, today or timezone.localdate())
