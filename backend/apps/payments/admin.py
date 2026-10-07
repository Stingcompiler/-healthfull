from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.payments.models import (
    Allocation,
    Bank,
    CashHandover,
    Payment,
    Refund,
    Shift,
    ShiftReview,
    Till,
)


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin[Bank]):
    list_display = ("code", "name_ar", "name_en", "sort_order", "active")
    list_filter = ("active",)
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Till)
class TillAdmin(admin.ModelAdmin[Till]):
    list_display = ("code", "name_ar", "name_en", "active")
    list_filter = ("active",)


@admin.register(Shift)
class ShiftAdmin(ReadOnlyAdmin[Shift]):
    """Read-only: a closed shift never changes (invariant 3)."""

    list_display = (
        "number",
        "cashier",
        "status",
        "opened_at",
        "closed_at",
        "expected_cash",
        "counted_cash",
        "variance",
    )
    list_filter = ("status",)
    search_fields = ("number", "cashier__username")
    date_hierarchy = "opened_at"


@admin.register(ShiftReview)
class ShiftReviewAdmin(ReadOnlyAdmin[ShiftReview]):
    list_display = ("shift", "outcome", "reviewed_by", "reviewed_at")
    list_filter = ("outcome",)


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin[Payment]):
    list_display = (
        "number",
        "shift",
        "patient",
        "method",
        "amount",
        "bank",
        "reference",
        "verification",
        "created_at",
    )
    list_filter = ("method", "verification", "bank", "duplicate_override")
    search_fields = ("number", "reference", "reference_norm", "patient__file_no")
    date_hierarchy = "created_at"


@admin.register(Allocation)
class AllocationAdmin(ReadOnlyAdmin[Allocation]):
    list_display = ("payment", "invoice", "kind", "amount", "created_at")
    list_filter = ("kind",)
    search_fields = ("payment__number", "invoice__number")


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin[Refund]):
    list_display = ("number", "patient", "amount", "method", "status", "requested_at", "paid_at")
    list_filter = ("status", "method")
    search_fields = ("number", "patient__file_no")


@admin.register(CashHandover)
class CashHandoverAdmin(ReadOnlyAdmin[CashHandover]):
    list_display = ("number", "shift", "destination", "to_shift", "amount", "handed_at")
    list_filter = ("destination",)
    search_fields = ("number",)
