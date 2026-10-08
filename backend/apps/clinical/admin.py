from __future__ import annotations

from django.contrib import admin

from apps.clinical.models import (
    Allergy,
    ChronicCondition,
    ClinicalNote,
    Diagnosis,
    Icd10Code,
    NursingNote,
    OrderSet,
    OrderSetItem,
    Referral,
    Vitals,
)
from apps.core.admin_base import ReadOnlyAdmin


@admin.register(Icd10Code)
class Icd10CodeAdmin(admin.ModelAdmin[Icd10Code]):
    list_display = ("code", "title_en", "title_ar", "chapter", "is_leaf", "active")
    list_filter = ("chapter", "is_leaf", "active")
    search_fields = ("code", "title_en", "title_ar")


@admin.register(Allergy)
class AllergyAdmin(ReadOnlyAdmin[Allergy]):
    list_display = ("patient", "allergen_type", "substance", "drug_class", "severity", "status")
    list_filter = ("allergen_type", "severity", "status")
    search_fields = ("patient__file_no", "substance")


@admin.register(ChronicCondition)
class ChronicConditionAdmin(ReadOnlyAdmin[ChronicCondition]):
    list_display = ("patient", "name", "icd10", "since", "status")
    list_filter = ("status",)
    search_fields = ("patient__file_no", "name")


@admin.register(ClinicalNote)
class ClinicalNoteAdmin(ReadOnlyAdmin[ClinicalNote]):
    list_display = ("visit", "author", "status", "created_at", "signed_at")
    list_filter = ("status",)
    search_fields = ("visit__number",)


@admin.register(Diagnosis)
class DiagnosisAdmin(ReadOnlyAdmin[Diagnosis]):
    list_display = ("visit", "icd10", "text", "kind", "certainty", "recorded_at")
    list_filter = ("kind", "certainty")


@admin.register(Vitals)
class VitalsAdmin(ReadOnlyAdmin[Vitals]):
    list_display = ("visit", "recorded_at", "temperature_c", "pulse_bpm", "bp_systolic")


@admin.register(Referral)
class ReferralAdmin(ReadOnlyAdmin[Referral]):
    list_display = ("visit", "kind", "to_department", "external_facility", "urgency", "status")
    list_filter = ("kind", "urgency", "status")


class OrderSetItemInline(admin.TabularInline[OrderSetItem, OrderSet]):
    model = OrderSetItem
    extra = 0
    raw_id_fields = ("service",)


@admin.register(OrderSet)
class OrderSetAdmin(admin.ModelAdmin[OrderSet]):
    list_display = ("name_ar", "name_en", "owner", "department", "active")
    list_filter = ("active", "department")
    search_fields = ("name_ar", "name_en")
    raw_id_fields = ("owner",)
    inlines = (OrderSetItemInline,)


@admin.register(OrderSetItem)
class OrderSetItemAdmin(admin.ModelAdmin[OrderSetItem]):
    list_display = ("order_set", "service", "quantity", "dose", "frequency_code")
    raw_id_fields = ("order_set", "service")


@admin.register(NursingNote)
class NursingNoteAdmin(ReadOnlyAdmin[NursingNote]):
    list_display = ("visit", "kind", "author", "created_at")
    list_filter = ("kind",)
