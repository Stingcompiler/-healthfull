"""Invoice and credit note schema: immutability triggers and constraints (invariants 2, 4, 6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db


# --- Approved invoices never change (invariant 2) -------------------------------------------


def test_draft_invoice_and_lines_are_editable() -> None:
    inv = b.draft_invoice()
    line = b.invoice_line(inv)
    Invoice.objects.filter(pk=inv.pk).update(note="still a draft")
    InvoiceLine.objects.filter(pk=line.pk).update(description_en="Edited")
    line.delete()
    inv.delete()


def test_approved_invoice_rejects_orm_update_and_delete() -> None:
    inv = b.approved_invoice()
    b.db_rejects(lambda: Invoice.objects.filter(pk=inv.pk).update(note="x"), "INVOICE_FROZEN")
    b.db_rejects(lambda: Invoice.objects.filter(pk=inv.pk).delete(), "INVOICE_FROZEN")
    inv.patient_total = Decimal("1.00")
    b.db_rejects(inv.save, "INVOICE_FROZEN")


def test_approved_invoice_rejects_raw_sql_update_and_delete() -> None:
    inv = b.approved_invoice()
    b.sql_rejects(
        "UPDATE billing_invoice SET gross_total = 0, patient_total = 0 WHERE id = %s",
        [inv.pk],
        "INVOICE_FROZEN",
    )
    b.sql_rejects(
        "UPDATE billing_invoice SET status = 'draft' WHERE id = %s", [inv.pk], "INVOICE_FROZEN"
    )
    b.sql_rejects("DELETE FROM billing_invoice WHERE id = %s", [inv.pk], "INVOICE_FROZEN")


def test_void_invoice_never_changes() -> None:
    inv = b.draft_invoice()
    Invoice.objects.filter(pk=inv.pk).update(
        status="void", voided_by=b.user(), voided_at=timezone.now(), void_note="wrong visit"
    )
    b.sql_rejects(
        "UPDATE billing_invoice SET status = 'draft' WHERE id = %s", [inv.pk], "INVOICE_FROZEN"
    )


def test_frozen_line_rejects_orm_and_raw_sql() -> None:
    inv = b.approved_invoice()
    line = inv.lines.get()
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(discount=Decimal("1")),
        "INVOICE_FROZEN",
    )
    b.db_rejects(lambda: InvoiceLine.objects.filter(pk=line.pk).delete(), "INVOICE_FROZEN")
    b.sql_rejects(
        "UPDATE billing_invoiceline SET unit_price = 1, gross = 1, patient_share = 1 WHERE id = %s",
        [line.pk],
        "INVOICE_FROZEN",
    )
    b.sql_rejects(
        "UPDATE billing_invoiceline SET frozen = false WHERE id = %s", [line.pk], "INVOICE_FROZEN"
    )
    b.sql_rejects("DELETE FROM billing_invoiceline WHERE id = %s", [line.pk], "INVOICE_FROZEN")


def test_no_line_can_be_added_to_an_approved_invoice() -> None:
    inv = b.approved_invoice()
    b.db_rejects(lambda: b.invoice_line(inv, line_no=9), "INVOICE_FROZEN")


# --- Commit-time consistency of an approved invoice -----------------------------------------


def test_consistent_approval_commits() -> None:
    with b.deferred_checks_fire(rejects=False):
        inv = b.draft_invoice()
        b.invoice_line(inv, unit_price="250.00", quantity="2")
        b.invoice_line(inv, unit_price="10.00", payer_share="4.00", payer_obj=b.payer())
        b.approve_invoice(inv)
    assert inv.gross_total == Decimal("510.00")
    assert inv.patient_total == Decimal("506.00")


def test_approval_with_unfrozen_lines_fails_at_commit() -> None:
    with b.deferred_checks_fire("INVOICE_LINES_NOT_FROZEN"):
        inv = b.draft_invoice()
        line = b.invoice_line(inv)
        Invoice.objects.filter(pk=inv.pk).update(
            status="approved",
            number="INV-T-1",
            approved_by=b.user(),
            approved_at=timezone.now(),
            priced_on=timezone.localdate(),
            gross_total=line.gross,
            patient_total=line.patient_share,
        )


def test_approval_with_wrong_totals_fails_at_commit() -> None:
    with b.deferred_checks_fire("INVOICE_TOTALS_MISMATCH"):
        inv = b.draft_invoice()
        b.invoice_line(inv)
        InvoiceLine.objects.filter(invoice=inv).update(
            frozen=True, price_list_version=b.price_version()
        )
        Invoice.objects.filter(pk=inv.pk).update(
            status="approved",
            number="INV-T-2",
            approved_by=b.user(),
            approved_at=timezone.now(),
            priced_on=timezone.localdate(),
            gross_total=Decimal("1.00"),
            patient_total=Decimal("1.00"),
        )


def test_empty_approved_invoice_fails_at_commit() -> None:
    with b.deferred_checks_fire("INVOICE_EMPTY"):
        inv = b.draft_invoice()
        Invoice.objects.filter(pk=inv.pk).update(
            status="approved",
            number="INV-T-3",
            approved_by=b.user(),
            approved_at=timezone.now(),
            priced_on=timezone.localdate(),
        )


# --- Constraints -------------------------------------------------------------------------------


def test_invoice_approval_must_be_documented() -> None:
    inv = b.draft_invoice()
    b.db_rejects(
        lambda: Invoice.objects.filter(pk=inv.pk).update(status="approved"),
        "billing_invoice_approval_documented",
    )
    b.db_rejects(
        lambda: Invoice.objects.filter(pk=inv.pk).update(status="void"),
        "billing_invoice_void_documented",
    )
    b.db_rejects(
        lambda: Invoice.objects.filter(pk=inv.pk).update(status="paid"),
        "billing_invoice_status_valid",
    )


def test_invoice_totals_balance() -> None:
    inv = b.draft_invoice()
    b.db_rejects(
        lambda: Invoice.objects.filter(pk=inv.pk).update(
            gross_total=Decimal("100"), patient_total=Decimal("90")
        ),
        "billing_invoice_totals_balance",
    )
    b.db_rejects(
        lambda: Invoice.objects.filter(pk=inv.pk).update(
            gross_total=Decimal("-1"), patient_total=Decimal("-1")
        ),
        "billing_invoice_totals_non_negative",
    )


def test_line_gross_is_quantity_times_price_rounded_half_up() -> None:
    inv = b.draft_invoice()
    line = b.invoice_line(inv, unit_price="33.33", quantity="1.5")
    assert line.gross == Decimal("50.00")  # 49.995 -> 50.00
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(
            gross=Decimal("49.99"), patient_share=Decimal("49.99")
        ),
        "billing_invoiceline_gross_is_qty_times_price",
    )


def test_line_shares_balance_and_cash_lines_have_no_payer_share() -> None:
    inv = b.draft_invoice()
    line = b.invoice_line(inv)
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(patient_share=Decimal("1")),
        "billing_invoiceline_shares_balance",
    )
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(
            payer_share=Decimal("40"), patient_share=Decimal("60")
        ),
        "billing_invoiceline_cash_has_no_payer_share",
    )
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(
            payer=b.payer(), payer_share=Decimal("120"), patient_share=Decimal("-20")
        ),
        "billing_invoiceline_amounts_non_negative",
    )


def test_discount_records_reason_and_approver() -> None:
    inv = b.draft_invoice()
    line = b.invoice_line(inv)
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(
            discount=Decimal("10"), patient_share=Decimal("90")
        ),
        "billing_invoiceline_discount_documented",
    )
    InvoiceLine.objects.filter(pk=line.pk).update(
        discount=Decimal("10"),
        patient_share=Decimal("90"),
        discount_reason=b.reason("discount"),
        discount_approved_by=b.user(),
    )


def test_frozen_line_needs_price_version() -> None:
    inv = b.draft_invoice()
    line = b.invoice_line(inv)
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=line.pk).update(frozen=True),
        "billing_invoiceline_frozen_has_price_version",
    )


def test_service_line_is_billed_once() -> None:
    first = b.approved_invoice()
    service_line = first.lines.get().service_line
    second = b.draft_invoice(service_line.visit)
    other = b.invoice_line(second, line=service_line)  # a draft may hold it again
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=other.pk).update(
            frozen=True, price_list_version=b.price_version()
        ),
        "billing_invoiceline_service_line_billed_once",
    )


def test_line_numbers_unique_per_invoice() -> None:
    inv = b.draft_invoice()
    b.invoice_line(inv, line_no=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        b.invoice_line(inv, line_no=1)


# --- Credit notes ------------------------------------------------------------------------------


def _credit_note(inv: Invoice, *, amount: str = "100.00", approve: bool = True) -> CreditNote:
    line = inv.lines.first()
    assert line is not None
    note = CreditNote.objects.create(
        invoice=inv,
        patient=inv.patient,
        reason_code=b.reason("credit_note"),
        created_by=b.user(),
    )
    CreditNoteLine.objects.create(
        credit_note=note,
        line_no=1,
        invoice_line=line,
        quantity=Decimal("1"),
        gross=Decimal(amount),
        patient_share=Decimal(amount),
    )
    if approve:
        CreditNoteLine.objects.filter(credit_note=note).update(frozen=True)
        CreditNote.objects.filter(pk=note.pk).update(
            status="approved",
            number=f"CN-2026-{b.n():06d}",
            approved_by=b.user(),
            approved_at=timezone.now(),
            gross_total=Decimal(amount),
            patient_total=Decimal(amount),
        )
        note.refresh_from_db()
    return note


def test_approved_credit_note_is_immutable() -> None:
    note = _credit_note(b.approved_invoice())
    line = note.lines.get()
    b.db_rejects(
        lambda: CreditNote.objects.filter(pk=note.pk).update(reason_note="x"),
        "CREDIT_NOTE_FROZEN",
    )
    b.db_rejects(lambda: CreditNote.objects.filter(pk=note.pk).delete(), "CREDIT_NOTE_FROZEN")
    b.sql_rejects(
        "UPDATE billing_creditnote SET status = 'draft' WHERE id = %s", [note.pk], "CREDIT_NOTE"
    )
    b.sql_rejects("DELETE FROM billing_creditnote WHERE id = %s", [note.pk], "CREDIT_NOTE")
    b.sql_rejects(
        "UPDATE billing_creditnoteline SET gross = 1, patient_share = 1 WHERE id = %s",
        [line.pk],
        "CREDIT_NOTE_FROZEN",
    )
    b.sql_rejects(
        "DELETE FROM billing_creditnoteline WHERE id = %s", [line.pk], "CREDIT_NOTE_FROZEN"
    )


def test_credit_note_cannot_credit_more_than_invoiced() -> None:
    inv = b.approved_invoice(unit_price="100.00")
    with b.deferred_checks_fire(rejects=False):
        _credit_note(inv, amount="60.00")
    with b.deferred_checks_fire("CREDIT_EXCEEDS_INVOICE"):
        _credit_note(inv, amount="60.00")


def test_credit_note_lines_must_belong_to_its_invoice() -> None:
    inv = b.approved_invoice()
    other = b.approved_invoice()
    note = _credit_note(inv, approve=False)
    # A credit line never changes the invoice line it credits (refused at once) ...
    b.db_rejects(
        lambda: CreditNoteLine.objects.filter(credit_note=note).update(
            invoice_line=other.lines.get()
        ),
        "Cannot update",
    )
    # ... and a note crediting another invoice's line is refused when it is approved.
    with b.deferred_checks_fire("CREDIT_WRONG_INVOICE"):
        CreditNoteLine.objects.filter(credit_note=note).delete()
        CreditNoteLine.objects.create(
            credit_note=note,
            line_no=1,
            invoice_line=other.lines.get(),
            quantity=Decimal("1"),
            gross=Decimal("100.00"),
            patient_share=Decimal("100.00"),
            frozen=True,
        )
        CreditNote.objects.filter(pk=note.pk).update(
            status="approved",
            number="CN-T-1",
            approved_by=b.user(),
            approved_at=timezone.now(),
            gross_total=Decimal("100.00"),
            patient_total=Decimal("100.00"),
        )


def test_credit_note_requires_reason() -> None:
    inv = b.approved_invoice()
    with pytest.raises(IntegrityError), transaction.atomic():
        CreditNote.objects.create(invoice=inv, patient=inv.patient, created_by=b.user())
