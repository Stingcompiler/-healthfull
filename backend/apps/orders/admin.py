from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.orders.models import PerformAuthorization, PrescriptionDetail, ServiceLine


@admin.register(ServiceLine)
class ServiceLineAdmin(ReadOnlyAdmin[ServiceLine]):
    """Read-only: line transitions go through ``apps.orders.services`` (ARCHITECTURE 4.4)."""

    list_display = (
        "id",
        "visit",
        "service",
        "kind",
        "quantity",
        "billing_status",
        "fulfilment_status",
        "authorization",
        "ordered_at",
    )
    list_filter = ("kind", "billing_status", "fulfilment_status", "order_source")
    search_fields = ("visit__number", "service__code", "service__name_en", "service__name_ar")
    date_hierarchy = "ordered_at"


@admin.register(PerformAuthorization)
class PerformAuthorizationAdmin(ReadOnlyAdmin[PerformAuthorization]):
    list_display = ("id", "visit", "kind", "authorized_by", "authorized_at", "revoked_at")
    list_filter = ("kind",)
    search_fields = ("visit__number", "approval_reference")


@admin.register(PrescriptionDetail)
class PrescriptionDetailAdmin(ReadOnlyAdmin[PrescriptionDetail]):
    list_display = ("line", "dose", "route", "frequency_code", "duration_days")
