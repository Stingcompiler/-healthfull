from __future__ import annotations

from django.contrib import admin

from apps.claims.models import Claim, ClaimLine, PayerPayment, PayerPaymentAllocation
from apps.core.admin_base import ReadOnlyAdmin, ReadOnlyInline


class ClaimLineInline(ReadOnlyInline[ClaimLine, Claim]):
    model = ClaimLine
    fields = ("invoice_line", "amount_claimed", "status", "accepted_amount", "rejected_amount")


@admin.register(Claim)
class ClaimAdmin(ReadOnlyAdmin[Claim]):
    list_display = (
        "number",
        "payer",
        "period_start",
        "period_end",
        "status",
        "claimed_total",
        "accepted_total",
        "rejected_total",
    )
    list_filter = ("status", "payer")
    search_fields = ("number",)
    inlines = (ClaimLineInline,)


@admin.register(ClaimLine)
class ClaimLineAdmin(ReadOnlyAdmin[ClaimLine]):
    list_display = ("claim", "invoice_line", "amount_claimed", "status", "resolution")
    list_filter = ("status", "resolution")


@admin.register(PayerPayment)
class PayerPaymentAdmin(ReadOnlyAdmin[PayerPayment]):
    list_display = ("number", "payer", "amount", "method", "bank", "reference", "received_on")
    list_filter = ("payer", "method")
    search_fields = ("number", "reference")


@admin.register(PayerPaymentAllocation)
class PayerPaymentAllocationAdmin(ReadOnlyAdmin[PayerPaymentAllocation]):
    list_display = ("payer_payment", "claim", "claim_line", "amount", "created_at")
