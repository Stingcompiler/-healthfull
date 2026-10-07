"""Append-only double-entry money ledger (ARCHITECTURE 4.7).

The chart of accounts is fixed (``domain/ledger.py``, ``apps.ledger.chart``) and seeded by
migration ``0003_seed_accounts``; account codes never change and accounts are never deleted.

Every posting is one balanced ``JournalEntry`` with ``source_type``/``source_id`` pointing at
the business document. Database backstops:

* ``JournalEntry`` and ``JournalLine`` are append-only: corrections are new entries
  (``reversal_of`` for a full reversal).
* A commit-time (deferred) trigger refuses any entry with fewer than two lines or with
  debits different from credits.
* Each line is a debit or a credit, never both, never zero, and carries the dimension its
  account needs (patient for AR_PATIENT/PATIENT_CREDIT, payer for AR_PAYER/WRITE_OFF, shift for
  CASH/CASH_OVER_SHORT).
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import ServiceKind
from apps.core.db import ZERO, append_only, choice_check, money_field, protect_when, track_history


class AccountKind(models.TextChoices):
    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    REVENUE = "revenue", "Revenue"
    CONTRA_REVENUE = "contra_revenue", "Contra revenue"
    EXPENSE = "expense", "Expense"


class NormalBalance(models.TextChoices):
    DEBIT = "debit", "Debit"
    CREDIT = "credit", "Credit"


@track_history()
class Account(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=AccountKind.choices)
    normal_balance = models.CharField(max_length=10, choices=NormalBalance.choices)
    sort_order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ledger account"
        ordering: ClassVar[list[str]] = ["sort_order", "code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", AccountKind, "ledger_account_kind_valid"),
            choice_check("normal_balance", NormalBalance, "ledger_account_balance_valid"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.ReadOnly(
                name="account_code_fixed", fields=["code", "kind", "normal_balance"]
            ),
            protect_when(
                "account_no_delete",
                code="ACCOUNT_FIXED",
                message="the chart of accounts is fixed",
                operation=pgtrigger.Delete,
            ),
        ]

    def __str__(self) -> str:
        return self.code


class SourceType(models.TextChoices):
    INVOICE = "invoice", "Invoice approved"
    CREDIT_NOTE = "credit_note", "Credit note approved"
    PAYMENT = "payment", "Payment received"
    ALLOCATION = "allocation", "Payment allocated"
    TRANSFER_CONFIRM = "transfer_confirm", "Transfer confirmed"
    TRANSFER_REJECT = "transfer_reject", "Transfer rejected"
    REFUND = "refund", "Refund paid"
    SHIFT_OPEN = "shift_open", "Shift opening float"
    SHIFT_CLOSE = "shift_close", "Shift close variance"
    HANDOVER = "handover", "Cash handover"
    CLAIM_REBILL = "claim_rebill", "Payer rejection rebilled to patient"
    CLAIM_WRITEOFF = "claim_writeoff", "Payer rejection written off"
    PAYER_PAYMENT = "payer_payment", "Payer payment received"


_BALANCE_SQL = """
    SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0)
      INTO n_lines, s_debit, s_credit
      FROM ledger_journalline WHERE entry_id = {entry};
    IF n_lines < 2 OR s_debit <> s_credit THEN
        RAISE EXCEPTION
            'JOURNAL_UNBALANCED: entry % has % lines, debits % and credits %',
            {entry}, n_lines, s_debit, s_credit;
    END IF;
    RETURN NULL;
"""

_BALANCE_DECLARE = [("n_lines", "integer"), ("s_debit", "numeric"), ("s_credit", "numeric")]


def _balanced(name: str, entry: str) -> pgtrigger.Trigger:
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.After,
        operation=pgtrigger.Insert,
        timing=pgtrigger.Deferred,
        declare=_BALANCE_DECLARE,
        func=_BALANCE_SQL.format(entry=entry),
    )


class JournalEntry(models.Model):
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    source_id = models.BigIntegerField()
    entry_date = models.DateField()
    shift = models.ForeignKey(
        "payments.Shift",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entries",
        help_text="Shift the effect belongs to (the acting user's current shift for late effects).",
    )
    reversal_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals"
    )
    memo = models.CharField(max_length=300, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "journal entry"
        verbose_name_plural = "journal entries"
        ordering: ClassVar[list[str]] = ["-posted_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("source_type", SourceType, "ledger_entry_source_type_valid"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["source_type", "source_id"], name="ledger_entry_source_idx"),
            models.Index(fields=["entry_date"], name="ledger_entry_date_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            append_only(),
            _balanced("entry_balanced", "NEW.id"),
        ]

    def __str__(self) -> str:
        return f"JE {self.pk} {self.source_type}:{self.source_id}"


_DIMENSIONS_SQL = """
    SELECT a.code INTO account_code FROM ledger_account a WHERE a.id = NEW.account_id;
    IF account_code IN ('AR_PATIENT', 'PATIENT_CREDIT') AND NEW.patient_id IS NULL THEN
        RAISE EXCEPTION 'JOURNAL_DIMENSION: % lines need a patient', account_code;
    END IF;
    IF account_code IN ('AR_PAYER', 'WRITE_OFF') AND NEW.payer_id IS NULL THEN
        RAISE EXCEPTION 'JOURNAL_DIMENSION: % lines need a payer', account_code;
    END IF;
    IF account_code IN ('CASH', 'CASH_OVER_SHORT') AND NEW.shift_id IS NULL THEN
        RAISE EXCEPTION 'JOURNAL_DIMENSION: % lines need a shift', account_code;
    END IF;
    RETURN NEW;
"""


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    debit = money_field(default=ZERO)
    credit = money_field(default=ZERO)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    payer = models.ForeignKey(
        "catalog.Payer", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    shift = models.ForeignKey(
        "payments.Shift", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    service_kind = models.CharField(max_length=20, choices=ServiceKind.choices, blank=True)
    memo = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "journal line"
        ordering: ClassVar[list[str]] = ["entry", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(Q(debit__gt=0) & Q(credit=0)) | (Q(credit__gt=0) & Q(debit=0)),
                name="ledger_line_one_side",
            ),
            models.CheckConstraint(
                condition=Q(service_kind="") | Q(service_kind__in=ServiceKind.values),
                name="ledger_line_service_kind_valid",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["account", "patient"], name="ledger_line_patient_idx"),
            models.Index(fields=["account", "payer"], name="ledger_line_payer_idx"),
            models.Index(fields=["account", "invoice"], name="ledger_line_invoice_idx"),
            models.Index(fields=["account", "shift"], name="ledger_line_shift_idx"),
            models.Index(
                fields=["account", "department", "service_kind"], name="ledger_line_revenue_idx"
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            append_only(),
            _balanced("line_entry_balanced", "NEW.entry_id"),
            pgtrigger.Trigger(
                name="line_dimensions",
                when=pgtrigger.Before,
                operation=pgtrigger.Insert,
                declare=[("account_code", "text")],
                func=_DIMENSIONS_SQL,
            ),
        ]

    def __str__(self) -> str:
        side = f"Dr {self.debit}" if self.debit else f"Cr {self.credit}"
        return f"{self.account_id} {side}"
