from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin, ReadOnlyInline
from apps.lab.models import (
    LabParameter,
    LabTest,
    ReferenceRange,
    ResultSet,
    ResultValue,
    ResultVersion,
    Sample,
)


class LabParameterInline(admin.TabularInline[LabParameter, LabTest]):
    model = LabParameter
    extra = 0
    show_change_link = True


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin[LabTest]):
    list_display = ("code", "service", "sample_type", "turnaround_minutes", "active")
    list_filter = ("sample_type", "active")
    search_fields = ("code", "service__name_ar", "service__name_en")
    raw_id_fields = ("service",)
    inlines = (LabParameterInline,)


class ReferenceRangeInline(admin.TabularInline[ReferenceRange, LabParameter]):
    model = ReferenceRange
    extra = 0


@admin.register(LabParameter)
class LabParameterAdmin(admin.ModelAdmin[LabParameter]):
    list_display = ("test", "code", "name_ar", "name_en", "unit", "value_type", "active")
    list_filter = ("value_type", "active")
    search_fields = ("code", "name_ar", "name_en", "test__code")
    inlines = (ReferenceRangeInline,)


@admin.register(ReferenceRange)
class ReferenceRangeAdmin(admin.ModelAdmin[ReferenceRange]):
    list_display = ("parameter", "sex", "age_min_days", "age_max_days", "low", "high")
    list_filter = ("sex",)


@admin.register(Sample)
class SampleAdmin(ReadOnlyAdmin[Sample]):
    list_display = ("accession_no", "visit", "sample_type", "status", "collected_at")
    list_filter = ("status", "sample_type")
    search_fields = ("accession_no", "visit__number")


@admin.register(ResultSet)
class ResultSetAdmin(ReadOnlyAdmin[ResultSet]):
    list_display = ("service_line", "test", "sample", "created_at", "first_approved_at")
    list_filter = ("test",)


class ResultValueInline(ReadOnlyInline[ResultValue, ResultVersion]):
    model = ResultValue
    fields = ("parameter", "value_numeric", "value_text", "unit", "flag")


@admin.register(ResultVersion)
class ResultVersionAdmin(ReadOnlyAdmin[ResultVersion]):
    """Read-only: approved versions are immutable; corrections are amended versions."""

    list_display = ("result_set", "version_no", "status", "entered_by", "approved_by")
    list_filter = ("status",)
    inlines = (ResultValueInline,)


@admin.register(ResultValue)
class ResultValueAdmin(ReadOnlyAdmin[ResultValue]):
    list_display = ("version", "parameter", "value_numeric", "value_text", "flag")
    list_filter = ("flag",)
