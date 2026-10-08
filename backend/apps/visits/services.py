"""Visits, doctor queue, appointments and minimal inpatient (FEATURES 2, 10.5).

* A visit is the container of a patient's encounter. Creating one adds the consultation fee
  line (``requested``) through ``orders.services`` and a queue token for the department.
* Follow-up rule (FEATURES 2.2, ``Policy.follow_up_window_days`` and
  ``follow_up_discount_percent``): a visit with the same doctor (or department when no
  doctor) within the window after an original, non-cancelled visit is a follow-up of that
  original. The window always counts from the original, so chained follow-ups never extend
  it. At 100% the follow-up has no consultation line at all; below 100% the line is created
  and billing applies :func:`follow_up_discount_percent` with the ``FOLLOW_UP`` reason.
* The doctor queue shows paid visits in token order (FEATURES 2.3): an entry is *ready* when
  the visit has no open consultation line that is neither settled nor authorized
  (invariant 1: no consultation without payment or a documented perform-first exception).
  Finishing the consultation performs the consultation line.
* Appointments (FEATURES 2.5) refuse overlapping slots of a doctor; booking inside a
  doctor's schedule is checked when the doctor has a schedule.
* Minimal inpatient (FEATURES 10.5): admit to a bed, move beds, discharge. Bed days are
  charged per night in arrears (midnight census): a daily run of :func:`charge_bed_days`
  charges the nights that have passed, and discharge charges the rest, at least one day.
  Each night is a ``bed_charge`` service line (one ``BedCharge`` per admission and date)
  at the bed occupied at the end of that date. Charging in arrears never needs a reversal.
  The admission records the perform-first exception the nights are given under (who and
  why, invariants 1 and 4), and each night's line is performed when it is charged. A
  patient holds one open admission (locked on the patient, unique in the database).
* Lock order: patient, visit, queue entries, service lines (the money engine's order).
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.catalog.models import Service, ServiceKind
from apps.core.models import (
    CenterProfile,
    Department,
    DoctorProfile,
    Policy,
    ReasonCategory,
    ReasonCode,
    Room,
    User,
)
from apps.core.services import next_number, resolve_reason
from apps.orders.models import BillingStatus, FulfilmentStatus, OrderSource, ServiceLine
from apps.patients import services as patient_services
from apps.patients.models import Patient, PatientCoverage
from apps.visits.models import (
    ACTIVE_QUEUE_STATUSES,
    Admission,
    AdmissionStatus,
    Appointment,
    AppointmentStatus,
    Bed,
    BedCharge,
    BedStatus,
    BedStay,
    DoctorSchedule,
    QueueEntry,
    QueueStatus,
    Visit,
    VisitStatus,
    VisitType,
)
from domain import coverage as dc
from domain import queue as dq
from domain.errors import DomainError

__all__ = [
    "EMERGENCY_PRIORITY",
    "FINANCIAL_EVENTS",
    "AgendaItem",
    "DayAgenda",
    "DisplayEntry",
    "LineView",
    "TimelineEvent",
    "TimelineItem",
    "TokenSlip",
    "VisitOptions",
    "VisitView",
    "WaitingRoom",
    "admit",
    "appointment_day",
    "available_slots",
    "bed_charge_dates",
    "board",
    "board_row",
    "book_appointment",
    "call_next",
    "call_patient",
    "cancel_appointment",
    "cancel_queue_entry",
    "cancel_visit",
    "change_coverage",
    "charge_bed_days",
    "close_visit",
    "convert_appointment",
    "create_bed",
    "create_visit",
    "discharge",
    "enqueue",
    "finish_consultation",
    "follow_up_discount_percent",
    "follow_up_origin",
    "is_ready",
    "mark_appointment_no_show",
    "mark_no_show",
    "move_entry",
    "queue",
    "reassign_future_appointments",
    "requeue",
    "reschedule_appointment",
    "start_consultation",
    "timeline",
    "timeline_view",
    "token_slip",
    "transfer_bed",
    "upcoming_appointments",
    "update_appointment",
    "visit_list",
    "visit_options",
    "visit_view",
    "waiting_room",
]

EMERGENCY_PRIORITY = 10
DEFAULT_SLOT_MINUTES = 15
_NO_FEE_TYPES = {VisitType.PHARMACY_SALE, VisitType.INPATIENT}

#: Allowed queue moves (from -> to).
QUEUE_TRANSITIONS: dict[str, frozenset[str]] = {
    QueueStatus.WAITING: frozenset(
        {QueueStatus.CALLED, QueueStatus.IN_PROGRESS, QueueStatus.NO_SHOW, QueueStatus.CANCELLED}
    ),
    QueueStatus.CALLED: frozenset(
        {
            QueueStatus.WAITING,
            QueueStatus.IN_PROGRESS,
            QueueStatus.NO_SHOW,
            QueueStatus.CANCELLED,
        }
    ),
    QueueStatus.IN_PROGRESS: frozenset({QueueStatus.DONE}),
    QueueStatus.NO_SHOW: frozenset({QueueStatus.WAITING, QueueStatus.CANCELLED}),
    QueueStatus.DONE: frozenset(),
    QueueStatus.CANCELLED: frozenset(),
}


def _orders() -> ModuleType:
    """``apps.orders.services`` (the financial engine's write path for service lines)."""
    return importlib.import_module("apps.orders.services")


def _now(now: datetime | None) -> datetime:
    return now or timezone.now()


# --- visits ---------------------------------------------------------------------------------


def follow_up_origin(
    patient: Patient,
    *,
    doctor: DoctorProfile | None,
    department: Department | None,
    at: datetime,
    window_days: int,
) -> Visit | None:
    """The original visit this one follows up within the window, if any (FEATURES 2.2)."""
    if window_days <= 0 or (doctor is None and department is None):
        return None
    qs = Visit.objects.filter(
        patient_id__in=patient_services.file_ids(patient),
        follow_up_of__isnull=True,
        visit_type__in=[VisitType.NEW, VisitType.EMERGENCY],
        created_at__gte=at - timedelta(days=window_days),
        created_at__lte=at,
    ).exclude(status=VisitStatus.CANCELLED)
    qs = qs.filter(doctor=doctor) if doctor is not None else qs.filter(department=department)
    return qs.order_by("-created_at", "-id").first()


def follow_up_discount_percent(visit: Visit) -> Decimal:
    """Discount billing applies to the consultation line of a follow-up visit (0 if none)."""
    if visit.follow_up_of_id is None:
        return Decimal(0)
    return Decimal(Policy.load().follow_up_discount_percent)


def _visit_coverage(
    patient: Patient,
    coverage: PatientCoverage | None,
    use_default: bool,
    card_number: str,
    on: date,
) -> tuple[PatientCoverage | None, str]:
    if coverage is None and use_default:
        coverage = patient_services.active_coverage(patient, on=on)
    if coverage is None:
        return None, ""
    valid = (
        coverage.patient_id in patient_services.file_ids(patient)
        and coverage.active
        and coverage.payer.active
        and (coverage.valid_from is None or coverage.valid_from <= on)
        and (coverage.valid_to is None or coverage.valid_to >= on)
    )
    if not valid:
        raise DomainError("COVERAGE_INVALID", "The coverage is not valid for this visit")
    dc.require_contract(coverage.payer.contract_start, coverage.payer.contract_end, on)
    card = card_number.strip() or coverage.card_number
    if coverage.payer.requires_card_number and not card:
        raise DomainError("CARD_NUMBER_REQUIRED", "This payer requires a card number")
    return coverage, card


def create_visit(
    *,
    patient: Patient,
    actor: User,
    doctor: DoctorProfile | None = None,
    department: Department | None = None,
    visit_type: str = VisitType.NEW,
    coverage: PatientCoverage | None = None,
    use_default_coverage: bool = True,
    card_number: str = "",
    chief_complaint: str = "",
    appointment: Appointment | None = None,
    room: Room | None = None,
    now: datetime | None = None,
) -> Visit:
    """Open a visit with its consultation line and queue token (FEATURES 2.1-2.3).

    Raises:
        DomainError: ``PATIENT_MERGED``, ``PATIENT_INACTIVE``, ``DOCTOR_INACTIVE``,
            ``DEPARTMENT_REQUIRED``, ``COVERAGE_INVALID``, ``CARD_NUMBER_REQUIRED``,
            ``INVALID_VISIT_TYPE``, ``APPOINTMENT_NOT_BOOKED``.
    """
    at = _now(now)
    if visit_type not in VisitType.values:
        raise DomainError("INVALID_VISIT_TYPE", "Unknown visit type", visit_type=visit_type)
    if patient.merged_into_id is not None:
        raise DomainError("PATIENT_MERGED", "This file was merged into another file")
    if not patient.is_active:
        raise DomainError("PATIENT_INACTIVE", "The patient file is inactive")
    if doctor is not None and not doctor.active:
        raise DomainError("DOCTOR_INACTIVE", "The doctor is not active")
    dept = department or (doctor.department if doctor is not None else None)
    if dept is None and visit_type not in _NO_FEE_TYPES:
        raise DomainError("DEPARTMENT_REQUIRED", "A visit needs a department or a doctor")
    cov, card = _visit_coverage(
        patient, coverage, use_default_coverage, card_number, timezone.localdate(at)
    )

    policy = Policy.load()
    origin = None
    if visit_type in (VisitType.NEW, VisitType.FOLLOW_UP):
        origin = follow_up_origin(
            patient,
            doctor=doctor,
            department=dept,
            at=at,
            window_days=policy.follow_up_window_days,
        )
    vtype = VisitType.FOLLOW_UP if origin is not None else visit_type

    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create visit"):
        if appointment is not None:
            appt = Appointment.objects.select_for_update().get(pk=appointment.pk)
            if appt.status != AppointmentStatus.BOOKED:
                raise DomainError("APPOINTMENT_NOT_BOOKED", "The appointment is not open")
        visit = Visit.objects.create(
            number=next_number("VIS"),
            patient=patient,
            visit_type=vtype,
            department=dept,
            doctor=doctor,
            payer=cov.payer if cov is not None else None,
            coverage=cov,
            card_number=card,
            follow_up_of=origin,
            appointment=appointment,
            chief_complaint=chief_complaint.strip()[:300],
            created_by=actor,
        )
        if appointment is not None:
            Appointment.objects.filter(pk=appointment.pk).update(
                status=AppointmentStatus.ARRIVED, updated_at=at
            )
        free_follow_up = origin is not None and policy.follow_up_discount_percent >= 100
        fee_service = doctor.consultation_service if doctor is not None else None
        if fee_service is not None and vtype not in _NO_FEE_TYPES and not free_follow_up:
            _orders().create_service_lines(
                visit,
                [
                    {
                        "service": fee_service,
                        "quantity": Decimal(1),
                        "order_source": OrderSource.CONSULTATION_FEE,
                    }
                ],
                actor,
            )
        if dept is not None and vtype not in _NO_FEE_TYPES:
            enqueue(
                visit,
                actor=actor,
                priority=EMERGENCY_PRIORITY if vtype == VisitType.EMERGENCY else 0,
                room=room,
                on=timezone.localdate(at),
            )
    return visit


def close_visit(visit: Visit, *, actor: User, now: datetime | None = None) -> Visit:
    """Close an open visit (the doctor or discharge finished it)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="close visit"):
        locked = Visit.objects.select_for_update(no_key=True).get(pk=visit.pk)
        if locked.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "Only an open visit can be closed")
        locked.status = VisitStatus.CLOSED
        locked.closed_at = _now(now)
        locked.closed_by = actor
        locked.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    return locked


def cancel_visit(
    visit: Visit,
    *,
    actor: User,
    reason_code: str,
    note: str = "",
    line_reason_code: str = "PATIENT_REFUSED",
    now: datetime | None = None,
    approver: User | None = None,
) -> Visit:
    """Cancel a visit with a reason (FEATURES 2.7, invariant 4).

    Every open service line is cancelled through ``orders.services.cancel_line``, which issues
    the credit note (approved by ``approver``, default the actor, holding
    ``billing.approve_credit_note``) and so the refundable patient credit for invoiced or
    paid lines. A visit with performed work, or with dispensed units, cannot be cancelled:
    credit those lines instead.

    Raises:
        PermissionRequired: a paid line's approver lacks ``billing.approve_credit_note``.
        DomainError: ``VISIT_NOT_OPEN``, ``REASON_UNKNOWN``, ``REASON_NOTE_REQUIRED``,
            ``VISIT_HAS_PERFORMED_WORK``.
    """
    reason = resolve_reason(reason_code, "visit_cancel", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"cancel visit: {note}"):
        _orders().lock_patient(visit.patient_id)  # the money engine's lock order
        locked = Visit.objects.select_for_update(no_key=True).get(pk=visit.pk)
        if locked.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "Only an open visit can be cancelled")
        # Queue entries before service lines: the order finish_consultation uses too.
        entries = list(
            QueueEntry.objects.select_for_update()
            .filter(visit=locked, status__in=[*ACTIVE_QUEUE_STATUSES, QueueStatus.NO_SHOW])
            .order_by("id")
        )
        lines = list(ServiceLine.objects.select_for_update().filter(visit=locked).order_by("id"))
        if any(
            ln.fulfilment_status == FulfilmentStatus.PERFORMED or _orders().given_units(ln) > 0
            for ln in lines
        ):
            raise DomainError(
                "VISIT_HAS_PERFORMED_WORK", "Performed work must be credited, not cancelled"
            )
        line_reason = resolve_reason(line_reason_code, "line_cancel", note)
        for line in lines:
            if line.fulfilment_status in (FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS):
                _orders().cancel_line(line, line_reason, actor, note=note, approver=approver)
        for entry in entries:
            entry.status = QueueStatus.CANCELLED
            entry.save(update_fields=["status"])
        locked.status = VisitStatus.CANCELLED
        locked.cancelled_at = _now(now)
        locked.cancelled_by = actor
        locked.cancel_reason = reason
        locked.cancel_note = note.strip()
        locked.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by",
                "cancel_reason",
                "cancel_note",
                "updated_at",
            ]
        )
    return locked


# --- queue ----------------------------------------------------------------------------------


def _unpaid_consultation() -> Exists:
    return Exists(
        ServiceLine.objects.filter(
            visit_id=OuterRef("visit_id"),
            order_source=OrderSource.CONSULTATION_FEE,
            fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        )
        .exclude(billing_status=BillingStatus.SETTLED)
        .exclude(authorization__isnull=False, authorization__revoked_at__isnull=True)
    )


def queue(
    *,
    department: Department | None = None,
    doctor: DoctorProfile | None = None,
    on: date | None = None,
    include_not_ready: bool = False,
    statuses: Sequence[str] = tuple(ACTIVE_QUEUE_STATUSES),
) -> QuerySet[QueueEntry]:
    """Queue entries of the day, in serving order, annotated with ``ready``.

    By default only ready entries (paid or authorized consultation, or none due) are listed.
    """
    qs = (
        QueueEntry.objects.filter(queue_date=on or timezone.localdate(), status__in=statuses)
        .select_related("visit", "visit__patient")
        .annotate(blocked=_unpaid_consultation())
    )
    if department is not None:
        qs = qs.filter(department=department)
    if doctor is not None:
        qs = qs.filter(Q(doctor=doctor) | Q(doctor__isnull=True))
    if not include_not_ready:
        qs = qs.filter(blocked=False)
    return qs.order_by("-priority", "token_no")


def is_ready(entry: QueueEntry) -> bool:
    return not QueueEntry.objects.filter(pk=entry.pk).filter(_unpaid_consultation()).exists()


def enqueue(
    visit: Visit,
    *,
    actor: User,
    priority: int = 0,
    room: Room | None = None,
    on: date | None = None,
) -> QueueEntry:
    """Give the visit the next token of its department for the day."""
    if visit.department_id is None:
        raise DomainError("DEPARTMENT_REQUIRED", "Queue tokens belong to a department")
    day = on or timezone.localdate()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="enqueue"):
        # Serializes token numbering per department.
        Department.objects.select_for_update().get(pk=visit.department_id)
        if QueueEntry.objects.filter(visit=visit, status__in=ACTIVE_QUEUE_STATUSES).exists():
            raise DomainError("ALREADY_QUEUED", "The visit is already in the queue")
        last = QueueEntry.objects.filter(
            department_id=visit.department_id, queue_date=day
        ).aggregate(m=Max("token_no"))["m"]
        return QueueEntry.objects.create(
            visit=visit,
            department_id=visit.department_id,
            doctor=visit.doctor,
            room=room,
            queue_date=day,
            token_no=(last or 0) + 1,
            priority=priority,
        )


def _move(entry: QueueEntry, to: str, actor: User, *, need_ready: bool = False) -> QueueEntry:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"queue {to}"):
        locked = QueueEntry.objects.select_for_update().get(pk=entry.pk)
        if to not in QUEUE_TRANSITIONS[locked.status]:
            raise DomainError(
                "QUEUE_TRANSITION_INVALID",
                "This queue move is not allowed",
                status=locked.status,
                to=to,
            )
        if need_ready and not is_ready(locked):
            raise DomainError(
                "QUEUE_NOT_READY", "The consultation fee is neither paid nor authorized"
            )
        now = timezone.now()
        locked.status = to
        fields = ["status"]
        if to == QueueStatus.CALLED:
            locked.called_at, locked.called_by = now, actor
            fields += ["called_at", "called_by"]
        elif to == QueueStatus.IN_PROGRESS:
            locked.started_at = now
            fields.append("started_at")
        elif to == QueueStatus.DONE:
            locked.done_at = now
            fields.append("done_at")
        locked.save(update_fields=fields)
    return locked


def call_patient(entry: QueueEntry, *, actor: User) -> QueueEntry:
    return _move(entry, QueueStatus.CALLED, actor, need_ready=True)


def start_consultation(entry: QueueEntry, *, actor: User) -> QueueEntry:
    return _move(entry, QueueStatus.IN_PROGRESS, actor, need_ready=True)


def finish_consultation(entry: QueueEntry, *, actor: User) -> QueueEntry:
    """Done with the doctor: the consultation line is performed (FLOW step 3).

    Locks the visit first (then the queue entry, then the lines), the order cancel_visit
    uses, so a cancellation and a finish serialize instead of deadlocking.
    """
    with transaction.atomic():
        visit_id = QueueEntry.objects.filter(pk=entry.pk).values_list("visit_id", flat=True).get()
        Visit.objects.select_for_update(no_key=True).filter(pk=visit_id).first()
        done = _move(entry, QueueStatus.DONE, actor)
        open_fees = ServiceLine.objects.filter(
            visit_id=done.visit_id,
            order_source=OrderSource.CONSULTATION_FEE,
            fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        ).order_by("id")
        for line in open_fees:
            _orders().perform_line(line, actor)
    return done


def mark_no_show(entry: QueueEntry, *, actor: User) -> QueueEntry:
    return _move(entry, QueueStatus.NO_SHOW, actor)


def requeue(entry: QueueEntry, *, actor: User) -> QueueEntry:
    """Back to waiting (called but not seen yet, or a no-show who came back)."""
    return _move(entry, QueueStatus.WAITING, actor)


def cancel_queue_entry(entry: QueueEntry, *, actor: User) -> QueueEntry:
    return _move(entry, QueueStatus.CANCELLED, actor)


# --- appointments ---------------------------------------------------------------------------


def _slot_minutes(doctor: DoctorProfile, start: datetime) -> int:
    local = timezone.localtime(start)
    sched = (
        DoctorSchedule.objects.filter(doctor=doctor, weekday=local.weekday(), active=True)
        .filter(start_time__lte=local.time(), end_time__gt=local.time())
        .first()
    )
    return sched.slot_minutes if sched is not None else DEFAULT_SLOT_MINUTES


def _within_schedule(doctor: DoctorProfile, start: datetime, end: datetime) -> bool:
    schedules = DoctorSchedule.objects.filter(doctor=doctor, active=True)
    if not schedules.exists():
        return True  # no schedule configured: any slot is bookable
    s, e = timezone.localtime(start), timezone.localtime(end)
    if s.date() != e.date() and e.time() != time(0, 0):
        return False
    day = s.date()
    return (
        schedules.filter(weekday=s.weekday(), start_time__lte=s.time(), end_time__gte=e.time())
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=day))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=day))
        .exists()
    )


def _check_slot(
    doctor: DoctorProfile, start: datetime, end: datetime, *, exclude_id: int | None = None
) -> None:
    if end <= start:
        raise DomainError("INVALID_SLOT", "An appointment ends after it starts")
    if not _within_schedule(doctor, start, end):
        raise DomainError("OUTSIDE_SCHEDULE", "The doctor does not work at that time")
    clash = Appointment.objects.filter(
        doctor=doctor, status=AppointmentStatus.BOOKED, starts_at__lt=end, ends_at__gt=start
    )
    if exclude_id is not None:
        clash = clash.exclude(pk=exclude_id)
    if clash.exists():
        raise DomainError(
            "APPOINTMENT_CONFLICT",
            "The doctor already has an appointment in that slot",
            appointments=list(clash.values_list("pk", flat=True)),
        )


def book_appointment(
    *,
    doctor: DoctorProfile,
    starts_at: datetime,
    actor: User,
    ends_at: datetime | None = None,
    patient: Patient | None = None,
    contact_name: str = "",
    contact_phone: str = "",
    department: Department | None = None,
    notes: str = "",
    rescheduled_from: Appointment | None = None,
) -> Appointment:
    """Book a slot (FEATURES 2.5). Overlapping booked slots of the doctor are refused.

    Raises:
        DomainError: ``PATIENT_OR_CONTACT_REQUIRED``, ``INVALID_SLOT``, ``OUTSIDE_SCHEDULE``,
            ``APPOINTMENT_CONFLICT``, ``APPOINTMENT_IN_PAST``, ``DOCTOR_INACTIVE``.
    """
    if patient is None and not contact_name.strip():
        raise DomainError("PATIENT_OR_CONTACT_REQUIRED", "Book for a patient or a named contact")
    if not doctor.active:
        raise DomainError("DOCTOR_INACTIVE", "The doctor is not active")
    if starts_at < timezone.now() - timedelta(minutes=5):
        raise DomainError("APPOINTMENT_IN_PAST", "Appointments are booked in the future")
    end = ends_at or starts_at + timedelta(minutes=_slot_minutes(doctor, starts_at))
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="book appointment"):
        # One booking at a time per doctor, so two clerks cannot take the same slot.
        DoctorProfile.objects.select_for_update().get(pk=doctor.pk)
        _check_slot(doctor, starts_at, end)
        return Appointment.objects.create(
            patient=patient,
            contact_name=contact_name.strip(),
            contact_phone=contact_phone.strip(),
            doctor=doctor,
            department=department or doctor.department,
            starts_at=starts_at,
            ends_at=end,
            notes=notes.strip()[:300],
            created_by=actor,
            rescheduled_from=rescheduled_from,
        )


def _booked(appointment: Appointment) -> Appointment:
    locked = Appointment.objects.select_for_update().get(pk=appointment.pk)
    if locked.status != AppointmentStatus.BOOKED:
        raise DomainError("APPOINTMENT_NOT_BOOKED", "The appointment is not open")
    return locked


def reschedule_appointment(
    appointment: Appointment,
    *,
    starts_at: datetime,
    actor: User,
    ends_at: datetime | None = None,
) -> Appointment:
    """Move a booking: the old one becomes ``rescheduled`` and links to the new one."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="reschedule"):
        old = _booked(appointment)
        duration = old.ends_at - old.starts_at
        old.status = AppointmentStatus.RESCHEDULED
        old.save(update_fields=["status", "updated_at"])
        return book_appointment(
            doctor=old.doctor,
            starts_at=starts_at,
            ends_at=ends_at or starts_at + duration,
            actor=actor,
            patient=old.patient,
            contact_name=old.contact_name,
            contact_phone=old.contact_phone,
            department=old.department,
            notes=old.notes,
            rescheduled_from=old,
        )


def cancel_appointment(appointment: Appointment, *, actor: User, note: str = "") -> Appointment:
    """Cancel a booking with the reason the caller gave (invariant 4: reason, who, when).

    Raises:
        DomainError: ``APPOINTMENT_NOT_BOOKED``, ``REASON_REQUIRED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cancel appointment"):
        locked = _booked(appointment)
        if not note.strip():
            raise DomainError("REASON_REQUIRED", "Say why the appointment is cancelled")
        locked.status = AppointmentStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.cancelled_by = actor
        locked.cancel_note = note.strip()[:300]
        locked.save(
            update_fields=["status", "cancelled_at", "cancelled_by", "cancel_note", "updated_at"]
        )
    return locked


def mark_appointment_no_show(appointment: Appointment, *, actor: User) -> Appointment:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="appointment no show"):
        locked = _booked(appointment)
        locked.status = AppointmentStatus.NO_SHOW
        locked.save(update_fields=["status", "updated_at"])
    return locked


def convert_appointment(
    appointment: Appointment, *, actor: User, patient: Patient | None = None, **visit_kwargs: Any
) -> Visit:
    """The patient arrived: open the visit from the booking (a contact needs a file first)."""
    who = patient or appointment.patient
    if who is None:
        raise DomainError("PATIENT_REQUIRED", "Register the caller before opening the visit")
    if patient is not None and appointment.patient_id not in (None, patient.pk):
        raise DomainError("APPOINTMENT_PATIENT_MISMATCH", "The booking is for another patient")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="convert appointment"):
        if appointment.patient_id is None:
            Appointment.objects.filter(pk=appointment.pk).update(patient=who)
        return create_visit(
            patient=who,
            actor=actor,
            doctor=appointment.doctor,
            department=appointment.department,
            appointment=appointment,
            **visit_kwargs,
        )


def available_slots(doctor: DoctorProfile, on: date) -> list[tuple[datetime, datetime]]:
    """Free slots of the doctor's schedule on ``on`` (empty without a schedule)."""
    tz = timezone.get_current_timezone()
    booked = list(
        Appointment.objects.filter(
            doctor=doctor,
            status=AppointmentStatus.BOOKED,
            starts_at__date__lte=on,
            ends_at__date__gte=on,
        ).values_list("starts_at", "ends_at")
    )
    out: list[tuple[datetime, datetime]] = []
    schedules = (
        DoctorSchedule.objects.filter(doctor=doctor, weekday=on.weekday(), active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on))
        .order_by("start_time")
    )
    for sched in schedules:
        start = datetime.combine(on, sched.start_time, tzinfo=tz)
        stop = datetime.combine(on, sched.end_time, tzinfo=tz)
        step = timedelta(minutes=sched.slot_minutes)
        while start + step <= stop:
            end = start + step
            if not any(s < end and e > start for s, e in booked):
                out.append((start, end))
            start = end
    return out


# --- minimal inpatient ----------------------------------------------------------------------


def bed_charge_dates(
    admitted_on: date, *, through: date, discharged_on: date | None = None
) -> list[date]:
    """Bed nights to charge (midnight census), each identified by the date it starts.

    While admitted, every night that has passed by ``through`` (admission date up to the day
    before ``through``). At discharge, every date from admission up to the day before the
    discharge date, and at least the admission date (a same-day stay is one day).
    """
    if discharged_on is not None:
        last = max(admitted_on, discharged_on - timedelta(days=1))
    else:
        last = through - timedelta(days=1)
    if last < admitted_on:
        return []
    return [admitted_on + timedelta(days=i) for i in range((last - admitted_on).days + 1)]


def _free_bed(bed: Bed) -> Bed:
    locked = Bed.objects.select_for_update().get(pk=bed.pk)
    if not locked.active or locked.status != BedStatus.AVAILABLE:
        raise DomainError("BED_NOT_AVAILABLE", "The bed is not available", bed=locked.code)
    if locked.bed_service.kind != ServiceKind.BED:
        raise DomainError("BED_SERVICE_INVALID", "The bed's charge service must be a bed day")
    return locked


def admit(
    visit: Visit,
    *,
    doctor: DoctorProfile,
    bed: Bed,
    actor: User,
    diagnosis: str = "",
    at: datetime | None = None,
) -> Admission:
    """Admit the visit's patient to a bed (FEATURES 10.5). Nights are charged afterwards.

    Raises:
        DomainError: ``VISIT_NOT_OPEN``, ``ALREADY_ADMITTED``, ``BED_NOT_AVAILABLE``,
            ``BED_SERVICE_INVALID``, ``PATIENT_ALREADY_ADMITTED``.
    """
    when = _now(at)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="admit"):
        # The patient first: two admissions of one patient serialize here (and the partial
        # unique index on open admissions per patient is the backstop).
        _orders().lock_patient(visit.patient_id)
        locked = Visit.objects.select_for_update(no_key=True).get(pk=visit.pk)
        if locked.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "Only an open visit can be admitted")
        if Admission.objects.filter(visit=locked).exists():
            raise DomainError("ALREADY_ADMITTED", "The visit already has an admission")
        if Admission.objects.filter(
            patient_id=locked.patient_id, status=AdmissionStatus.ADMITTED
        ).exists():
            raise DomainError("PATIENT_ALREADY_ADMITTED", "The patient is already admitted")
        free = _free_bed(bed)
        number = next_number("ADM")
        authorization = _orders().authorize_stay(
            locked,
            actor=actor,
            note=f"inpatient stay {number}: bed nights are charged in arrears",
        )
        admission = Admission.objects.create(
            number=number,
            visit=locked,
            patient_id=locked.patient_id,
            authorization=authorization,
            admitting_doctor=doctor,
            admission_diagnosis=diagnosis.strip()[:300],
            admitted_at=when,
            admitted_by=actor,
        )
        BedStay.objects.create(admission=admission, bed=free, started_at=when, created_by=actor)
        free.status = BedStatus.OCCUPIED
        free.save(update_fields=["status"])
    return admission


def _stay_for(admission: Admission, day: date) -> BedStay:
    end_of_day = datetime.combine(day, time.max, tzinfo=timezone.get_current_timezone())
    stay = (
        BedStay.objects.filter(admission=admission, started_at__lte=end_of_day)
        .order_by("-started_at", "-id")
        .first()
    )
    if stay is None:  # pragma: no cover - an admission always starts with a stay
        raise DomainError("BED_STAY_MISSING", "No bed stay covers that date")
    return stay


def charge_bed_days(
    admission: Admission, *, actor: User, through: date | None = None
) -> list[BedCharge]:
    """Create the missing bed night lines (idempotent; run daily and at discharge).

    ``through`` defaults to today: the nights before today are charged. Each date is charged
    at the bed occupied at the end of that day.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="bed charges"):
        locked = Admission.objects.select_for_update().get(pk=admission.pk)
        admitted_on = timezone.localdate(locked.admitted_at)
        discharged_on = (
            timezone.localdate(locked.discharged_at) if locked.discharged_at is not None else None
        )
        if locked.status == AdmissionStatus.CANCELLED:
            return []
        dates = bed_charge_dates(
            admitted_on,
            through=through or timezone.localdate(),
            discharged_on=discharged_on,
        )
        charged = set(
            BedCharge.objects.filter(admission=locked).values_list("charge_date", flat=True)
        )
        created: list[BedCharge] = []
        tz = timezone.get_current_timezone()
        for day in dates:
            if day in charged:
                continue
            stay = _stay_for(locked, day)
            # The night was given under the admission's authorization: performed now,
            # invoiced afterwards (invariant 1's documented exception).
            night_end = min(
                datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz), timezone.now()
            )
            lines = _orders().order_performed(
                locked.visit,
                [
                    {
                        "service": stay.bed.bed_service,
                        "quantity": Decimal(1),
                        "order_source": OrderSource.BED_CHARGE,
                        "note": f"bed {stay.bed.code} {day.isoformat()}",
                    }
                ],
                actor,
                authorization=_stay_authorization(locked, actor),
                at=night_end,
            )
            created.append(
                BedCharge.objects.create(
                    admission=locked, bed_stay=stay, charge_date=day, service_line=lines[0]
                )
            )
    return created


def _stay_authorization(admission: Admission, actor: User) -> Any:
    """The admission's perform-first authorization (created for admissions made before it
    was recorded at admission)."""
    if admission.authorization_id is None:
        admission.authorization = _orders().authorize_stay(
            admission.visit,
            actor=actor,
            note=f"inpatient stay {admission.number}: bed nights are charged in arrears",
        )
        admission.save(update_fields=["authorization", "updated_at"])
    return admission.authorization


def transfer_bed(
    admission: Admission, *, bed: Bed, actor: User, at: datetime | None = None
) -> BedStay:
    """Move an admitted patient to another bed."""
    when = _now(at)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="bed transfer"):
        locked = Admission.objects.select_for_update().get(pk=admission.pk)
        if locked.status != AdmissionStatus.ADMITTED:
            raise DomainError("NOT_ADMITTED", "The patient is not admitted")
        current = BedStay.objects.select_for_update().get(admission=locked, ended_at__isnull=True)
        if current.bed_id == bed.pk:
            raise DomainError("SAME_BED", "The patient is already in this bed")
        free = _free_bed(bed)
        if when <= current.started_at:
            raise DomainError("INVALID_TIME", "A transfer happens after the current stay began")
        current.ended_at = when
        current.save(update_fields=["ended_at"])
        Bed.objects.filter(pk=current.bed_id).update(status=BedStatus.AVAILABLE)
        stay = BedStay.objects.create(admission=locked, bed=free, started_at=when, created_by=actor)
        free.status = BedStatus.OCCUPIED
        free.save(update_fields=["status"])
    return stay


def discharge(
    admission: Admission, *, actor: User, summary: str = "", at: datetime | None = None
) -> Admission:
    """Discharge: charge the remaining bed days, free the bed, close the visit."""
    when = _now(at)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="discharge"):
        locked = Admission.objects.select_for_update().get(pk=admission.pk)
        if locked.status != AdmissionStatus.ADMITTED:
            raise DomainError("NOT_ADMITTED", "The patient is not admitted")
        if when < locked.admitted_at:
            raise DomainError("INVALID_TIME", "Discharge happens after admission")
        stay = BedStay.objects.select_for_update().get(admission=locked, ended_at__isnull=True)
        stay.ended_at = max(when, stay.started_at + timedelta(seconds=1))
        stay.save(update_fields=["ended_at"])
        Bed.objects.filter(pk=stay.bed_id).update(status=BedStatus.AVAILABLE)
        locked.status = AdmissionStatus.DISCHARGED
        locked.discharged_at = when
        locked.discharged_by = actor
        locked.discharge_summary = summary
        locked.save(
            update_fields=[
                "status",
                "discharged_at",
                "discharged_by",
                "discharge_summary",
                "updated_at",
            ]
        )
        charge_bed_days(locked, actor=actor, through=timezone.localdate(when))
        visit = Visit.objects.get(pk=locked.visit_id)
        if visit.status == VisitStatus.OPEN:
            close_visit(visit, actor=actor, now=when)
    return locked


def change_coverage(
    visit: Visit,
    *,
    actor: User,
    note: str,
    coverage: PatientCoverage | None = None,
    card_number: str = "",
) -> Visit:
    """Change who pays for an open visit (a card shown after ordering; FEATURES 2.1, 5.6).

    The visit's payer, coverage and card change, and every unbilled line moves to the new
    payer (``orders.services.set_line_payer``), leaving draft invoices to be priced again.
    Invoiced lines keep their payer (correct them with a credit note).

    Raises:
        DomainError: ``VISIT_NOT_OPEN``, ``REASON_REQUIRED``, ``COVERAGE_INVALID``,
            ``CARD_NUMBER_REQUIRED``, ``PAYER_CONTRACT_EXPIRED``.
    """
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the visit's coverage changes")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"coverage: {text}"):
        _orders().lock_patient(visit.patient_id)
        locked = (
            Visit.objects.select_for_update(no_key=True).select_related("patient").get(pk=visit.pk)
        )
        if locked.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "Only an open visit can change coverage")
        cov, card = _visit_coverage(
            locked.patient, coverage, False, card_number, timezone.localdate(locked.created_at)
        )
        locked.coverage = cov
        locked.payer = cov.payer if cov is not None else None
        locked.card_number = card
        locked.save(update_fields=["coverage", "payer", "card_number", "updated_at"])
        for line in ServiceLine.objects.filter(
            visit=locked, billing_status=BillingStatus.UNBILLED
        ).exclude(fulfilment_status=FulfilmentStatus.CANCELLED):
            if line.payer_id != locked.payer_id:
                _orders().set_line_payer(line, payer=locked.payer, actor=actor, note=text)
    return locked


def reassign_future_appointments(source: Patient, target: Patient, *, actor: User) -> int:
    """Move a merged file's future booked appointments to the surviving file (FEATURES 1.4).

    Called by ``apps.patients.services.merge_patients``. Returns how many moved.
    """
    moved = 0
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="merge: appointments"):
        for appt in Appointment.objects.select_for_update().filter(
            patient=source, status=AppointmentStatus.BOOKED, starts_at__gte=timezone.now()
        ):
            appt.patient = target
            appt.save(update_fields=["patient", "updated_at"])
            moved += 1
    return moved


def create_bed(
    *,
    code: str,
    name_ar: str,
    name_en: str,
    bed_service: Service,
    actor: User,
    room: Room | None = None,
) -> Bed:
    """A bed charged with a ``bed`` catalog service per night (FEATURES 10.5)."""
    if bed_service.kind != ServiceKind.BED:
        raise DomainError("BED_SERVICE_INVALID", "The bed's charge service must be a bed day")
    if Bed.objects.filter(code=code.strip()).exists():
        raise DomainError("BED_EXISTS", "A bed with this code exists", bed_code=code)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create bed"):
        return Bed.objects.create(
            code=code.strip(),
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            room=room,
            bed_service=bed_service,
        )


# --- visit timeline -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    at: datetime
    kind: str
    ref_id: int
    actor_id: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


#: Event kinds that carry money; left out of the doctor's view (FEATURES 3.8).
FINANCIAL_EVENTS = frozenset({"invoice_approved", "payment_allocated", "credit_note", "refund"})


def timeline(visit: Visit, *, include_financial: bool = True) -> list[TimelineEvent]:
    """Everything that happened on a visit, oldest first (FEATURES 2.4): orders, invoices,
    payments, results, dispenses, credit notes, refunds, admission and closing.
    """
    from apps.billing.models import CreditNote, DocumentStatus, Invoice
    from apps.lab.models import ResultStatus, ResultVersion
    from apps.payments.models import Allocation, Refund
    from apps.pharmacy.models import Dispense

    visit = Visit.objects.get(pk=visit.pk)  # fresh status and timestamps
    events = [TimelineEvent(visit.created_at, "visit_created", visit.pk, visit.created_by_id)]
    for line in ServiceLine.objects.filter(visit=visit).select_related("service").order_by("id"):
        service = {
            "service_id": line.service_id,
            "service_code": line.service.code,
            "service_name_ar": line.service.name_ar,
            "service_name_en": line.service.name_en,
            "kind": line.kind,
        }
        events.append(
            TimelineEvent(line.ordered_at, "line_ordered", line.pk, line.ordered_by_id, service)
        )
        if line.performed_at is not None:
            events.append(
                TimelineEvent(
                    line.performed_at, "line_performed", line.pk, line.performed_by_id, service
                )
            )
        if line.cancelled_at is not None:
            events.append(
                TimelineEvent(
                    line.cancelled_at, "line_cancelled", line.pk, line.cancelled_by_id, service
                )
            )
    for version in ResultVersion.objects.filter(
        result_set__service_line__visit=visit,
        status__in=[ResultStatus.APPROVED, ResultStatus.AMENDED],
    ).select_related("result_set__service_line__service"):
        tested = version.result_set.service_line.service
        events.append(
            TimelineEvent(
                version.approved_at or version.entered_at,
                "result_approved",
                version.pk,
                version.approved_by_id,
                {
                    "service_line_id": version.result_set.service_line_id,
                    "version": version.version_no,
                    "service_code": tested.code,
                    "service_name_ar": tested.name_ar,
                    "service_name_en": tested.name_en,
                },
            )
        )
    for dispense in Dispense.objects.filter(visit=visit):
        events.append(
            TimelineEvent(dispense.dispensed_at, "dispensed", dispense.pk, dispense.dispensed_by_id)
        )
    if include_financial:
        invoices = Invoice.objects.filter(visit=visit, status=DocumentStatus.APPROVED)
        for inv in invoices:
            events.append(
                TimelineEvent(
                    inv.approved_at or inv.created_at,
                    "invoice_approved",
                    inv.pk,
                    inv.approved_by_id,
                    {"number": inv.number, "patient_total": str(inv.patient_total)},
                )
            )
        for alloc in Allocation.objects.filter(invoice__in=invoices):
            events.append(
                TimelineEvent(
                    alloc.created_at,
                    "payment_allocated",
                    alloc.pk,
                    alloc.created_by_id,
                    {"invoice_id": alloc.invoice_id, "amount": str(alloc.amount)},
                )
            )
        for cn in CreditNote.objects.filter(invoice__in=invoices, status=DocumentStatus.APPROVED):
            events.append(
                TimelineEvent(
                    cn.approved_at or cn.created_at,
                    "credit_note",
                    cn.pk,
                    cn.approved_by_id,
                    {"number": cn.number, "patient_total": str(cn.patient_total)},
                )
            )
        for refund in Refund.objects.filter(
            Q(credit_note__invoice__visit=visit) | Q(service_line__visit=visit)
        ).distinct():
            events.append(
                TimelineEvent(
                    refund.requested_at,
                    "refund",
                    refund.pk,
                    refund.requested_by_id,
                    {"amount": str(refund.amount), "status": refund.status},
                )
            )
    admission = Admission.objects.filter(visit=visit).first()
    if admission is not None:
        events.append(
            TimelineEvent(admission.admitted_at, "admitted", admission.pk, admission.admitted_by_id)
        )
        if admission.discharged_at is not None:
            events.append(
                TimelineEvent(
                    admission.discharged_at, "discharged", admission.pk, admission.discharged_by_id
                )
            )
    if visit.closed_at is not None:
        events.append(TimelineEvent(visit.closed_at, "visit_closed", visit.pk, visit.closed_by_id))
    if visit.cancelled_at is not None:
        events.append(
            TimelineEvent(visit.cancelled_at, "visit_cancelled", visit.pk, visit.cancelled_by_id)
        )
    return sorted(events, key=lambda e: (e.at, e.kind, e.ref_id))


@dataclass(frozen=True, slots=True)
class TimelineItem:
    """A timeline event with the user who did it."""

    event: TimelineEvent
    actor: User | None


def timeline_view(visit: Visit, *, include_financial: bool) -> list[TimelineItem]:
    """:func:`timeline` with the acting users loaded in one query (FEATURES 2.4)."""
    events = timeline(visit, include_financial=include_financial)
    users = User.objects.in_bulk({e.actor_id for e in events if e.actor_id is not None})
    return [
        TimelineItem(e, users.get(e.actor_id) if e.actor_id is not None else None) for e in events
    ]


# --- reception screens: reference data, visit lists, queue board, display, token slip -------


@dataclass(frozen=True, slots=True)
class VisitOptions:
    """What the create-visit form chooses from."""

    departments: list[Department]
    doctors: list[DoctorProfile]
    cancel_reasons: list[ReasonCode]
    follow_up_window_days: int


def visit_options() -> VisitOptions:
    """Active departments and doctors, visit cancellation reasons and the follow-up window."""
    return VisitOptions(
        departments=list(Department.objects.filter(active=True).order_by("sort_order", "code")),
        doctors=list(
            DoctorProfile.objects.filter(active=True, user__is_active=True)
            .select_related("user", "department", "consultation_service")
            .order_by("department__sort_order", "department__code", "user__username")
        ),
        cancel_reasons=list(
            ReasonCode.objects.filter(category=ReasonCategory.VISIT_CANCEL, active=True).order_by(
                "sort_order", "code"
            )
        ),
        follow_up_window_days=Policy.load().follow_up_window_days,
    )


def _visit_rows() -> QuerySet[Visit]:
    return Visit.objects.select_related(
        "patient",
        "department",
        "doctor__user",
        "payer",
        "follow_up_of",
        "cancel_reason",
        "created_by",
    )


def visit_list(
    *,
    patient: Patient | None = None,
    on: date | None = None,
    department: Department | None = None,
    doctor: DoctorProfile | None = None,
    status: str | None = None,
) -> QuerySet[Visit]:
    """Visits, newest first: of a person (every merged file), a day, a department or doctor."""
    qs = _visit_rows()
    if patient is not None:
        qs = qs.filter(patient_id__in=patient_services.person_file_ids(patient))
    if on is not None:
        tz = timezone.get_current_timezone()
        start = datetime.combine(on, time.min, tzinfo=tz)
        qs = qs.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))
    if department is not None:
        qs = qs.filter(department=department)
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at", "-id")


@dataclass(frozen=True, slots=True)
class LineView:
    """A service line with its derived state (ARCHITECTURE 4.4); never a price."""

    line: ServiceLine
    state: str


@dataclass(frozen=True, slots=True)
class VisitView:
    visit: Visit
    lines: list[LineView]
    queue_entry: QueueEntry | None
    #: The consultation fee is paid or authorized (or none is due): the doctor may call.
    queue_ready: bool


def _entry_rows() -> QuerySet[QueueEntry]:
    return QueueEntry.objects.select_related(
        "visit", "visit__patient", "department", "doctor__user", "room"
    )


def visit_view(visit: Visit) -> VisitView:
    """A visit with its service lines' states and its latest queue entry."""
    fresh = _visit_rows().get(pk=visit.pk)
    lines = ServiceLine.objects.filter(visit=fresh).select_related("service").order_by("id")
    entry = (
        _entry_rows()
        .filter(visit=fresh)
        .exclude(status=QueueStatus.CANCELLED)
        .order_by("-queue_date", "-id")
        .first()
    )
    return VisitView(
        visit=fresh,
        lines=[LineView(line, str(_orders().line_state(line))) for line in lines],
        queue_entry=entry,
        queue_ready=entry is not None and is_ready(entry),
    )


def _ready(entry: QueueEntry) -> bool:
    """Whether a row from :func:`queue` may be called (its ``blocked`` annotation)."""
    return not bool(getattr(entry, "blocked", False))


def board(
    *,
    department: Department | None = None,
    doctor: DoctorProfile | None = None,
    on: date | None = None,
    include_finished: bool = False,
) -> QuerySet[QueueEntry]:
    """The reception board: every token of the day in serving order, paid or not.

    Active tokens always; with ``include_finished`` also no-shows and finished ones.
    Each row is annotated with ``blocked`` (consultation fee neither paid nor authorized).
    """
    statuses: list[str] = [*ACTIVE_QUEUE_STATUSES, QueueStatus.NO_SHOW]
    if include_finished:
        statuses.append(QueueStatus.DONE)
    return queue(
        department=department,
        doctor=doctor,
        on=on,
        include_not_ready=True,
        statuses=statuses,
    ).select_related("department", "doctor__user", "room")


def call_next(
    *,
    department: Department,
    actor: User,
    doctor: DoctorProfile | None = None,
    on: date | None = None,
) -> QueueEntry:
    """Call the first paid, waiting token of the department (FEATURES 2.3).

    Emergencies first, then token order (:func:`domain.queue.next_to_call`). With a doctor,
    only that doctor's tokens and tokens without a doctor. Unpaid tokens keep their place
    and are skipped (invariant 1).

    Raises:
        DomainError: ``QUEUE_EMPTY``.
    """
    day = on or timezone.localdate()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="queue call next"):
        # One caller at a time per department (the lock token numbering takes too).
        Department.objects.select_for_update().get(pk=department.pk)
        waiting = list(
            queue(
                department=department,
                doctor=doctor,
                on=day,
                include_not_ready=True,
                statuses=[QueueStatus.WAITING],
            )
        )
        chosen = dq.next_to_call(
            dq.QueueCandidate(e.pk, e.token_no, e.priority, e.status, _ready(e)) for e in waiting
        )
        if chosen is None:
            raise DomainError(
                "QUEUE_EMPTY",
                "Nobody with a paid consultation is waiting",
                department=department.code,
            )
        entry = next(e for e in waiting if e.pk == chosen.entry_id)
        return board_row(call_patient(entry, actor=actor).pk)


def board_row(entry_id: int) -> QueueEntry:
    """One queue entry as the board lists it (annotated with ``blocked``)."""
    return _entry_rows().filter(pk=entry_id).annotate(blocked=_unpaid_consultation()).get()


_QUEUE_ACTIONS = {
    "call": call_patient,
    "start": start_consultation,
    "finish": finish_consultation,
    "no_show": mark_no_show,
    "requeue": requeue,
}


def move_entry(entry: QueueEntry, action: str, *, actor: User) -> QueueEntry:
    """Apply a board action (call, start, finish, no_show, requeue) and return the row.

    Raises:
        DomainError: ``QUEUE_TRANSITION_INVALID``, ``QUEUE_NOT_READY``.
    """
    step = _QUEUE_ACTIONS.get(action)
    if step is None:
        raise DomainError(
            "QUEUE_TRANSITION_INVALID", "Unknown queue action", status=entry.status, to=action
        )
    return board_row(step(entry, actor=actor).pk)


@dataclass(frozen=True, slots=True)
class DisplayEntry:
    """One token on the waiting-room screen: the name is abbreviated (privacy)."""

    visit_id: int
    token_no: int
    name_ar: str
    name_en: str
    status: str
    department: Department
    doctor: DoctorProfile | None
    room: Room | None
    called_at: datetime | None


@dataclass(frozen=True, slots=True)
class WaitingRoom:
    #: Called or with the doctor, the latest call first.
    serving: list[DisplayEntry]
    #: Paid tokens still waiting, in serving order.
    waiting: list[DisplayEntry]


def _display(entry: QueueEntry) -> DisplayEntry:
    patient = entry.visit.patient
    return DisplayEntry(
        visit_id=entry.visit_id,
        token_no=entry.token_no,
        name_ar=dq.abbreviate_name(patient.full_name_ar or patient.full_name_en),
        name_en=dq.abbreviate_name(patient.full_name_en or patient.full_name_ar),
        status=entry.status,
        department=entry.department,
        doctor=entry.doctor,
        room=entry.room,
        called_at=entry.called_at,
    )


def waiting_room(*, department: Department | None = None, on: date | None = None) -> WaitingRoom:
    """The waiting-room display feed (FEATURES 2.3): paid tokens only, names abbreviated."""
    rows = [
        _display(e)
        for e in queue(department=department, on=on).select_related(
            "department", "doctor__user", "room"
        )
    ]
    serving = [r for r in rows if r.status in (QueueStatus.CALLED, QueueStatus.IN_PROGRESS)]
    serving.sort(
        key=lambda r: (r.called_at.timestamp() if r.called_at else 0.0, r.token_no), reverse=True
    )
    return WaitingRoom(
        serving=serving, waiting=[r for r in rows if r.status == QueueStatus.WAITING]
    )


@dataclass(frozen=True, slots=True)
class TokenSlip:
    """What the 80 mm token slip prints (FEATURES 2.6)."""

    entry: QueueEntry
    #: Tokens still waiting or called that are served before this one.
    ahead: int
    center: CenterProfile


def token_slip(entry: QueueEntry) -> TokenSlip:
    fresh = _entry_rows().get(pk=entry.pk)
    same_day = QueueEntry.objects.filter(
        department_id=fresh.department_id,
        queue_date=fresh.queue_date,
        status__in=ACTIVE_QUEUE_STATUSES,
    )
    candidates = [dq.QueueCandidate(e.pk, e.token_no, e.priority, e.status, True) for e in same_day]
    return TokenSlip(
        entry=fresh, ahead=dq.tokens_ahead(candidates, fresh.pk), center=CenterProfile.load()
    )


# --- appointment day view -------------------------------------------------------------------

#: Appointment statuses that keep their slot on the day view.
_HOLDS_SLOT = frozenset(
    {AppointmentStatus.BOOKED, AppointmentStatus.ARRIVED, AppointmentStatus.NO_SHOW}
)


@dataclass(frozen=True, slots=True)
class AgendaItem:
    """A free slot (``appointment`` is None) or an appointment on the doctor's day."""

    starts_at: datetime
    ends_at: datetime
    appointment: Appointment | None


@dataclass(frozen=True, slots=True)
class DayAgenda:
    doctor: DoctorProfile
    day: date
    #: The doctor has clinic hours that day.
    works: bool
    items: list[AgendaItem]


def _appointment_rows() -> QuerySet[Appointment]:
    return Appointment.objects.select_related(
        "patient", "department", "doctor__user", "converted_visit"
    )


def appointment_day(doctor: DoctorProfile, on: date, *, now: datetime | None = None) -> DayAgenda:
    """A doctor's day (FEATURES 2.5): free slots still ahead and every appointment, by time."""
    tz = timezone.get_current_timezone()
    start = datetime.combine(on, time.min, tzinfo=tz)
    appointments = list(
        _appointment_rows()
        .filter(doctor=doctor, starts_at__gte=start, starts_at__lt=start + timedelta(days=1))
        .order_by("starts_at", "id")
    )
    held = [(a.starts_at, a.ends_at) for a in appointments if a.status in _HOLDS_SLOT]
    moment = _now(now)
    items = [
        AgendaItem(s, e, None)
        for s, e in available_slots(doctor, on)
        if e > moment and not any(hs < e and he > s for hs, he in held)
    ]
    items.extend(AgendaItem(a.starts_at, a.ends_at, a) for a in appointments)
    items.sort(
        key=lambda i: (i.starts_at, i.appointment is not None, getattr(i.appointment, "pk", 0))
    )
    works = (
        DoctorSchedule.objects.filter(doctor=doctor, weekday=on.weekday(), active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on))
        .exists()
    )
    return DayAgenda(doctor=doctor, day=on, works=works, items=items)


def update_appointment(
    appointment: Appointment,
    *,
    actor: User,
    notes: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
) -> Appointment:
    """Edit a booking's notes or caller details (time changes go through reschedule).

    Raises:
        DomainError: ``APPOINTMENT_NOT_BOOKED``, ``PATIENT_OR_CONTACT_REQUIRED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit appointment"):
        locked = _booked(appointment)
        fields = ["updated_at"]
        if notes is not None:
            locked.notes = notes.strip()[:300]
            fields.append("notes")
        if contact_name is not None:
            locked.contact_name = " ".join(contact_name.split())[:200]
            fields.append("contact_name")
        if contact_phone is not None:
            locked.contact_phone = contact_phone.strip()[:30]
            fields.append("contact_phone")
        if locked.patient_id is None and not locked.contact_name:
            raise DomainError(
                "PATIENT_OR_CONTACT_REQUIRED", "Book for a patient or a named contact"
            )
        locked.save(update_fields=fields)
    return locked


def upcoming_appointments(patient: Patient, *, now: datetime | None = None) -> list[Appointment]:
    """Booked appointments of the person (every merged file) that have not ended yet."""
    return list(
        _appointment_rows()
        .filter(
            patient_id__in=patient_services.person_file_ids(patient),
            status=AppointmentStatus.BOOKED,
            ends_at__gt=_now(now),
        )
        .order_by("starts_at", "id")
    )
