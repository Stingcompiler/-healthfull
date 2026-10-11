"""Payer claims, responses and payer payments (FEATURES 11, invariant 7).

The payer share of an approved invoice line is a receivable (AR_PAYER) that travels:
due -> claimed (``ClaimLine``) -> accepted / rejected / partial -> collected
(``PayerPaymentAllocation``). A rejected amount is rebilled to the patient or written off,
both with approver and reason. Reports never show payer share as collected cash until a
``PayerPayment`` is allocated.

Database backstops: a claim line of a closed or void claim never changes; claim lines are
never deleted; a line's invoice line and claimed amount never change; its status moves only
from ``pending`` (to an answer, or ``withdrawn`` while the claim is open), or
from an answer to ``withdrawn`` when nothing was collected, resolved or written off on it (a
credit note took its payer share back); a withdrawal records who, when and why; a resolution
or a short-payment write-off is recorded once. A new claim line may claim no more
than the invoice line's payer share less what approved credit notes took back.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import (
    ZERO,
    append_only,
    choice_check,
    money_field,
    protect_when,
    shift_must_be_open,
    track_history,
    truncate_guard,
)
from domain.payments import normalize_reference


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
    resolution_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="The second person who approved the rebill or write-off (ADR 0018).",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    withdraw_note = models.CharField(max_length=500, blank=True)
    written_off_amount = money_field(
        default=ZERO, help_text="Accepted amount the payer short-paid, written off."
    )
    written_off_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "writeoff"},
    )
    written_off_note = models.TextField(blank=True)
    written_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    written_off_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="The second person who approved the short-payment write-off (ADR 0018).",
    )
    written_off_at = models.DateTimeField(null=True, blank=True)

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
            # ADR 0018: the approver of a rebill or write-off is never its recorder.
            models.CheckConstraint(
                condition=Q(resolution_approved_by__isnull=True)
                | ~Q(resolution_approved_by=F("resolved_by")),
                name="claims_line_resolution_second_person",
            ),
            models.CheckConstraint(
                condition=Q(written_off_approved_by__isnull=True)
                | ~Q(written_off_approved_by=F("written_off_by")),
                name="claims_line_write_off_second_person",
            ),
            models.UniqueConstraint(
                fields=["invoice_line"],
                condition=~Q(status=ClaimLineStatus.WITHDRAWN),
                name="claims_line_invoice_line_claimed_once",
            ),
            # Invariant 4: a withdrawal records who withdrew the line, when and why.
            models.CheckConstraint(
                condition=~Q(status=ClaimLineStatus.WITHDRAWN)
                | (
                    Q(withdrawn_at__isnull=False, withdrawn_by__isnull=False) & ~Q(withdraw_note="")
                ),
                name="claims_line_withdrawal_documented",
            ),
            # Invariant 4: a short-payment write-off records reason, approver and time.
            models.CheckConstraint(
                condition=Q(written_off_amount=0)
                | (
                    Q(written_off_amount__gt=0)
                    & Q(status__in=[ClaimLineStatus.ACCEPTED, ClaimLineStatus.PARTIAL])
                    & Q(written_off_amount__lte=F("accepted_amount"))
                    & Q(
                        written_off_reason__isnull=False,
                        written_off_by__isnull=False,
                        written_off_at__isnull=False,
                    )
                ),
                name="claims_line_write_off_documented",
            ),
            models.CheckConstraint(
                condition=Q(written_off_amount__gte=0), name="claims_line_write_off_non_negative"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "resolution"], name="claims_line_status_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            pgtrigger.Trigger(
                name="claim_line_guard",
                when=pgtrigger.Before,
                operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
                declare=[("claim_status", "text")],
                func="""
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'CLAIM_LINE_PERMANENT: claim line % is never deleted',
                            OLD.id;
                    END IF;
                    SELECT k.status INTO claim_status FROM claims_claim k WHERE k.id = NEW.claim_id;
                    IF TG_OP = 'INSERT' THEN
                        IF claim_status <> 'draft' OR NEW.status <> 'pending' THEN
                            RAISE EXCEPTION
                                'CLAIM_STATUS_INVALID: lines join a draft claim as pending';
                        END IF;
                        IF NEW.amount_claimed > (
                            SELECT il.payer_share - coalesce((
                                SELECT sum(cl.payer_share) FROM billing_creditnoteline cl
                                  JOIN billing_creditnote cn ON cn.id = cl.credit_note_id
                                 WHERE cl.invoice_line_id = il.id AND cn.status = 'approved'
                            ), 0)
                              FROM billing_invoiceline il
                             WHERE il.id = NEW.invoice_line_id AND il.frozen
                        ) IS NOT FALSE THEN
                            RAISE EXCEPTION
                                'CLAIM_LINE_NOT_ACCRUED: claim line claims more than is accrued';
                        END IF;
                        RETURN NEW;
                    END IF;
                    IF claim_status IN ('closed', 'void') THEN
                        RAISE EXCEPTION 'CLAIM_FINAL: claim line % of a % claim never changes',
                            OLD.id, claim_status;
                    END IF;
                    IF NEW.claim_id IS DISTINCT FROM OLD.claim_id
                       OR NEW.invoice_line_id IS DISTINCT FROM OLD.invoice_line_id
                       OR NEW.amount_claimed IS DISTINCT FROM OLD.amount_claimed THEN
                        RAISE EXCEPTION 'CLAIM_LINE_READONLY: claim line % claims a fixed amount',
                            OLD.id;
                    END IF;
                    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                        (OLD.status = 'pending' AND (
                            NEW.status IN ('accepted', 'rejected', 'partial')
                            OR (NEW.status = 'withdrawn'
                                AND claim_status IN ('draft', 'submitted', 'responded'))
                        ))
                        -- An answered line nothing was collected or resolved on is withdrawn
                        -- when a credit note takes its whole payer share back.
                        OR (OLD.status IN ('accepted', 'rejected', 'partial')
                            AND NEW.status = 'withdrawn'
                            AND OLD.resolution = 'none' AND OLD.written_off_amount = 0
                            AND coalesce((
                                SELECT sum(a.amount) FROM claims_payerpaymentallocation a
                                 WHERE a.claim_line_id = OLD.id), 0) = 0)
                    ) THEN
                        RAISE EXCEPTION 'CLAIM_LINE_TRANSITION: claim line % cannot go from % to %',
                            OLD.id, OLD.status, NEW.status;
                    END IF;
                    IF OLD.status <> 'pending' AND (
                        NEW.accepted_amount IS DISTINCT FROM OLD.accepted_amount
                        OR NEW.rejected_amount IS DISTINCT FROM OLD.rejected_amount) THEN
                        RAISE EXCEPTION 'CLAIM_LINE_READONLY: the payer answer of % is recorded',
                            OLD.id;
                    END IF;
                    IF OLD.resolution <> 'none'
                       AND NEW.resolution IS DISTINCT FROM OLD.resolution THEN
                        RAISE EXCEPTION 'CLAIM_LINE_READONLY: the rejection of % is resolved',
                            OLD.id;
                    END IF;
                    IF OLD.written_off_amount > 0
                       AND NEW.written_off_amount < OLD.written_off_amount THEN
                        RAISE EXCEPTION 'CLAIM_LINE_READONLY: a write-off of % is final', OLD.id;
                    END IF;
                    RETURN NEW;
                """,
            ),
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
    reference_norm = models.CharField(
        max_length=200,
        blank=True,
        editable=False,
        help_text="``domain.payments.normalize_reference(reference)``, written by the service.",
    )
    received_on = models.DateField()
    shift = models.ForeignKey(
        "payments.Shift",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payer_payments",
        help_text="Payer cash goes into the recording cashier's open shift.",
    )
    cleared_at = models.DateTimeField(null=True, blank=True, help_text="A cheque cleared.")
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reverse_note = models.TextField(blank=True)
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
            models.CheckConstraint(
                condition=~Q(method=PayerPaymentMethod.CASH) | Q(shift__isnull=False),
                name="claims_payerpayment_cash_in_shift",
            ),
            models.CheckConstraint(
                condition=Q(cleared_at__isnull=True)
                | (Q(method=PayerPaymentMethod.CHEQUE) & Q(cleared_by__isnull=False)),
                name="claims_payerpayment_clearing_documented",
            ),
            models.CheckConstraint(
                condition=Q(reversed_at__isnull=True)
                | (
                    ~Q(method=PayerPaymentMethod.CASH)
                    & Q(reversed_by__isnull=False)
                    & ~Q(reverse_note="")
                ),
                name="claims_payerpayment_reversal_documented",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            pgtrigger.ReadOnly(
                name="payer_payment_money_readonly",
                fields=[
                    "number",
                    "payer",
                    "amount",
                    "method",
                    "bank",
                    "reference",
                    "reference_norm",
                    "received_on",
                    "shift",
                ],
            ),
            protect_when(
                "payer_payment_reversed_final",
                code="PAYMENT_PERMANENT",
                message="a reversed payer payment never changes",
                condition=pgtrigger.Q(old__reversed_at__isnull=False),
                operation=pgtrigger.Update,
            ),
            shift_must_be_open(),
            protect_when(
                "payer_payment_no_delete",
                code="PAYMENT_PERMANENT",
                message="payer payments are never deleted",
                operation=pgtrigger.Delete,
            ),
        ]

    def __str__(self) -> str:
        return self.number

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Write ``reference_norm`` from the one Python definition of a reference's canonical
        form (``domain.payments.normalize_reference``), so the unique index and duplicate
        lookups compare exactly what the domain compares."""
        self.reference_norm = normalize_reference(self.reference) if True else ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "reference" in update_fields:
            kwargs["update_fields"] = {*update_fields, "reference_norm"}
        super().save(*args, **kwargs)


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
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            append_only(),
        ]

    def __str__(self) -> str:
        return f"{self.payer_payment_id} -> {self.claim_line_id or self.claim_id}: {self.amount}"
