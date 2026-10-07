from __future__ import annotations

from django.contrib import admin

from apps.catalog.models import (
    CoverageRule,
    Exclusion,
    Payer,
    PriceItem,
    PriceList,
    PriceListVersion,
    Service,
    ServiceCategory,
)


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin[ServiceCategory]):
    list_display = ("code", "name_ar", "name_en", "sort_order", "active")
    list_filter = ("active",)
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin[Service]):
    list_display = ("code", "name_ar", "name_en", "kind", "department", "category", "active")
    list_filter = ("kind", "active", "department", "category")
    search_fields = ("code", "name_ar", "name_en")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin[PriceList]):
    list_display = ("code", "name_ar", "name_en", "kind", "is_default", "active")
    list_filter = ("kind", "active")
    search_fields = ("code", "name_ar", "name_en")


class PriceItemInline(admin.TabularInline[PriceItem, PriceListVersion]):
    model = PriceItem
    extra = 0
    raw_id_fields = ("service",)


@admin.register(PriceListVersion)
class PriceListVersionAdmin(admin.ModelAdmin[PriceListVersion]):
    list_display = ("price_list", "effective_from", "percent_change", "created_by", "created_at")
    list_filter = ("price_list",)
    date_hierarchy = "effective_from"
    raw_id_fields = ("based_on", "created_by")
    inlines = (PriceItemInline,)


@admin.register(PriceItem)
class PriceItemAdmin(admin.ModelAdmin[PriceItem]):
    list_display = ("version", "service", "unit_price")
    list_filter = ("version__price_list",)
    search_fields = ("service__code", "service__name_ar", "service__name_en")
    raw_id_fields = ("version", "service")


class CoverageRuleInline(admin.TabularInline[CoverageRule, Payer]):
    model = CoverageRule
    extra = 0
    raw_id_fields = ("service",)


class ExclusionInline(admin.TabularInline[Exclusion, Payer]):
    model = Exclusion
    extra = 0
    raw_id_fields = ("service",)


@admin.register(Payer)
class PayerAdmin(admin.ModelAdmin[Payer]):
    list_display = ("code", "name_ar", "name_en", "kind", "price_list", "claim_period", "active")
    list_filter = ("kind", "active", "claim_period")
    search_fields = ("code", "name_ar", "name_en", "contract_no")
    inlines = (CoverageRuleInline, ExclusionInline)


@admin.register(CoverageRule)
class CoverageRuleAdmin(admin.ModelAdmin[CoverageRule]):
    list_display = (
        "payer",
        "service",
        "service_kind",
        "rule_kind",
        "payer_percent",
        "copay_amount",
        "ceiling_amount",
        "requires_pre_approval",
        "active",
    )
    list_filter = ("payer", "rule_kind", "active", "requires_pre_approval")
    raw_id_fields = ("service",)


@admin.register(Exclusion)
class ExclusionAdmin(admin.ModelAdmin[Exclusion]):
    list_display = ("payer", "service", "service_kind", "active")
    list_filter = ("payer", "active")
    raw_id_fields = ("service",)
