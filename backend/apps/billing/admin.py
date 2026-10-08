from __future__ import annotations

from django.contrib import admin

from apps.billing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine
from apps.core.admin_base import ReadOnlyAdmin, ReadOnlyInline


class InvoiceLineInline(ReadOnlyInline[InvoiceLine, Invoice]):
    model = InvoiceLine
    fields = (
        "line_no",
        "service",
        "quantity",
        "unit_price",
        "gross",
        "discount",
        "payer",
        "payer_share",
        "patient_share",
        "frozen",
    )


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdmin[Invoice]):
    """Read-only: approved invoices are immutable (invariant 2); drafts change via services."""

    list_display = (
        "number",
        "visit",
        "patient",
        "status",
        "gross_total",
        "payer_total",
        "patient_total",
        "approved_at",
    )
    list_filter = ("status",)
    search_fields = ("number", "visit__number", "patient__file_no")
    date_hierarchy = "created_at"
    inlines = (InvoiceLineInline,)


@admin.register(InvoiceLine)
class InvoiceLineAdmin(ReadOnlyAdmin[InvoiceLine]):
    list_display = ("invoice", "line_no", "service", "gross", "payer", "patient_share", "frozen")
    list_filter = ("frozen", "kind")
    search_fields = ("invoice__number",)


class CreditNoteLineInline(ReadOnlyInline[CreditNoteLine, CreditNote]):
    model = CreditNoteLine
    fields = ("line_no", "invoice_line", "quantity", "gross", "payer_share", "patient_share")


@admin.register(CreditNote)
class CreditNoteAdmin(ReadOnlyAdmin[CreditNote]):
    list_display = ("number", "invoice", "patient", "status", "gross_total", "approved_at")
    list_filter = ("status",)
    search_fields = ("number", "invoice__number", "patient__file_no")
    inlines = (CreditNoteLineInline,)


@admin.register(CreditNoteLine)
class CreditNoteLineAdmin(ReadOnlyAdmin[CreditNoteLine]):
    list_display = ("credit_note", "line_no", "invoice_line", "gross", "patient_share", "frozen")
