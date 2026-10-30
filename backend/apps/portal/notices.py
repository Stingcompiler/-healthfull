"""The patient's portal inbox (ADR 0029 I; public site Phase 5).

Writers are called by the services that own the events, inside their transactions, so a
notice exists exactly when its event committed:

* :func:`booking_changed` / :func:`booking_moved` from ``apps.visits.services`` (book, approve,
  decline, cancel, expire, reschedule), for an appointment that has a patient file. Guests
  (no file) get nothing: they have the reference and reception's WhatsApp message.
* :func:`result_published` from ``apps.lab.services.approve_results``, after the approval it
  announces: the notice names the test and points to the result the portal already shows
  (approved versions only); it carries no value.

Every writer goes through ``apps.patients.services.notify`` (one door, a ``channels`` list; SMS
would be another channel behind it). The readers take the signed-in
:class:`~apps.portal.services.PortalPrincipal` and see only that person's files: anyone
else's notice id is ``DoesNotExist`` (404).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pghistory
from django.db import transaction
from django.utils import timezone

from apps.lab.models import ResultVersion
from apps.orders.models import ServiceLine
from apps.patients.models import Patient
from apps.portal.models import PatientNotice
from apps.visits.models import Appointment, AppointmentStatus
from domain import appointments as dappt
from domain.portal_status import (
    BookingDisplay,
    NoticeKind,
    booking_display,
    booking_notice,
)

if TYPE_CHECKING:
    from apps.portal.services import PortalPrincipal

__all__ = [
    "booking_changed",
    "booking_display_of",
    "booking_moved",
    "list_notices",
    "mark_all_read",
    "mark_read",
    "record",
    "result_published",
    "unread_count",
]

_LIST_LIMIT = 50

#: Displays whose notice names the reason staff chose (the code's label, never the note).
_WITH_REASON = frozenset({BookingDisplay.DECLINED, BookingDisplay.CANCELLED_BY_CENTER})


def booking_display_of(a: Appointment, now: datetime) -> BookingDisplay:
    """The patient-facing status of an appointment row (``domain.portal_status``)."""
    holds = dappt.holds_slot(a.status, a.expires_at, now=now)
    return booking_display(
        a.status,
        cancel_reason=a.cancel_reason.code if a.cancel_reason else None,
        was_request=a.expires_at is not None and a.approved_at is None,
        expired=a.status == AppointmentStatus.REQUESTED and not holds,
    )


# --- writers -------------------------------------------------------------------------------


def record(
    patient: Patient,
    kind: str,
    payload: dict[str, Any],
    *,
    channels: list[str],
    appointment: Appointment | None = None,
    service_line: ServiceLine | None = None,
) -> PatientNotice:
    """Write one notice (``patients.notify`` is the only caller). Needs the caller's
    transaction: a notice never outlives a rolled-back event."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("a patient notice is written inside its event's transaction")
    return PatientNotice.objects.create(
        patient=patient,
        kind=NoticeKind(kind).value,
        payload=payload,
        channels=channels,
        appointment=appointment,
        service_line=service_line,
    )


def _doctor(a: Appointment) -> dict[str, str]:
    user = a.doctor.user
    return {"doctor_ar": user.display_name_ar, "doctor_en": user.display_name_en}


def _booking_payload(a: Appointment, display: BookingDisplay) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "starts_at": a.starts_at.isoformat(),
        "display_status": display.value,
        **_doctor(a),
    }
    if display in _WITH_REASON and a.cancel_reason is not None:
        payload["reason_ar"] = a.cancel_reason.label_ar
        payload["reason_en"] = a.cancel_reason.label_en
    if display == BookingDisplay.CANCELLED_BY_YOU:
        payload["by_you"] = True
    return payload


def _fresh(appointment: Appointment) -> Appointment:
    return Appointment.objects.select_related("doctor__user", "cancel_reason", "patient").get(
        pk=appointment.pk
    )


def booking_changed(appointment: Appointment) -> PatientNotice | None:
    """Tell the patient what a booking change means for them (requested, confirmed,
    declined, cancelled, expired). Nothing for a guest booking, an arrival or a no-show."""
    from apps.patients import services as patients  # patients is below the portal

    a = _fresh(appointment)
    if a.patient is None:
        return None
    display = booking_display_of(a, timezone.now())
    kind = booking_notice(display)
    if kind is None or kind == NoticeKind.BOOKING_RESCHEDULED:
        return None
    return patients.notify(a.patient, kind, appointment=a, **_booking_payload(a, display))


def booking_moved(old: Appointment, new: Appointment) -> PatientNotice | None:
    """Tell the patient a booking moved to another time (by them or by the center), and
    whether the new time still waits for reception."""
    from apps.patients import services as patients

    a = _fresh(new)
    if a.patient is None:
        return None
    display = booking_display_of(a, timezone.now())
    return patients.notify(
        a.patient,
        NoticeKind.BOOKING_RESCHEDULED,
        appointment=a,
        **_booking_payload(a, display),
        from_starts_at=old.starts_at.isoformat(),
        awaiting_approval=a.status == AppointmentStatus.REQUESTED,
    )


def result_published(line: ServiceLine, version: ResultVersion) -> PatientNotice:
    """A lab result was approved (or a corrected one replaced it): name the test only."""
    from apps.patients import services as patients

    service = line.service
    return patients.notify(
        line.visit.patient,
        NoticeKind.RESULT_PUBLISHED,
        service_line=line,
        test_ar=service.name_ar,
        test_en=service.name_en,
        amended=version.amends_id is not None,
    )


# --- readers (the signed-in patient) -------------------------------------------------------


def _json(n: PatientNotice) -> dict[str, Any]:
    return {
        "id": n.pk,
        "kind": n.kind,
        "created_at": n.created_at,
        "read_at": n.read_at,
        "payload": n.payload,
        "appointment_id": n.appointment_id,
        "result_line_id": n.service_line_id if n.kind == NoticeKind.RESULT_PUBLISHED else None,
    }


def list_notices(principal: PortalPrincipal) -> dict[str, Any]:
    """The person's latest notices (newest first) and how many are unread."""
    rows = PatientNotice.objects.filter(patient_id__in=principal.file_ids())
    return {
        "items": [_json(n) for n in rows.order_by("-created_at", "-id")[:_LIST_LIMIT]],
        "unread": rows.filter(read_at__isnull=True).count(),
    }


def unread_count(principal: PortalPrincipal) -> int:
    return PatientNotice.objects.filter(
        patient_id__in=principal.file_ids(), read_at__isnull=True
    ).count()


def mark_read(principal: PortalPrincipal, notice_id: int) -> dict[str, Any]:
    """Mark one of the person's notices read (idempotent: an already read one keeps its
    time).

    Raises: PatientNotice.DoesNotExist (not the person's notice: 404).
    """
    rows = PatientNotice.objects.filter(patient_id__in=principal.file_ids())
    with transaction.atomic(), _context(principal):
        notice = rows.select_for_update().get(pk=notice_id)
        if notice.read_at is None:
            notice.read_at = timezone.now()
            notice.save(update_fields=["read_at"])
    return _json(notice)


def mark_all_read(principal: PortalPrincipal) -> int:
    """Mark every unread notice of the person read. Returns how many changed."""
    with transaction.atomic(), _context(principal):
        return PatientNotice.objects.filter(
            patient_id__in=principal.file_ids(), read_at__isnull=True
        ).update(read_at=timezone.now())


def _context(principal: PortalPrincipal) -> Any:
    from apps.portal.services import portal_actor  # services imports the visits layer

    return pghistory.context(
        user=portal_actor().pk, reason="portal notice read", portal_session=principal.session_id
    )
