from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.patients.models import Patient, PatientCoverage, PatientMerge


class PatientCoverageInline(admin.TabularInline[PatientCoverage, Patient]):
    model = PatientCoverage
    fk_name = "patient"
    extra = 0
    raw_id_fields = ("payer", "created_by")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin[Patient]):
    list_display = (
        "file_no",
        "full_name_ar",
        "full_name_en",
        "sex",
        "date_of_birth",
        "phone",
        "is_incomplete",
        "is_active",
    )
    list_filter = ("sex", "is_incomplete", "is_active")
    search_fields = ("file_no", "full_name_ar", "full_name_en", "phone", "search_name")
    readonly_fields = (
        "file_no",
        "merged_into",
        "search_name",
        "phone_norm",
        "phone_alt_norm",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = (PatientCoverageInline,)


@admin.register(PatientCoverage)
class PatientCoverageAdmin(admin.ModelAdmin[PatientCoverage]):
    list_display = ("patient", "payer", "card_number", "valid_from", "valid_to", "is_default")
    list_filter = ("payer", "is_default", "active")
    search_fields = ("card_number", "patient__file_no", "patient__full_name_ar")
    raw_id_fields = ("patient", "created_by")


@admin.register(PatientMerge)
class PatientMergeAdmin(ReadOnlyAdmin[PatientMerge]):
    list_display = ("source", "target", "merged_by", "merged_at")
    search_fields = ("source__file_no", "target__file_no")
    date_hierarchy = "merged_at"
