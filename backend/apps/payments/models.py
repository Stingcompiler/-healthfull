"""Shifts, patient payments, allocations, refunds and cash handovers (ARCHITECTURE 4.6).

Database backstops:

* A cashier has at most one open shift (partial unique index). A closed shift never changes
  (trigger, invariant 3), its report is frozen at close (``close_report``), and no payment,
  refund, allocation or handover can be written against a shift that is not open: later
  effects post to the acting user's current shift, linked to the original row
  (``reversal_of``).
* A payment's money fields never change and payments are never deleted; only verification
  and override bookkeeping moves, and verification only forward (pending -> confirmed or
  rejected, confirmed -> rejected). A rejected transfer is terminal.
* A refund's request never changes; its status moves only forward (requested -> approved or
  rejected, approved -> paid or rejected) and its approver is never its requester.
* A handover's amount, route and sender never change; it is received once (into an open
  shift) or cancelled once (while the sender's shift is open), and never deleted.
* ``(bank, normalized reference)`` is unique for bank/QR/card payments, except rows a
  supervisor explicitly overrode as a known duplicate (FEATURES 6.2).
* Allocations are append-only; a reversal is a new negative row (ARCHITECTURE 4.9).
"""

from __future__ import annotations

from typing import Any, ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import (
    append_only,
    choice_check,
    money_field,
    protect_when,
    shift_must_be_open,
    track_history,
    truncate_guard,
)
from domain.payments import normalize_reference


@track_history()
class Bank(models.Model):
    """Banks and wallets that transfers arrive through (Bankak and others, FEATURES 6.1)."""

    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "bank"
        ordering: ClassVar[list[str]] = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.name_en or self.code


@track_history()
class Till(models.Model):
    """A cash drawer (FEATURES 7.7, V1?)."""

    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "till"
        ordering: ClassVar[list[str]] = ["code"]

    def __str__(self) -> str:
        return self.name_en or self.code


class ShiftStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


@track_history()
class Shift(models.Model):
    """A cashier's working session with its cash drawer (FEATURES 7.1-7.4).

    At close: ``expected_cash`` = opening float + confirmed cash in - cash refunds - cash
    handovers out; ``variance`` = counted - expected, explained by a reason when non-zero.
    """

    number = models.CharField(max_length=30, unique=True)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shifts"
    )
    till = models.ForeignKey(
        Till, on_delete=models.PROTECT, null=True, blank=True, related_name="shifts"
    )
    status = models.CharField(max_length=10, choices=ShiftStatus.choices, default=ShiftStatus.OPEN)
    opened_at = models.DateTimeField()
    opening_float = money_field()
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    expected_cash = money_field(null=True, blank=True)
    counted_cash = money_field(null=True, blank=True)
    variance = money_field(null=True, blank=True)
    variance_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "variance"},
    )
    variance_note = models.TextField(blank=True)
    note = models.CharField(max_length=500, blank=True)
    close_report = models.JSONField(
        null=True,
        blank=True,
        help_text="The shift report as it stood at close (FEATURES 7.3); never recomputed.",
    )

    class Meta:
        verbose_name = "shift"
        ordering: ClassVar[list[str]] = ["-opened_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", ShiftStatus, "payments_shift_status_valid"),
            models.UniqueConstraint(
                fields=["cashier"],
                condition=Q(status=ShiftStatus.OPEN),
                name="payments_shift_one_open_per_cashier",
            ),
            models.CheckConstraint(
                condition=Q(opening_float__gte=0), name="payments_shift_float_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(counted_cash__isnull=True) | Q(counted_cash__gte=0),
                name="payments_shift_counted_non_negative",
            ),
            models.CheckConstraint(
                condition=~Q(status=ShiftStatus.CLOSED)
                | Q(
                    closed_at__isnull=False,
                    closed_by__isnull=False,
                    expected_cash__isnull=False,
                    counted_cash__isnull=False,
                    variance__isnull=False,
                ),
                name="payments_shift_close_documented",
            ),
            models.CheckConstraint(
                condition=Q(variance__isnull=True)
                | Q(variance=F("counted_cash") - F("expected_cash")),
                name="payments_shift_variance_is_counted_minus_expected",
            ),
            models.CheckConstraint(
                condition=Q(variance__isnull=True)
                | Q(variance=0)
                | Q(variance_reason__isnull=False),
                name="payments_shift_variance_explained",
            ),
            models.CheckConstraint(
                condition=Q(closed_at__isnull=True) | Q(closed_at__gte=F("opened_at")),
                name="payments_shift_close_after_open",
            ),
            models.CheckConstraint(
                condition=~Q(status=ShiftStatus.CLOSED) | Q(close_report__isnull=False),
                name="payments_shift_close_report_frozen",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["cashier", "-opened_at"], name="payments_shift_cashier_idx"),
            models.Index(fields=["status", "-closed_at"], name="payments_shift_status_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            protect_when(
                "shift_closed",
                code="SHIFT_CLOSED",
                message="a closed shift never changes",
                condition=pgtrigger.Q(old__status="closed"),
            ),
        ]

    def __str__(self) -> str:
        return self.number


class ReviewOutcome(models.TextChoices):
    APPROVED = "approved", "Signed off"
    FLAGGED = "flagged", "Flagged for follow-up"


class ShiftReview(models.Model):
    """Manager sign-off of a closed shift (FEATURES 7.5). Append-only, one per shift."""

    shift = models.OneToOneField(Shift, on_delete=models.PROTECT, related_name="review")
    outcome = models.CharField(max_length=10, choices=ReviewOutcome.choices)
    note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "shift review"
        ordering: ClassVar[list[str]] = ["-reviewed_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("outcome", ReviewOutcome, "payments_shiftreview_outcome_valid"),
            models.CheckConstraint(
                condition=Q(outcome=ReviewOutcome.APPROVED) | ~Q(note=""),
                name="payments_shiftreview_flag_explained",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [append_only()]

    def __str__(self) -> str:
        return f"{self.shift_id}: {self.outcome}"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    QR = "qr", "QR payment"
    CARD = "card", "Card"
    PATIENT_CREDIT = "patient_credit", "Patient credit balance"


#: Methods that carry a bank and a reference and start ``pending`` verification.
BANK_METHODS = [PaymentMethod.BANK_TRANSFER, PaymentMethod.QR, PaymentMethod.CARD]


class Verification(models.TextChoices):
    PENDING = "pending", "Pending verification"
    CONFIRMED = "confirmed", "Confirmed"
    REJECTED = "rejected", "Rejected"


_PAYMENT_MONEY_FIELDS = [
    "number",
    "shift",
    "patient",
    "method",
    "amount",
    "bank",
    "reference",
    "reference_norm",
    "transfer_date",
    "reversal_of",
    "created_by",
    "created_at",
]


@track_history(exclude=["reference_norm"])
class Payment(models.Model):
    """Money received from (or, as a negative reversal row, given back to) a patient.

    ``verification``: cash and patient credit are ``confirmed`` at once; bank/QR/card start
    ``pending`` and move to ``confirmed`` or ``rejected`` by a ``payments.confirm_transfer``
    holder. Pending money settles lines but is never reported as confirmed collection.
    A rejection after the shift closed is booked as a negative row (``reversal_of``) in the
    acting user's current shift (FEATURES 6.8).
    """

    number = models.CharField(max_length=30, unique=True)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="payments")
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="payments"
    )
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = money_field()
    bank = models.ForeignKey(
        Bank, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    reference = models.CharField(max_length=100, blank=True)
    reference_norm = models.CharField(
        max_length=200,
        blank=True,
        editable=False,
        help_text="``domain.payments.normalize_reference(reference)``, written by the service.",
    )
    transfer_date = models.DateField(null=True, blank=True)
    sender_name = models.CharField(max_length=200, blank=True)
    verification = models.CharField(
        max_length=20, choices=Verification.choices, default=Verification.PENDING
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "transfer_reject"},
    )
    rejection_note = models.TextField(blank=True)
    duplicate_override = models.BooleanField(
        default=False, help_text="Supervisor accepted a reference already used for this bank."
    )
    duplicate_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="duplicates"
    )
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    override_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "override"},
    )
    override_note = models.TextField(blank=True)
    override_at = models.DateTimeField(null=True, blank=True)
    reversal_of = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal"
    )
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "payment"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("method", PaymentMethod, "payments_payment_method_valid"),
            choice_check("verification", Verification, "payments_payment_verification_valid"),
            models.CheckConstraint(
                condition=(Q(reversal_of__isnull=True) & Q(amount__gt=0))
                | (Q(reversal_of__isnull=False) & Q(amount__lt=0)),
                name="payments_payment_amount_sign",
            ),
            models.CheckConstraint(
                condition=Q(method__in=BANK_METHODS)
                | (Q(bank__isnull=True) & Q(reference="") & Q(verification=Verification.CONFIRMED)),
                name="payments_payment_cash_is_confirmed_without_bank",
            ),
            models.CheckConstraint(
                condition=~Q(method__in=BANK_METHODS)
                | (Q(bank__isnull=False) & ~Q(reference="") & ~Q(reference_norm="")),
                name="payments_payment_bank_needs_reference",
            ),
            # Invariant 4: confirmation and rejection record actor and time; rejection a reason.
            models.CheckConstraint(
                condition=~Q(method__in=BANK_METHODS)
                | Q(verification=Verification.PENDING)
                | Q(verified_by__isnull=False, verified_at__isnull=False),
                name="payments_payment_verification_documented",
            ),
            models.CheckConstraint(
                condition=~Q(verification=Verification.REJECTED)
                | Q(rejection_reason__isnull=False),
                name="payments_payment_rejection_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(duplicate_override=False)
                | Q(
                    duplicate_of__isnull=False,
                    override_by__isnull=False,
                    override_reason__isnull=False,
                    override_at__isnull=False,
                ),
                name="payments_payment_override_documented",
            ),
            models.UniqueConstraint(
                fields=["bank", "reference_norm"],
                condition=Q(method__in=BANK_METHODS)
                & Q(duplicate_override=False)
                & Q(reversal_of__isnull=True),
                name="payments_payment_bank_reference_unique",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["shift", "method"], name="payments_payment_shift_idx"),
            models.Index(fields=["patient", "-created_at"], name="payments_payment_patient_idx"),
            models.Index(
                fields=["verification", "created_at"],
                condition=Q(verification=Verification.PENDING),
                name="payments_payment_pending_idx",
            ),
            models.Index(fields=["bank", "reference_norm"], name="payments_payment_ref_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            pgtrigger.ReadOnly(name="payment_money_readonly", fields=_PAYMENT_MONEY_FIELDS),
            protect_when(
                "payment_no_delete",
                code="PAYMENT_PERMANENT",
                message="payments are never deleted; reverse them",
                operation=pgtrigger.Delete,
            ),
            protect_when(
                "payment_rejected_final",
                code="PAYMENT_REJECTED",
                message="a rejected transfer never changes",
                condition=pgtrigger.Q(old__verification="rejected"),
                operation=pgtrigger.Update,
            ),
            pgtrigger.Trigger(
                name="payment_verification_forward",
                when=pgtrigger.Before,
                operation=pgtrigger.Update,
                func="""
                    IF NEW.verification IS DISTINCT FROM OLD.verification AND NOT (
                        (OLD.verification = 'pending'
                         AND NEW.verification IN ('confirmed', 'rejected'))
                        OR (OLD.verification = 'confirmed' AND NEW.verification = 'rejected')
                    ) THEN
                        RAISE EXCEPTION
                            'PAYMENT_VERIFICATION_TRANSITION: payment % cannot go from % to %',
                            OLD.id, OLD.verification, NEW.verification;
                    END IF;
                    RETURN NEW;
                """,
            ),
            shift_must_be_open(),
        ]

    def __str__(self) -> str:
        return self.number

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Write ``reference_norm`` from the one Python definition of a reference's canonical
        form (``domain.payments.normalize_reference``), so the unique index and duplicate
        lookups compare exactly what the domain compares."""
        bank = self.method in BANK_METHODS
        self.reference_norm = normalize_reference(self.reference) if bank else ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "reference" in update_fields:
            kwargs["update_fields"] = {*update_fields, "reference_norm"}
        super().save(*args, **kwargs)


class AllocationKind(models.TextChoices):
    ALLOCATE = "allocate", "Allocation to an invoice"
    REVERSAL = "reversal", "Reversal of an allocation"
    DEALLOCATION = "deallocation", "De-allocation after a credit note"


class Allocation(models.Model):
    """Part of a payment applied to an invoice's patient side (FEATURES 6.5). Append-only.

    The sum per payment never exceeds its amount; the remainder is patient credit.
    """

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, related_name="allocations"
    )
    kind = models.CharField(
        max_length=20, choices=AllocationKind.choices, default=AllocationKind.ALLOCATE
    )
    amount = money_field()
    # A ForeignKey, not one-to-one: a credit-funded allocation can be taken back in parts by
    # separate transfer rejections (``domain.allocation.plan_rejection`` recovery rows).
    reversal_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals"
    )
    credit_note = models.ForeignKey(
        "billing.CreditNote",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deallocations",
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
        help_text="Shift of the acting user when the row was written.",
    )
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "allocation"
        ordering: ClassVar[list[str]] = ["created_at", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", AllocationKind, "payments_allocation_kind_valid"),
            models.CheckConstraint(
                condition=(
                    Q(kind=AllocationKind.ALLOCATE)
                    & Q(amount__gt=0)
                    & Q(reversal_of__isnull=True)
                    & Q(credit_note__isnull=True)
                )
                | (Q(kind=AllocationKind.REVERSAL) & Q(amount__lt=0) & Q(reversal_of__isnull=False))
                | (
                    Q(kind=AllocationKind.DEALLOCATION)
                    & Q(amount__lt=0)
                    & Q(credit_note__isnull=False)
                    & Q(reversal_of__isnull=True)
                ),
                name="payments_allocation_kind_shape",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["invoice"], name="payments_alloc_invoice_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            append_only(),
            shift_must_be_open(),
        ]

    def __str__(self) -> str:
        return f"{self.payment_id} -> {self.invoice_id}: {self.amount}"


class RefundStatus(models.TextChoices):
    REQUESTED = "requested", "Awaiting approval"
    APPROVED = "approved", "Approved, not paid"
    REJECTED = "rejected", "Rejected"
    PAID = "paid", "Paid"


class RefundMethod(models.TextChoices):
    CASH = "cash", "Cash"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"


@track_history()
class Refund(models.Model):
    """Money paid back from patient credit created by a credit note or cancellation.

    Requested by a cashier, decided by a supervisor, paid from the payer's current shift
    (FEATURES 6.7). Paid and rejected refunds never change.
    """

    number = models.CharField(max_length=30, unique=True)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="refunds"
    )
    amount = money_field()
    method = models.CharField(
        max_length=20, choices=RefundMethod.choices, default=RefundMethod.CASH
    )
    bank = models.ForeignKey(
        Bank, on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )
    reference = models.CharField(max_length=100, blank=True)
    credit_note = models.ForeignKey(
        "billing.CreditNote",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refunds",
    )
    service_line = models.ForeignKey(
        "orders.ServiceLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refunds",
    )
    reason_code = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"category": "refund"},
    )
    reason_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=RefundStatus.choices, default=RefundStatus.REQUESTED
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    shift = models.ForeignKey(
        Shift, on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "refund"
        ordering: ClassVar[list[str]] = ["-requested_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", RefundStatus, "payments_refund_status_valid"),
            choice_check("method", RefundMethod, "payments_refund_method_valid"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payments_refund_positive"),
            models.CheckConstraint(
                condition=Q(credit_note__isnull=False) | Q(service_line__isnull=False),
                name="payments_refund_has_source",
            ),
            models.CheckConstraint(
                condition=Q(status=RefundStatus.REQUESTED)
                | Q(decided_by__isnull=False, decided_at__isnull=False),
                name="payments_refund_decision_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=RefundStatus.PAID)
                | Q(shift__isnull=False, paid_by__isnull=False, paid_at__isnull=False),
                name="payments_refund_payment_documented",
            ),
            models.CheckConstraint(
                condition=~Q(method=RefundMethod.BANK_TRANSFER) | Q(bank__isnull=False),
                name="payments_refund_transfer_has_bank",
            ),
            # Segregation of duties (FLOW 8): nobody approves their own refund request.
            models.CheckConstraint(
                condition=~Q(status__in=[RefundStatus.APPROVED, RefundStatus.PAID])
                | ~Q(decided_by=F("requested_by")),
                name="payments_refund_approver_not_requester",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "requested_at"], name="payments_refund_status_idx"),
            models.Index(fields=["patient"], name="payments_refund_patient_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            protect_when(
                "refund_final",
                code="REFUND_FINAL",
                message="paid or rejected refunds never change",
                condition=pgtrigger.Q(old__status__in=["paid", "rejected"]),
            ),
            pgtrigger.ReadOnly(
                name="refund_request_readonly",
                fields=[
                    "number",
                    "patient",
                    "amount",
                    "method",
                    "bank",
                    "reference",
                    "credit_note",
                    "service_line",
                    "reason_code",
                    "reason_note",
                    "requested_by",
                    "requested_at",
                ],
            ),
            pgtrigger.Trigger(
                name="refund_forward",
                when=pgtrigger.Before,
                operation=pgtrigger.Update,
                func="""
                    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                        (OLD.status = 'requested' AND NEW.status IN ('approved', 'rejected'))
                        OR (OLD.status = 'approved' AND NEW.status IN ('paid', 'rejected'))
                    ) THEN
                        RAISE EXCEPTION 'REFUND_TRANSITION: refund % cannot go from % to %',
                            OLD.id, OLD.status, NEW.status;
                    END IF;
                    IF OLD.status = 'approved' AND NEW.status IN ('approved', 'paid') AND (
                        NEW.decided_by_id IS DISTINCT FROM OLD.decided_by_id
                        OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                        OR NEW.decision_note IS DISTINCT FROM OLD.decision_note) THEN
                        RAISE EXCEPTION 'REFUND_DECISION_FINAL: refund % was already approved',
                            OLD.id;
                    END IF;
                    RETURN NEW;
                """,
            ),
            shift_must_be_open(),
        ]

    def __str__(self) -> str:
        return self.number


class HandoverDestination(models.TextChoices):
    NEXT_SHIFT = "next_shift", "Next shift"
    SAFE = "safe", "Safe"
    BANK_DEPOSIT = "bank_deposit", "Bank deposit"
    SUPERVISOR = "supervisor", "Supervisor"


@track_history()
class CashHandover(models.Model):
    """Cash leaving a shift's drawer: to the next shift, the safe or the bank (FEATURES 7.6)."""

    number = models.CharField(max_length=30, unique=True)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="handovers_out")
    destination = models.CharField(max_length=20, choices=HandoverDestination.choices)
    to_shift = models.ForeignKey(
        Shift, on_delete=models.PROTECT, null=True, blank=True, related_name="handovers_in"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    amount = money_field()
    bank_reference = models.CharField(max_length=100, blank=True)
    handed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    handed_at = models.DateTimeField()
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_note = models.CharField(max_length=500, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "cash handover"
        ordering: ClassVar[list[str]] = ["-handed_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("destination", HandoverDestination, "payments_handover_dest_valid"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payments_handover_positive"),
            models.CheckConstraint(
                condition=~Q(destination=HandoverDestination.NEXT_SHIFT)
                | Q(to_shift__isnull=False),
                name="payments_handover_next_shift_named",
            ),
            models.CheckConstraint(
                condition=~Q(to_shift=F("shift")), name="payments_handover_not_to_itself"
            ),
            models.CheckConstraint(
                condition=Q(received_at__isnull=True) | Q(received_by__isnull=False),
                name="payments_handover_receipt_documented",
            ),
            models.CheckConstraint(
                condition=Q(cancelled_at__isnull=True)
                | (
                    Q(cancelled_by__isnull=False) & ~Q(cancel_note="") & Q(received_at__isnull=True)
                ),
                name="payments_handover_cancel_documented",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            shift_must_be_open(),
            shift_must_be_open(name="to_shift_must_be_open", column="to_shift_id"),
            pgtrigger.Trigger(
                name="handover_guard",
                when=pgtrigger.Before,
                operation=pgtrigger.Update | pgtrigger.Delete,
                func="""
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'HANDOVER_PERMANENT: handover % is never deleted', OLD.id;
                    END IF;
                    IF ROW(NEW.number, NEW.shift_id, NEW.destination, NEW.to_shift_id,
                           NEW.to_user_id, NEW.amount, NEW.bank_reference, NEW.handed_by_id,
                           NEW.handed_at)
                       IS DISTINCT FROM
                       ROW(OLD.number, OLD.shift_id, OLD.destination, OLD.to_shift_id,
                           OLD.to_user_id, OLD.amount, OLD.bank_reference, OLD.handed_by_id,
                           OLD.handed_at) THEN
                        RAISE EXCEPTION 'HANDOVER_READONLY: handover % never changes', OLD.id;
                    END IF;
                    IF ROW(NEW.received_at, NEW.received_by_id)
                       IS DISTINCT FROM ROW(OLD.received_at, OLD.received_by_id) THEN
                        IF OLD.received_at IS NOT NULL OR OLD.cancelled_at IS NOT NULL THEN
                            RAISE EXCEPTION 'HANDOVER_FINAL: handover % is already settled',
                                OLD.id;
                        END IF;
                        IF NEW.to_shift_id IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM payments_shift s
                             WHERE s.id = NEW.to_shift_id AND s.status = 'open'
                        ) THEN
                            RAISE EXCEPTION 'SHIFT_NOT_OPEN: shift % is not open (table %)',
                                NEW.to_shift_id, TG_TABLE_NAME;
                        END IF;
                    END IF;
                    IF ROW(NEW.cancelled_at, NEW.cancelled_by_id, NEW.cancel_note)
                       IS DISTINCT FROM ROW(OLD.cancelled_at, OLD.cancelled_by_id, OLD.cancel_note)
                    THEN
                        IF OLD.received_at IS NOT NULL OR OLD.cancelled_at IS NOT NULL THEN
                            RAISE EXCEPTION 'HANDOVER_FINAL: handover % is already settled',
                                OLD.id;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM payments_shift s
                             WHERE s.id = OLD.shift_id AND s.status = 'open'
                        ) THEN
                            RAISE EXCEPTION 'SHIFT_NOT_OPEN: shift % is not open (table %)',
                                OLD.shift_id, TG_TABLE_NAME;
                        END IF;
                    END IF;
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                """,
            ),
        ]

    def __str__(self) -> str:
        return self.number
