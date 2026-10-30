"""The reception inbox of online bookings (ADR 0029 A9, D, E, F, G; plan Phase 4).

Staff with ``visits.manage_online_bookings`` list the bookings made online (by signed-in
patients, ``source = portal``, and by guests, ``source = guest``), approve or decline requests,
cancel on the booker's behalf, decline every open request of one phone at once, link a guest
booking to a patient file, and issue a new guest PIN. Every write carries the actor, the time
and the reason (invariant 4). Arrival still goes through ``visits.check_in`` /
``convert_appointment``, unchanged.

Every answer row carries a ``wa.me`` click-to-chat link built here from the booker's phone with
a prefilled bilingual status message (never the PIN); nothing is sent by the server and
nothing is recorded as sent (ADR 0029 A9).
"""

from __future__ import annotations

import secrets
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pghistory
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.core.models import CenterProfile, User
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.portal import guest
from apps.portal.models import GuestBookingAccess, PortalEventKind
from apps.portal.services import _event
from apps.visits import services as visits
from apps.visits.models import Appointment, AppointmentSource, AppointmentStatus
from domain import guest_booking as dguest
from domain.errors import DomainError

__all__ = [
    "approve",
    "cancel_on_behalf",
    "link_patient",
    "list_online_bookings",
    "reissue_pin",
    "reject",
    "reject_all_from_phone",
]

ONLINE_SOURCES = (AppointmentSource.PORTAL, AppointmentSource.GUEST)
#: Inbox filters: a status, or every online booking.
STATUSES = ("requested", "booked", "arrived", "cancelled", "rescheduled", "no_show", "all")
_LIMIT = 200


def _rows() -> QuerySet[Appointment]:
    return Appointment.objects.select_related(
        "patient",
        "department",
        "doctor__user",
        "doctor__department",
        "converted_visit",
        "cancel_reason",
        "approved_by",
        "guest_access",
    )


def _access(a: Appointment) -> GuestBookingAccess | None:
    try:
        return a.guest_access
    except GuestBookingAccess.DoesNotExist:
        return None


def _phone(a: Appointment) -> str:
    if a.patient_id is not None and a.patient is not None:
        return a.patient.phone or a.patient.phone_alt or a.contact_phone
    return a.contact_phone


def _message(a: Appointment, center: CenterProfile, now: datetime) -> str:
    access = _access(a)
    return dguest.status_message(
        dguest.BookingFacts(
            center_ar=center.name_ar,
            center_en=center.name_en,
            doctor_ar=a.doctor.user.display_name_ar,
            doctor_en=a.doctor.user.display_name_en,
            when=timezone.localtime(a.starts_at).strftime("%Y-%m-%d %H:%M"),
            status=guest.display_of(a, now),
            reference=dguest.format_reference(access.reference) if access else "",
        )
    )


def decorate(rows: Iterable[Appointment]) -> list[Appointment]:
    """Add what the inbox shows besides the appointment: the guest reference and whether it is
    locked, the patient-facing status, the WhatsApp link, and how many requests of the same
    phone wait (for the bulk decline)."""
    items = list(rows)
    now = timezone.now()
    center = CenterProfile.load()
    waiting = Counter(
        dguest.phone_key(phone)
        for phone in Appointment.objects.filter(
            status=AppointmentStatus.REQUESTED,
            expires_at__gt=now,
            source=AppointmentSource.GUEST,
        ).values_list("contact_phone", flat=True)
    )
    for a in items:
        access = _access(a)
        key = dguest.phone_key(_phone(a))
        a.reference = dguest.format_reference(access.reference) if access else None  # type: ignore[attr-defined]
        a.guest_locked = bool(access and access.locked_at)  # type: ignore[attr-defined]
        a.display_status = guest.display_of(a, now)  # type: ignore[attr-defined]
        a.whatsapp_url = dguest.whatsapp_url(_phone(a), _message(a, center, now))  # type: ignore[attr-defined]
        a.phone_open_requests = (  # type: ignore[attr-defined]
            waiting.get(key, 0) if key and a.source == AppointmentSource.GUEST else 0
        )
    return items


def one(appointment_id: int) -> Appointment:
    """One online booking, decorated. Raises: Appointment.DoesNotExist (404)."""
    return decorate([_rows().get(pk=appointment_id, source__in=ONLINE_SOURCES)])[0]


def list_online_bookings(
    *, status: str = "requested", day: date | None = None, doctor_id: int | None = None
) -> list[Appointment]:
    """The inbox: online bookings in ``status`` (``requested`` lists only those still waiting;
    a lapsed one reads as expired under ``cancelled`` once swept), on ``day`` (local) or from
    today on, for one doctor or all. Requests come oldest expiry first, the others by time."""
    now = timezone.now()
    rows = _rows().filter(source__in=ONLINE_SOURCES)
    if status == "requested":
        rows = rows.filter(status=AppointmentStatus.REQUESTED, expires_at__gt=now)
    elif status != "all":
        rows = rows.filter(status=status)
    if day is not None:
        tz = timezone.get_current_timezone()
        start = datetime.combine(day, time.min, tzinfo=tz)
        rows = rows.filter(starts_at__gte=start, starts_at__lt=start + timedelta(days=1))
    elif status in ("requested", "booked"):
        rows = rows.filter(ends_at__gt=now)
    if doctor_id is not None:
        rows = rows.filter(doctor_id=doctor_id)
    order = ("expires_at", "starts_at", "id") if status == "requested" else ("starts_at", "id")
    return decorate(rows.order_by(*order)[:_LIMIT])


def _online(appointment_id: int) -> Appointment:
    return Appointment.objects.get(pk=appointment_id, source__in=ONLINE_SOURCES)


def approve(appointment_id: int, *, actor: User) -> Appointment:
    """Raises: DomainError ``APPOINTMENT_NOT_REQUESTED``, ``ONLINE_REQUEST_EXPIRED``."""
    visits.approve_online_booking(_online(appointment_id), actor=actor)
    return one(appointment_id)


def reject(appointment_id: int, *, actor: User, reason_code: str, note: str) -> Appointment:
    """Raises: DomainError ``APPOINTMENT_NOT_REQUESTED`` and the reason errors."""
    visits.reject_online_booking(
        _online(appointment_id), actor=actor, reason_code=reason_code, note=note
    )
    return one(appointment_id)


def cancel_on_behalf(
    appointment_id: int, *, actor: User, reason_code: str, note: str
) -> Appointment:
    """Cancel a booking or request for its booker (who called or wrote), with a reason code
    and a note, through the same service as any cancellation (ADR 0029 G).

    Raises: DomainError ``APPOINTMENT_NOT_BOOKED`` and the reason errors."""
    visits.cancel_appointment(
        _online(appointment_id), actor=actor, reason_code=reason_code, note=note
    )
    return one(appointment_id)


def reject_all_from_phone(
    appointment_id: int, *, actor: User, reason_code: str, note: str
) -> list[Appointment]:
    """Decline every open guest request with the phone of this booking, in one transaction,
    each with the same reason code, note, actor and time (ADR 0029 F). The phone is not
    blocked (no automatic blocking in V1).

    Raises:
        Appointment.DoesNotExist: not an online booking (404).
        DomainError: ``GUEST_PHONE_INVALID`` (the booking has no usable phone), the reason
            errors.
    """
    anchor = _rows().get(pk=appointment_id, source__in=ONLINE_SOURCES)
    key = dguest.require_phone_key(_phone(anchor))
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="decline all from phone"):
        candidates = Appointment.objects.select_for_update().filter(
            status=AppointmentStatus.REQUESTED, source=AppointmentSource.GUEST
        )
        ids = [a.pk for a in candidates if dguest.phone_key(a.contact_phone) == key]
        for pk in ids:
            visits.reject_online_booking(
                Appointment(pk=pk), actor=actor, reason_code=reason_code, note=note
            )
    return decorate(_rows().filter(pk__in=ids).order_by("starts_at", "id")) if ids else []


def link_patient(appointment_id: int, patient_id: int, *, actor: User) -> Appointment:
    """Link an online booking made without a file to a patient file, explicitly (reception
    checked the person; no automatic match by name or phone, FLOW step 1). A merged file
    links to the file it was merged into. Linking the same file again changes nothing.

    Raises:
        Appointment.DoesNotExist, Patient.DoesNotExist: 404.
        DomainError: ``APPOINTMENT_PATIENT_MISMATCH`` (another file is linked already),
            ``APPOINTMENT_NOT_BOOKED`` (the booking is not open).
    """
    person = patients.resolve(Patient.objects.get(pk=patient_id))
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="link online booking"):
        locked = Appointment.objects.select_for_update().get(
            pk=appointment_id, source__in=ONLINE_SOURCES
        )
        if locked.patient_id is not None:
            if patients.resolve(Patient(pk=locked.patient_id)).pk != person.pk:
                raise DomainError(
                    "APPOINTMENT_PATIENT_MISMATCH", "The booking is linked to another patient"
                )
        else:
            if locked.status not in (AppointmentStatus.REQUESTED, AppointmentStatus.BOOKED):
                raise DomainError("APPOINTMENT_NOT_BOOKED", "The appointment is not open")
            locked.patient = person
            locked.save(update_fields=["patient", "updated_at"])
    return one(appointment_id)


@dataclass(frozen=True, slots=True)
class ReissuedPin:
    pin: str
    booking: Appointment


def reissue_pin(
    appointment_id: int, *, actor: User, reason: str, request: HttpRequest | None = None
) -> ReissuedPin:
    """A new PIN for a guest booking (the guest lost it, or it locked): the old PIN stops
    working, the booking unlocks, open guest sessions end, and the new PIN is returned once
    for staff to read to the guest (ADR 0029 G).

    Raises:
        Appointment.DoesNotExist: not an online booking (404).
        DomainError: ``REASON_REQUIRED``, ``NOT_A_GUEST_BOOKING`` (no guest access: a
            patient's booking, an earlier row of a moved booking, or a purged one).
    """
    text = (reason or "").strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why a new PIN is issued")
    _online(appointment_id)
    pin = dguest.generate_pin(secrets.randbelow)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"new guest PIN: {text}"):
        access = (
            GuestBookingAccess.objects.select_for_update()
            .filter(appointment_id=appointment_id)
            .first()
        )
        if access is None:
            raise DomainError(
                "NOT_A_GUEST_BOOKING", "Only a current guest booking has a reference and PIN"
            )
        access.pin_hash = make_password(pin)
        access.failed_attempts = 0
        access.locked_at = None
        access.pin_issued_at = timezone.now()
        access.pin_issued_by = actor
        access.save(
            update_fields=[
                "pin_hash",
                "failed_attempts",
                "locked_at",
                "pin_issued_at",
                "pin_issued_by",
            ]
        )
        guest.end_sessions(access, reason="pin reissued")
        _event(
            PortalEventKind.GUEST_PIN_REISSUED,
            request,
            actor=actor,
            reference=access.reference,
            appointment=appointment_id,
            note=text[:300],
        )
    return ReissuedPin(pin=pin, booking=one(appointment_id))
