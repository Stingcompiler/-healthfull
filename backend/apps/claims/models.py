"""Payer claims, responses and payer payments (FEATURES 11, invariant 7).

The payer share of an approved invoice line is a receivable (AR_PAYER) that travels:
due -> claimed (``ClaimLine``) -> accepted / rejected / partial -> collected
(``PayerPaymentAllocation``). A rejected amount is rebilled to the patient or written off,
both with approver and reason. Reports never show payer share as collected cash until a
``PayerPayment`` is allocated.
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import (
    ZERO,
    NormalizeReference,
    append_only,
    choice_check,
    money_field,
    protect_when,
    track_history,
)


class ClaimStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    RESPONDED = "responded", "Response recorded"
    CLOSED = "closed", "Closed"
    VOID = "void", "Void"


@track_history()
class Claim(models.Model):
    """A claim batch for one payer and one period (FEATURES 11.3)."""

    number = models.CharField(max_length=30, unique=True)
    payer = models.ForeignKey("catalog.Payer", on_delete=models.PROTECT, related_name="claims")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=ClaimStatus.choices, default=ClaimStatus.DRAFT)
    claimed_total = money_field(default=ZERO)
    accepted_total = money_field(default=ZERO)
    rejected_total = money_field(default=ZERO)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    response_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "claim"
        ordering: ClassVar[list[str]] = ["-period_end", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", ClaimStatus, "claims_claim_status_valid"),
            models.CheckConstraint(
                condition=Q(period_end__gte=F("period_start")), name="claims_claim_period_order"
            ),
            models.CheckConstraint(
                condition=Q(claimed_total__gte=0)
                & Q(accepted_total__gte=0)
                & Q(rejected_total__gte=0),
                name="claims_claim_totals_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(accepted_total__lte=F("claimed_total") - F("rejected_total")),
                name="claims_claim_totals_within_claimed",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[ClaimStatus.DRAFT, ClaimStatus.VOID])
                | Q(submitted_by__isnull=False, submitted_at__isnull=False),
                name="claims_claim_submission_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["payer", "status"], name="claims_claim_payer_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "claim_final",
                code="CLAIM_FINAL",
                message="closed or void claims never change",
                condition=pgtrigger.Q(old__status__in=["closed", "void"]),
            ),
        ]

    def __str__(self) -> str:
        return self.number


class ClaimLineStatus(models.TextChoices):
    PENDING = "pending", "Awaiting response"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    PARTIAL = "partial", "Partially accepted"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Resolution(models.TextChoices):
    NONE = "none", "Not resolved"
    REBILLED = "rebilled", "Rebilled to the patient"
    WRITTEN_OFF = "written_off", "Written off"


@track_history()
class ClaimLine(models.Model):
    """The payer share of one frozen invoice line, as claimed and answered (FEATURES 11.4-11.5)."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(
        "billing.InvoiceLine", on_delete=models.PROTECT, related_name="claim_lines"
    )
    amount_claimed = money_field()
    status = models.CharField(
        max_length=20, choices=ClaimLineStatus.choices, default=ClaimLineStatus.PENDING
    )
    accepted_amount = money_field(default=ZERO)
    rejected_amount = money_field(default=ZERO)
    payer_reason = models.CharField(max_length=300, blank=True)
    payer_reference = models.CharField(max_length=100, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    resolution = models.CharField(
        max_length=20, choices=Resolution.choices, default=Resolution.NONE
    )
    resolution_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "writeoff"},
    )
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "claim line"
        ordering: ClassVar[list[str]] = ["claim", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", ClaimLineStatus, "claims_line_status_valid"),
            choice_check("resolution", Resolution, "claims_line_resolution_valid"),
            models.CheckConstraint(
                condition=Q(amount_claimed__gt=0)
                & Q(accepted_amount__gte=0)
                & Q(rejected_amount__gte=0),
                name="claims_line_amounts_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[ClaimLineStatus.PENDING, ClaimLineStatus.WITHDRAWN])
                | Q(accepted_amount=F("amount_claimed") - F("rejected_amount")),
                name="claims_line_response_adds_up",
            ),
            models.CheckConstraint(
                condition=~Q(status=ClaimLineStatus.ACCEPTED) | Q(rejected_amount=0),
                name="claims_line_accepted_has_no_rejection",
            ),
            models.CheckConstraint(
                condition=~Q(status=ClaimLineStatus.REJECTED) | Q(accepted_amount=0),
                name="claims_line_rejected_has_no_acceptance",
            ),
            models.CheckConstraint(
                condition=~Q(status=ClaimLineStatus.PARTIAL)
                | (Q(accepted_amount__gt=0) & Q(rejected_amount__gt=0)),
                name="claims_line_partial_has_both",
            ),
            # Invariant 4: rebill and write-off record reason, approver and time.
            models.CheckConstraint(
                condition=Q(resolution=Resolution.NONE)
                | (
                    Q(rejected_amount__gt=0)
                    & Q(
                        resolution_reason__isnull=False,
                        resolved_by__isnull=False,
                        resolved_at__isnull=False,
                    )
                ),
                name="claims_line_resolution_documented",
            ),
            models.UniqueConstraint(
                fields=["invoice_line"],
                condition=~Q(status=ClaimLineStatus.WITHDRAWN),
                name="claims_line_invoice_line_claimed_once",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "resolution"], name="claims_line_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.claim_id}: {self.invoice_line_id} {self.amount_claimed}"


class PayerPaymentMethod(models.TextChoices):
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    CHEQUE = "cheque", "Cheque"
    CASH = "cash", "Cash"


@track_history(exclude=["reference_norm"])
class PayerPayment(models.Model):
    """Money received from a payer (FEATURES 11.6): the only thing that turns AR_PAYER to cash."""

    number = models.CharField(max_length=30, unique=True)
    payer = models.ForeignKey("catalog.Payer", on_delete=models.PROTECT, related_name="payments")
    amount = money_field()
    method = models.CharField(
        max_length=20, choices=PayerPaymentMethod.choices, default=PayerPaymentMethod.BANK_TRANSFER
    )
    bank = models.ForeignKey(
        "payments.Bank",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payer_payments",
    )
    reference = models.CharField(max_length=100, blank=True)
    reference_norm = models.GeneratedField(
        expression=NormalizeReference(F("reference")),
        output_field=models.TextField(),
        db_persist=True,
    )
    received_on = models.DateField()
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "payer payment"
        ordering: ClassVar[list[str]] = ["-received_on", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("method", PayerPaymentMethod, "claims_payerpayment_method_valid"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="claims_payerpayment_positive"),
            models.CheckConstraint(
                condition=~Q(method=PayerPaymentMethod.BANK_TRANSFER)
                | (Q(bank__isnull=False) & ~Q(reference="")),
                name="claims_payerpayment_transfer_has_reference",
            ),
            models.UniqueConstraint(
                fields=["bank", "reference_norm"],
                condition=Q(bank__isnull=False) & ~Q(reference=""),
                name="claims_payerpayment_reference_unique",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.ReadOnly(
                name="payer_payment_money_readonly",
                fields=["number", "payer", "amount", "method", "bank", "reference", "received_on"],
            ),
            protect_when(
                "payer_payment_no_delete",
                code="PAYMENT_PERMANENT",
                message="payer payments are never deleted",
                operation=pgtrigger.Delete,
            ),
        ]

    def __str__(self) -> str:
        return self.number


class PayerPaymentAllocation(models.Model):
    """Part of a payer payment applied to a claim line. Append-only (reversal = negative row)."""

    payer_payment = models.ForeignKey(
        PayerPayment, on_delete=models.PROTECT, related_name="allocations"
    )
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="payer_allocations")
    claim_line = models.ForeignKey(
        ClaimLine, on_delete=models.PROTECT, null=True, blank=True, related_name="allocations"
    )
    amount = money_field()
    reversal_of = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "payer payment allocation"
        ordering: ClassVar[list[str]] = ["created_at", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(Q(reversal_of__isnull=True) & Q(amount__gt=0))
                | (Q(reversal_of__isnull=False) & Q(amount__lt=0)),
                name="claims_payeralloc_amount_sign",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [append_only()]

    def __str__(self) -> str:
        return f"{self.payer_payment_id} -> {self.claim_line_id or self.claim_id}: {self.amount}"
