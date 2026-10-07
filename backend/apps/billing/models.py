"""Invoices and credit notes (ARCHITECTURE 4.5, invariants 2 and 6).

* An invoice is built only from the visit's ``unbilled`` service lines. At approval every line
  freezes its price (from the ``PriceListVersion`` effective that day), quantity, gross,
  discount, payer and shares, and the invoice gets its number.
* Approved and void invoices, frozen lines, and approved credit notes and their lines can
  never be updated or deleted (DB triggers). No line can be added to a non-draft document.
* A deferred (commit-time) trigger refuses to commit an approved invoice or credit note whose
  lines are not all frozen, that has no lines, or whose header totals differ from its lines.
  It also refuses credit notes that credit more than the invoice line holds.
* Corrections are credit notes linked to the original invoice lines.
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round

from apps.catalog.models import ServiceKind
from apps.core.db import (
    ZERO,
    choice_check,
    money_field,
    parent_must_be_editable,
    protect_when,
    quantity_field,
    track_history,
)


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    VOID = "void", "Void"


def _totals_constraints(prefix: str) -> list[models.BaseConstraint]:
    return [
        models.CheckConstraint(
            condition=Q(gross_total__gte=0)
            & Q(discount_total__gte=0)
            & Q(payer_total__gte=0)
            & Q(patient_total__gte=0),
            name=f"{prefix}_totals_non_negative",
        ),
        models.CheckConstraint(
            condition=Q(patient_total=F("gross_total") - F("discount_total") - F("payer_total")),
            name=f"{prefix}_totals_balance",
        ),
    ]


def _shares_constraints(prefix: str) -> list[models.BaseConstraint]:
    return [
        models.CheckConstraint(condition=Q(quantity__gt=0), name=f"{prefix}_qty_positive"),
        models.CheckConstraint(
            condition=Q(gross__gte=0)
            & Q(discount__gte=0)
            & Q(payer_share__gte=0)
            & Q(patient_share__gte=0),
            name=f"{prefix}_amounts_non_negative",
        ),
        models.CheckConstraint(
            condition=Q(patient_share=F("gross") - F("discount") - F("payer_share")),
            name=f"{prefix}_shares_balance",
        ),
    ]


def _consistency_sql(*, document: str, lines_table: str, fk: str, extra: str = "") -> str:
    # Trigger DDL built at import time from code constants, never from user input.
    return f"""
        SELECT count(*), count(*) FILTER (WHERE NOT l.frozen),
               coalesce(sum(l.gross), 0), coalesce(sum(l.discount), 0),
               coalesce(sum(l.payer_share), 0), coalesce(sum(l.patient_share), 0)
          INTO n_lines, n_unfrozen, s_gross, s_discount, s_payer, s_patient
          FROM {lines_table} l WHERE l.{fk} = NEW.id;
        IF n_lines = 0 THEN
            RAISE EXCEPTION '{document}_EMPTY: approved % has no lines', NEW.id;
        END IF;
        IF n_unfrozen > 0 THEN
            RAISE EXCEPTION '{document}_LINES_NOT_FROZEN: approved % has % unfrozen lines',
                NEW.id, n_unfrozen;
        END IF;
        IF s_gross <> NEW.gross_total OR s_discount <> NEW.discount_total
           OR s_payer <> NEW.payer_total OR s_patient <> NEW.patient_total THEN
            RAISE EXCEPTION '{document}_TOTALS_MISMATCH: totals of % differ from its lines',
                NEW.id;
        END IF;
        {extra}
        RETURN NULL;
    """  # noqa: S608


_CONSISTENCY_DECLARE = [
    ("n_lines", "integer"),
    ("n_unfrozen", "integer"),
    ("s_gross", "numeric"),
    ("s_discount", "numeric"),
    ("s_payer", "numeric"),
    ("s_patient", "numeric"),
]

# Credited amounts per invoice line, over every approved credit note, never exceed the line.
_OVER_CREDIT_SQL = """
        IF EXISTS (
            SELECT 1
              FROM billing_creditnoteline cl
              JOIN billing_invoiceline il ON il.id = cl.invoice_line_id
             WHERE cl.invoice_line_id IN (
                       SELECT x.invoice_line_id FROM billing_creditnoteline x
                        WHERE x.credit_note_id = NEW.id)
               AND cl.frozen
             GROUP BY il.id, il.quantity, il.gross, il.discount, il.payer_share, il.patient_share
            HAVING sum(cl.quantity) > il.quantity OR sum(cl.gross) > il.gross
                OR sum(cl.discount) > il.discount OR sum(cl.payer_share) > il.payer_share
                OR sum(cl.patient_share) > il.patient_share
        ) THEN
            RAISE EXCEPTION 'CREDIT_EXCEEDS_INVOICE: credit note % credits more than invoiced',
                NEW.id;
        END IF;
        IF EXISTS (
            SELECT 1 FROM billing_creditnoteline cl
              JOIN billing_invoiceline il ON il.id = cl.invoice_line_id
             WHERE cl.credit_note_id = NEW.id AND il.invoice_id <> NEW.invoice_id
        ) THEN
            RAISE EXCEPTION 'CREDIT_WRONG_INVOICE: credit note % credits another invoice', NEW.id;
        END IF;
"""


def _consistency_trigger(name: str, sql: str) -> pgtrigger.Trigger:
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.After,
        operation=pgtrigger.Insert | pgtrigger.Update,
        timing=pgtrigger.Deferred,
        condition=pgtrigger.Q(new__status="approved"),
        declare=_CONSISTENCY_DECLARE,
        func=sql,
    )


@track_history()
class Invoice(models.Model):
    number = models.CharField(
        max_length=30, unique=True, null=True, blank=True, help_text="Assigned at approval."
    )
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="invoices")
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="invoices"
    )
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT
    )
    priced_on = models.DateField(
        null=True, blank=True, help_text="Date whose price list versions priced the lines."
    )
    gross_total = money_field(default=ZERO)
    discount_total = money_field(default=ZERO)
    payer_total = money_field(default=ZERO)
    patient_total = money_field(default=ZERO)
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "invoice"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", DocumentStatus, "billing_invoice_status_valid"),
            *_totals_constraints("billing_invoice"),
            models.CheckConstraint(
                condition=~Q(status=DocumentStatus.APPROVED)
                | Q(
                    number__isnull=False,
                    approved_by__isnull=False,
                    approved_at__isnull=False,
                    priced_on__isnull=False,
                ),
                name="billing_invoice_approval_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=DocumentStatus.VOID)
                | (Q(voided_by__isnull=False, voided_at__isnull=False) & ~Q(void_note="")),
                name="billing_invoice_void_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["visit", "status"], name="billing_invoice_visit_idx"),
            models.Index(fields=["patient", "status"], name="billing_invoice_patient_idx"),
            models.Index(fields=["status", "approved_at"], name="billing_invoice_approved_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "invoice_frozen",
                code="INVOICE_FROZEN",
                message="approved or void invoices never change",
                condition=pgtrigger.Q(old__status__in=["approved", "void"]),
            ),
            _consistency_trigger(
                "invoice_consistent",
                _consistency_sql(
                    document="INVOICE", lines_table="billing_invoiceline", fk="invoice_id"
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.number or f"draft invoice {self.pk}"


@track_history()
class InvoiceLine(models.Model):
    """One service line on an invoice. Every money field is frozen at approval."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    service_line = models.ForeignKey(
        "orders.ServiceLine", on_delete=models.PROTECT, related_name="invoice_lines"
    )
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=ServiceKind.choices)
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    description_ar = models.CharField(max_length=200)
    description_en = models.CharField(max_length=200)
    price_list_version = models.ForeignKey(
        "catalog.PriceListVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    quantity = quantity_field()
    unit_price = money_field()
    gross = money_field()
    discount = money_field(default=ZERO)
    discount_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "discount"},
    )
    discount_note = models.CharField(max_length=500, blank=True)
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    payer = models.ForeignKey(
        "catalog.Payer", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    coverage_rule = models.ForeignKey(
        "catalog.CoverageRule",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    excluded = models.BooleanField(
        default=False, help_text="A payer exclusion routed this line 100% to the patient."
    )
    payer_share = money_field(default=ZERO)
    patient_share = money_field(default=ZERO)
    pre_approval_ref = models.CharField(max_length=100, blank=True)
    frozen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "invoice line"
        ordering: ClassVar[list[str]] = ["invoice", "line_no"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", ServiceKind, "billing_invoiceline_kind_valid"),
            *_shares_constraints("billing_invoiceline"),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="billing_invoiceline_price_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(gross=Round(F("quantity") * F("unit_price"), 2)),
                name="billing_invoiceline_gross_is_qty_times_price",
            ),
            models.CheckConstraint(
                condition=Q(payer__isnull=False) | Q(payer_share=0),
                name="billing_invoiceline_cash_has_no_payer_share",
            ),
            # Invariant 4: a discount records reason and approver.
            models.CheckConstraint(
                condition=Q(discount=0)
                | Q(discount_reason__isnull=False, discount_approved_by__isnull=False),
                name="billing_invoiceline_discount_documented",
            ),
            # Invariant 6: a frozen line knows which price list version priced it.
            models.CheckConstraint(
                condition=Q(frozen=False) | Q(price_list_version__isnull=False),
                name="billing_invoiceline_frozen_has_price_version",
            ),
            models.UniqueConstraint(
                fields=["invoice", "line_no"], name="billing_invoiceline_line_no_unique"
            ),
            models.UniqueConstraint(
                fields=["service_line"],
                condition=Q(frozen=True),
                name="billing_invoiceline_service_line_billed_once",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["payer", "frozen"], name="billing_invline_payer_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "line_frozen",
                code="INVOICE_FROZEN",
                message="frozen invoice lines never change",
                condition=pgtrigger.Q(old__frozen=True),
            ),
            parent_must_be_editable(
                "line_needs_draft_invoice",
                code="INVOICE_FROZEN",
                parent_table="billing_invoice",
                fk_column="invoice_id",
                editable_condition="p.status = 'draft'",
                operation=pgtrigger.Insert,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id}#{self.line_no}"


@track_history()
class CreditNote(models.Model):
    """A correction of an approved invoice (FEATURES 5.11, invariant 2).

    Amounts on the credit note and its lines are positive numbers: what is taken back.
    """

    number = models.CharField(
        max_length=30, unique=True, null=True, blank=True, help_text="Assigned at approval."
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="credit_notes"
    )
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT
    )
    reason_code = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"category": "credit_note"},
    )
    reason_note = models.TextField(blank=True)
    gross_total = money_field(default=ZERO)
    discount_total = money_field(default=ZERO)
    payer_total = money_field(default=ZERO)
    patient_total = money_field(default=ZERO)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "credit note"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", DocumentStatus, "billing_creditnote_status_valid"),
            *_totals_constraints("billing_creditnote"),
            models.CheckConstraint(
                condition=~Q(status=DocumentStatus.APPROVED)
                | Q(number__isnull=False, approved_by__isnull=False, approved_at__isnull=False),
                name="billing_creditnote_approval_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=DocumentStatus.VOID)
                | (Q(voided_by__isnull=False, voided_at__isnull=False) & ~Q(void_note="")),
                name="billing_creditnote_void_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["invoice", "status"], name="billing_cn_invoice_idx"),
            models.Index(fields=["patient", "status"], name="billing_cn_patient_idx"),
            models.Index(fields=["status", "approved_at"], name="billing_cn_approved_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "credit_note_frozen",
                code="CREDIT_NOTE_FROZEN",
                message="approved or void credit notes never change",
                condition=pgtrigger.Q(old__status__in=["approved", "void"]),
            ),
            _consistency_trigger(
                "credit_note_consistent",
                _consistency_sql(
                    document="CREDIT_NOTE",
                    lines_table="billing_creditnoteline",
                    fk="credit_note_id",
                    extra=_OVER_CREDIT_SQL,
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.number or f"draft credit note {self.pk}"


@track_history()
class CreditNoteLine(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    invoice_line = models.ForeignKey(
        InvoiceLine, on_delete=models.PROTECT, related_name="credit_lines"
    )
    quantity = quantity_field()
    gross = money_field()
    discount = money_field(default=ZERO)
    payer_share = money_field(default=ZERO)
    patient_share = money_field(default=ZERO)
    cancels_service_line = models.BooleanField(
        default=False, help_text="The credited service line is also cancelled (not performed)."
    )
    frozen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "credit note line"
        ordering: ClassVar[list[str]] = ["credit_note", "line_no"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            *_shares_constraints("billing_creditnoteline"),
            models.UniqueConstraint(
                fields=["credit_note", "line_no"], name="billing_creditnoteline_line_no_unique"
            ),
            models.UniqueConstraint(
                fields=["credit_note", "invoice_line"],
                name="billing_creditnoteline_invoice_line_once",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "line_frozen",
                code="CREDIT_NOTE_FROZEN",
                message="frozen credit note lines never change",
                condition=pgtrigger.Q(old__frozen=True),
            ),
            parent_must_be_editable(
                "line_needs_draft_credit_note",
                code="CREDIT_NOTE_FROZEN",
                parent_table="billing_creditnote",
                fk_column="credit_note_id",
                editable_condition="p.status = 'draft'",
                operation=pgtrigger.Insert,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_id}#{self.line_no}"
