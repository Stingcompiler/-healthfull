"""Visits, doctor queue, appointments, schedules and minimal inpatient (FEATURES 2, 10.5).

The visit is the container that links orders (service lines), invoices, results, dispenses
and refunds (FLOW.md). ``payer``/``coverage``/``card_number`` are the visit's default
coverage at registration time (null payer = cash); each service line may still be billed
to another payer or to the patient (FEATURES 5.6).
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, track_history


class VisitType(models.TextChoices):
    NEW = "new", "New"
    FOLLOW_UP = "follow_up", "Follow-up"
    EMERGENCY = "emergency", "Emergency"
    PHARMACY_SALE = "pharmacy_sale", "Walk-in pharmacy sale"
    INPATIENT = "inpatient", "Inpatient admission"


class VisitStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class Visit(models.Model):
    number = models.CharField(max_length=30, unique=True)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="visits")
    visit_type = models.CharField(max_length=20, choices=VisitType.choices, default=VisitType.NEW)
    status = models.CharField(max_length=20, choices=VisitStatus.choices, default=VisitStatus.OPEN)
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="visits"
    )
    doctor = models.ForeignKey(
        "core.DoctorProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visits",
    )
    payer = models.ForeignKey(
        "catalog.Payer", on_delete=models.PROTECT, null=True, blank=True, related_name="visits"
    )
    coverage = models.ForeignKey(
        "patients.PatientCoverage",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visits",
    )
    card_number = models.CharField(max_length=60, blank=True)
    follow_up_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="follow_ups"
    )
    appointment = models.OneToOneField(
        "visits.Appointment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="converted_visit",
    )
    chief_complaint = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "visit_cancel"},
    )
    cancel_note = models.TextField(blank=True)

    class Meta:
        verbose_name = "visit"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("visit_type", VisitType, "visits_visit_type_valid"),
            choice_check("status", VisitStatus, "visits_visit_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=VisitStatus.CLOSED) | Q(closed_at__isnull=False),
                name="visits_visit_closed_has_time",
            ),
            # Invariant 4: cancellation records reason, actor and time.
            models.CheckConstraint(
                condition=~Q(status=VisitStatus.CANCELLED)
                | Q(
                    cancelled_at__isnull=False,
                    cancelled_by__isnull=False,
                    cancel_reason__isnull=False,
                ),
                name="visits_visit_cancel_documented",
            ),
            models.CheckConstraint(
                condition=Q(coverage__isnull=True) | Q(payer__isnull=False),
                name="visits_visit_coverage_has_payer",
            ),
            models.CheckConstraint(
                condition=~Q(follow_up_of=F("id")), name="visits_visit_not_follow_up_of_self"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "-created_at"], name="visits_visit_patient_idx"),
            models.Index(fields=["status", "department"], name="visits_visit_status_dept_idx"),
            models.Index(fields=["doctor", "-created_at"], name="visits_visit_doctor_idx"),
            models.Index(fields=["-created_at"], name="visits_visit_created_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class QueueStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    CALLED = "called", "Called"
    IN_PROGRESS = "in_progress", "With the doctor"
    DONE = "done", "Done"
    NO_SHOW = "no_show", "Did not answer"
    CANCELLED = "cancelled", "Cancelled"


ACTIVE_QUEUE_STATUSES = [QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_PROGRESS]


@track_history()
class QueueEntry(models.Model):
    """A paid visit waiting for a doctor (FEATURES 2.3). Tokens restart daily per department."""

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="queue_entries")
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, related_name="queue_entries"
    )
    doctor = models.ForeignKey(
        "core.DoctorProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="queue_entries",
    )
    room = models.ForeignKey(
        "core.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    queue_date = models.DateField()
    token_no = models.PositiveIntegerField()
    priority = models.PositiveSmallIntegerField(
        default=0, help_text="Higher is served first (emergencies)."
    )
    status = models.CharField(
        max_length=20, choices=QueueStatus.choices, default=QueueStatus.WAITING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    called_at = models.DateTimeField(null=True, blank=True)
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "queue entry"
        verbose_name_plural = "queue entries"
        ordering: ClassVar[list[str]] = ["queue_date", "-priority", "token_no"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", QueueStatus, "visits_queue_status_valid"),
            models.UniqueConstraint(
                fields=["department", "queue_date", "token_no"], name="visits_queue_token_unique"
            ),
            models.UniqueConstraint(
                fields=["visit"],
                condition=Q(status__in=ACTIVE_QUEUE_STATUSES),
                name="visits_queue_one_active_per_visit",
            ),
            models.CheckConstraint(
                condition=Q(token_no__gte=1), name="visits_queue_token_positive"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["doctor", "queue_date", "status"], name="visits_queue_doctor_idx"),
            models.Index(
                fields=["department", "queue_date", "status"], name="visits_queue_dept_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.queue_date} #{self.token_no}"


class AppointmentStatus(models.TextChoices):
    BOOKED = "booked", "Booked"
    ARRIVED = "arrived", "Arrived (converted to a visit)"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No show"
    RESCHEDULED = "rescheduled", "Rescheduled"


@track_history()
class Appointment(models.Model):
    """A booked slot with a doctor (FEATURES 2.5, V1?). Converted to a visit on arrival."""

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
    )
    contact_name = models.CharField(
        max_length=200, blank=True, help_text="For callers without a patient file yet."
    )
    contact_phone = models.CharField(max_length=30, blank=True)
    doctor = models.ForeignKey(
        "core.DoctorProfile", on_delete=models.PROTECT, related_name="appointments"
    )
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, related_name="appointments"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.BOOKED
    )
    rescheduled_from = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="rescheduled_to"
    )
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "appointment"
        ordering: ClassVar[list[str]] = ["starts_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", AppointmentStatus, "visits_appointment_status_valid"),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="visits_appointment_positive_slot"
            ),
            models.CheckConstraint(
                condition=Q(patient__isnull=False) | ~Q(contact_name=""),
                name="visits_appointment_has_person",
            ),
            models.CheckConstraint(
                condition=~Q(status=AppointmentStatus.CANCELLED)
                | Q(cancelled_at__isnull=False, cancelled_by__isnull=False),
                name="visits_appointment_cancel_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["doctor", "starts_at"], name="visits_appt_doctor_idx"),
            models.Index(fields=["patient", "starts_at"], name="visits_appt_patient_idx"),
            models.Index(fields=["status", "starts_at"], name="visits_appt_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} @ {self.starts_at:%Y-%m-%d %H:%M}"


@track_history()
class DoctorSchedule(models.Model):
    """A doctor's weekly clinic hours (FEATURES 13.2). ``weekday``: 0 = Monday ... 6 = Sunday."""

    doctor = models.ForeignKey(
        "core.DoctorProfile", on_delete=models.CASCADE, related_name="schedules"
    )
    weekday = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=15)
    room = models.ForeignKey(
        "core.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "doctor schedule"
        ordering: ClassVar[list[str]] = ["doctor", "weekday", "start_time"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(weekday__gte=0) & Q(weekday__lte=6), name="visits_schedule_weekday"
            ),
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")), name="visits_schedule_positive_span"
            ),
            models.CheckConstraint(
                condition=Q(slot_minutes__gte=1), name="visits_schedule_slot_positive"
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=F("valid_from")),
                name="visits_schedule_valid_dates",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} d{self.weekday} {self.start_time}-{self.end_time}"


# --- Minimal inpatient (FEATURES 10.5, V1?) ---------------------------------------------------


class BedStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    OCCUPIED = "occupied", "Occupied"
    MAINTENANCE = "maintenance", "Out of service"


@track_history()
class Bed(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    room = models.ForeignKey(
        "core.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="beds"
    )
    bed_service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        related_name="beds",
        help_text="Service of kind 'bed' charged once per day of stay.",
    )
    status = models.CharField(max_length=20, choices=BedStatus.choices, default=BedStatus.AVAILABLE)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "bed"
        ordering: ClassVar[list[str]] = ["code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", BedStatus, "visits_bed_status_valid"),
        ]

    def __str__(self) -> str:
        return self.name_en or self.code


class AdmissionStatus(models.TextChoices):
    ADMITTED = "admitted", "Admitted"
    DISCHARGED = "discharged", "Discharged"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class Admission(models.Model):
    number = models.CharField(max_length=30, unique=True)
    visit = models.OneToOneField(Visit, on_delete=models.PROTECT, related_name="admission")
    admitting_doctor = models.ForeignKey(
        "core.DoctorProfile", on_delete=models.PROTECT, related_name="admissions"
    )
    admission_diagnosis = models.CharField(max_length=300, blank=True)
    status = models.CharField(
        max_length=20, choices=AdmissionStatus.choices, default=AdmissionStatus.ADMITTED
    )
    admitted_at = models.DateTimeField()
    admitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    discharge_summary = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "admission"
        ordering: ClassVar[list[str]] = ["-admitted_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", AdmissionStatus, "visits_admission_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=AdmissionStatus.DISCHARGED)
                | Q(discharged_at__isnull=False, discharged_by__isnull=False),
                name="visits_admission_discharge_documented",
            ),
            models.CheckConstraint(
                condition=Q(discharged_at__isnull=True) | Q(discharged_at__gte=F("admitted_at")),
                name="visits_admission_discharge_after_admit",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status"], name="visits_admission_status_idx"),
        ]

    def __str__(self) -> str:
        return self.number


@track_history()
class BedStay(models.Model):
    """One bed for one stretch of an admission. ``ended_at`` empty = still in the bed."""

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="bed_stays")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="stays")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "bed stay"
        ordering: ClassVar[list[str]] = ["admission", "started_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gt=F("started_at")),
                name="visits_bedstay_positive_span",
            ),
            models.UniqueConstraint(
                fields=["bed"], condition=Q(ended_at__isnull=True), name="visits_bedstay_bed_free"
            ),
            models.UniqueConstraint(
                fields=["admission"],
                condition=Q(ended_at__isnull=True),
                name="visits_bedstay_one_open_per_admission",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.admission_id} in {self.bed_id}"


@track_history()
class BedCharge(models.Model):
    """The daily bed charge line of an admission: at most one per admission per day."""

    admission = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="bed_charges")
    bed_stay = models.ForeignKey(BedStay, on_delete=models.PROTECT, related_name="charges")
    charge_date = models.DateField()
    service_line = models.OneToOneField(
        "orders.ServiceLine", on_delete=models.PROTECT, related_name="bed_charge"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "bed charge"
        ordering: ClassVar[list[str]] = ["admission", "charge_date"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["admission", "charge_date"], name="visits_bedcharge_once_per_day"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.admission_id} {self.charge_date}"
