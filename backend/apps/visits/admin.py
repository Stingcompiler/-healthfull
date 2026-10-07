from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.visits.models import (
    Admission,
    Appointment,
    Bed,
    BedCharge,
    BedStay,
    DoctorSchedule,
    QueueEntry,
    Visit,
)


@admin.register(Visit)
class VisitAdmin(ReadOnlyAdmin[Visit]):
    """Visits change through ``apps.visits.services`` (status, cancellation with refund flow)."""

    list_display = ("number", "patient", "visit_type", "status", "department", "doctor", "payer")
    list_filter = ("status", "visit_type", "department")
    search_fields = ("number", "patient__file_no", "patient__full_name_ar", "patient__full_name_en")
    date_hierarchy = "created_at"


@admin.register(QueueEntry)
class QueueEntryAdmin(ReadOnlyAdmin[QueueEntry]):
    list_display = ("queue_date", "token_no", "department", "doctor", "status", "priority")
    list_filter = ("status", "department", "queue_date")


@admin.register(Appointment)
class AppointmentAdmin(ReadOnlyAdmin[Appointment]):
    list_display = ("starts_at", "doctor", "patient", "contact_name", "status")
    list_filter = ("status", "department")
    search_fields = ("contact_name", "contact_phone", "patient__file_no")
    date_hierarchy = "starts_at"


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin[DoctorSchedule]):
    list_display = ("doctor", "weekday", "start_time", "end_time", "slot_minutes", "room", "active")
    list_filter = ("weekday", "active")


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin[Bed]):
    list_display = ("code", "name_ar", "name_en", "room", "bed_service", "status", "active")
    list_filter = ("status", "active")
    search_fields = ("code", "name_ar", "name_en")
    raw_id_fields = ("bed_service",)


@admin.register(Admission)
class AdmissionAdmin(ReadOnlyAdmin[Admission]):
    list_display = ("number", "visit", "admitting_doctor", "status", "admitted_at", "discharged_at")
    list_filter = ("status",)
    search_fields = ("number", "visit__number")


@admin.register(BedStay)
class BedStayAdmin(ReadOnlyAdmin[BedStay]):
    list_display = ("admission", "bed", "started_at", "ended_at")


@admin.register(BedCharge)
class BedChargeAdmin(ReadOnlyAdmin[BedCharge]):
    list_display = ("admission", "charge_date", "service_line")
