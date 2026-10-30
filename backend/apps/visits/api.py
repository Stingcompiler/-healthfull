"""``/api/visits``: visits, the reception queue board, waiting-room display and appointments.

FEATURES 2.1-2.7, and the inpatient bed board at ``/inpatient`` (10.5,
``apps.visits.inpatient_api``). Routers stay thin: each operation checks its permission,
reads its schema, looks up the rows it names and calls one function of
``apps.visits.services``. Nothing here returns a price (doctors and nurses read these
endpoints); the timeline's financial events are included only for holders of
``billing.view``.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import has_perm, require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.core.models import Department, DoctorProfile, User
from apps.patients.models import Patient, PatientCoverage
from apps.portal import inbox
from apps.visits import services
from apps.visits.inpatient_api import inpatient_router
from apps.visits.models import Appointment, DoctorTimeOff, QueueEntry, Visit
from apps.visits.schemas import (
    AgendaParams,
    AppointmentCancelIn,
    AppointmentIn,
    AppointmentOut,
    AppointmentPatch,
    BoardParams,
    CallNextIn,
    CheckInIn,
    DayAgendaOut,
    DisplayParams,
    GuestPinReissuedOut,
    GuestPinReissueIn,
    OnlineBookingBulkRejectIn,
    OnlineBookingBulkRejectOut,
    OnlineBookingCancelIn,
    OnlineBookingLinkIn,
    OnlineBookingOut,
    OnlineBookingParams,
    OnlineBookingRejectIn,
    QueueMoveIn,
    QueueRowOut,
    RescheduleIn,
    TimelineOut,
    TimeOffAddedOut,
    TimeOffIn,
    TimeOffOut,
    TokenSlipOut,
    UpcomingParams,
    VisitCancelIn,
    VisitDetailOut,
    VisitIn,
    VisitListParams,
    VisitOptionsOut,
    VisitOut,
    WaitingRoomOut,
)

visits_router = Router(tags=["visits"])
add_ping(visits_router, "visits")

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("visits.view")
    return user


def _opt[M: Model](model: type[M], pk: int | None) -> M | None:
    return None if pk is None else get_object_or_404(model, pk=pk)


# --- visits ---------------------------------------------------------------------------------


@visits_router.get(
    "/options",
    response={200: VisitOptionsOut, **_READ},
    operation_id="visits_get_options",
    summary="Departments, doctors, cancel reasons and the follow-up window",
)
@require_perm("visits.view")
def get_options(request: HttpRequest) -> Any:
    return services.visit_options()


@visits_router.get(
    "",
    response={200: Page[VisitOut], **_READ},
    operation_id="visits_list_visits",
    summary="Visits, newest first: of a patient, a day, a department or a doctor (paged)",
)
@require_perm("visits.view")
def list_visits(request: HttpRequest, params: Query[VisitListParams]) -> dict[str, Any]:
    rows = services.visit_list(
        patient=_opt(Patient, params.patient_id),
        on=params.day,
        department=_opt(Department, params.department_id),
        doctor=_opt(DoctorProfile, params.doctor_id),
        status=params.status,
    )
    return paginate(rows, params.page, params.page_size)


@visits_router.post(
    "",
    response={201: VisitDetailOut, **_WRITE},
    operation_id="visits_create_visit",
    summary="Open a visit with its consultation line and queue token",
    description=(
        "A visit with the same doctor (or department) inside the follow-up window becomes a "
        "follow-up (free at 100% follow-up discount: no consultation line). 409 "
        "PATIENT_MERGED, DEPARTMENT_REQUIRED, DOCTOR_INACTIVE, COVERAGE_INVALID, "
        "CARD_NUMBER_REQUIRED, PAYER_CONTRACT_EXPIRED."
    ),
)
@require_perm("visits.create")
def create_visit(request: HttpRequest, payload: VisitIn) -> Status[Any]:
    patient = get_object_or_404(Patient, pk=payload.patient_id)
    view = services.open_visit(
        patient=patient,
        actor=_actor(request),
        doctor=_opt(DoctorProfile, payload.doctor_id),
        department=_opt(Department, payload.department_id),
        visit_type=payload.visit_type,
        coverage=_opt(PatientCoverage, payload.coverage_id),
        use_default_coverage=payload.use_default_coverage,
        card_number=payload.card_number,
        chief_complaint=payload.chief_complaint,
    )
    return Status(201, view)


@visits_router.get(
    "/{int:visit_id}",
    response={200: VisitDetailOut, **_READ},
    operation_id="visits_get_visit",
    summary="A visit with its service line states (no prices) and its queue token",
)
@require_perm("visits.view")
def get_visit(request: HttpRequest, visit_id: int) -> Any:
    return services.visit_view(get_object_or_404(Visit, pk=visit_id))


@visits_router.post(
    "/{int:visit_id}/cancel",
    response={200: VisitDetailOut, **_WRITE},
    operation_id="visits_cancel_visit",
    summary="Cancel an open visit with a reason (paid lines go through a credit note)",
    description=(
        "Open lines are cancelled; invoiced or paid lines get an approved credit note and the "
        "patient money becomes refundable credit (the actor needs "
        "billing.approve_credit_note then). 409 VISIT_NOT_OPEN, VISIT_HAS_PERFORMED_WORK, "
        "REASON_UNKNOWN, REASON_NOTE_REQUIRED."
    ),
)
@require_perm("visits.cancel")
def cancel_visit(request: HttpRequest, visit_id: int, payload: VisitCancelIn) -> Any:
    return services.cancel_visit_view(
        get_object_or_404(Visit, pk=visit_id),
        actor=_actor(request),
        reason_code=payload.reason_code,
        note=payload.note,
    )


@visits_router.post(
    "/{int:visit_id}/close",
    response={200: VisitDetailOut, **_WRITE},
    operation_id="visits_close_visit",
    summary="Close a visit (the doctor ends its clinical record)",
    description=(
        "No new orders, notes or vitals afterwards; ordered lines are still invoiced, paid and "
        "performed. 409 VISIT_NOT_OPEN, VISIT_IN_QUEUE (finish the consultation or mark the "
        "patient absent first), VISIT_ADMITTED (the discharge closes it)."
    ),
)
@require_perm("visits.close")
def close_visit(request: HttpRequest, visit_id: int) -> Any:
    return services.close_visit_view(get_object_or_404(Visit, pk=visit_id), actor=_actor(request))


@visits_router.get(
    "/{int:visit_id}/timeline",
    response={200: list[TimelineOut], **_READ},
    operation_id="visits_get_timeline",
    summary="Everything linked to the visit, oldest first",
    description=(
        "Orders, results, dispenses, admission and closing for every reader; invoices, "
        "payments, credit notes and refunds only for holders of billing.view."
    ),
)
@require_perm("visits.view")
def get_timeline(request: HttpRequest, visit_id: int) -> list[Any]:
    return services.timeline_view(
        get_object_or_404(Visit, pk=visit_id),
        include_financial=has_perm(request, "billing.view"),
    )


# --- queue ----------------------------------------------------------------------------------


@visits_router.get(
    "/queue/board",
    response={200: list[QueueRowOut], **_READ},
    operation_id="visits_get_board",
    summary="Today's tokens in serving order, paid or not (reception board)",
)
@require_perm("visits.view_queue")
def get_board(request: HttpRequest, params: Query[BoardParams]) -> list[Any]:
    return list(
        services.board(
            department=_opt(Department, params.department_id),
            doctor=_opt(DoctorProfile, params.doctor_id),
            include_finished=params.include_finished,
        )
    )


@visits_router.post(
    "/queue/call-next",
    response={200: QueueRowOut, **_WRITE},
    operation_id="visits_call_next",
    summary="Call the first paid waiting token of the department",
    description="Emergencies first, then token order; unpaid tokens are skipped. 409 QUEUE_EMPTY.",
)
@require_perm("visits.manage_queue")
def call_next(request: HttpRequest, payload: CallNextIn) -> Any:
    return services.call_next(
        department=get_object_or_404(Department, pk=payload.department_id),
        doctor=_opt(DoctorProfile, payload.doctor_id),
        actor=_actor(request),
    )


@visits_router.post(
    "/queue/{int:entry_id}/move",
    response={200: QueueRowOut, **_WRITE},
    operation_id="visits_move_queue_entry",
    summary="Call, start, finish, mark no-show or requeue a token",
    description=(
        "finish performs the consultation line and needs visits.finish_consultation (403). "
        "409 QUEUE_TRANSITION_INVALID, QUEUE_NOT_READY (fee neither paid nor authorized)."
    ),
)
@require_perm("visits.manage_queue")
def move_queue_entry(request: HttpRequest, entry_id: int, payload: QueueMoveIn) -> Any:
    return services.move_entry(
        get_object_or_404(QueueEntry, pk=entry_id), payload.action, actor=_actor(request)
    )


@visits_router.get(
    "/queue/display",
    response={200: WaitingRoomOut, **_READ},
    operation_id="visits_get_display",
    summary="Waiting-room screen feed: paid tokens, abbreviated names, the clinics to pick",
)
@require_perm("visits.view_display")
def get_display(request: HttpRequest, params: Query[DisplayParams]) -> Any:
    return services.waiting_room(department=_opt(Department, params.department_id))


@visits_router.get(
    "/queue/{int:entry_id}/token",
    response={200: TokenSlipOut, **_READ},
    operation_id="visits_get_token_slip",
    summary="What the 80 mm queue token slip prints",
)
@require_perm("visits.view_queue")
def get_token_slip(request: HttpRequest, entry_id: int) -> Any:
    return services.token_slip(get_object_or_404(QueueEntry, pk=entry_id))


# --- appointments ---------------------------------------------------------------------------


@visits_router.get(
    "/appointments/day",
    response={200: DayAgendaOut, **_READ},
    operation_id="visits_get_agenda",
    summary="A doctor's day: free slots still ahead and every appointment",
    description="Read-only: every holder of visits.view (doctors see their own day).",
)
@require_perm("visits.view")
def get_agenda(request: HttpRequest, params: Query[AgendaParams]) -> Any:
    return services.appointment_day(
        get_object_or_404(DoctorProfile, pk=params.doctor_id), params.day
    )


@visits_router.get(
    "/appointments/upcoming",
    response={200: list[AppointmentOut], **_READ},
    operation_id="visits_list_upcoming_appointments",
    summary="Booked appointments and open online requests of a patient that have not ended",
)
@require_perm("visits.view")
def list_upcoming(request: HttpRequest, params: Query[UpcomingParams]) -> list[Any]:
    return services.upcoming_appointments(get_object_or_404(Patient, pk=params.patient_id))


@visits_router.post(
    "/appointments",
    response={201: AppointmentOut, **_WRITE},
    operation_id="visits_book_appointment",
    summary="Book a slot with a doctor (for a patient or a named caller)",
    description=(
        "409 APPOINTMENT_CONFLICT (details.appointments), OUTSIDE_SCHEDULE, DOCTOR_TIME_OFF, "
        "INVALID_SLOT, APPOINTMENT_IN_PAST, PATIENT_OR_CONTACT_REQUIRED, DOCTOR_INACTIVE. "
        "There is no overbooking: an urgent patient is a walk-in visit (ADR 0029 C)."
    ),
)
@require_perm("visits.manage_appointments")
def book_appointment(request: HttpRequest, payload: AppointmentIn) -> Status[Any]:
    booked = services.book_appointment(
        doctor=get_object_or_404(DoctorProfile, pk=payload.doctor_id),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        patient=_opt(Patient, payload.patient_id),
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        notes=payload.notes,
        actor=_actor(request),
    )
    return Status(201, booked)


@visits_router.patch(
    "/appointments/{int:appointment_id}",
    response={200: AppointmentOut, **_WRITE},
    operation_id="visits_update_appointment",
    summary="Edit a booking's notes or caller details",
)
@require_perm("visits.manage_appointments")
def update_appointment(request: HttpRequest, appointment_id: int, payload: AppointmentPatch) -> Any:
    return services.update_appointment(
        get_object_or_404(Appointment, pk=appointment_id),
        actor=_actor(request),
        **payload.dict(exclude_unset=True),
    )


@visits_router.post(
    "/appointments/{int:appointment_id}/reschedule",
    response={201: AppointmentOut, **_WRITE},
    operation_id="visits_reschedule_appointment",
    summary="Move a booking to another slot (the old one is kept as rescheduled)",
    description=(
        "409 APPOINTMENT_NOT_BOOKED, APPOINTMENT_CONFLICT, OUTSIDE_SCHEDULE, DOCTOR_TIME_OFF."
    ),
)
@require_perm("visits.manage_appointments")
def reschedule_appointment(
    request: HttpRequest, appointment_id: int, payload: RescheduleIn
) -> Status[Any]:
    moved = services.reschedule_appointment(
        get_object_or_404(Appointment, pk=appointment_id),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        actor=_actor(request),
    )
    return Status(201, moved)


@visits_router.post(
    "/appointments/{int:appointment_id}/cancel",
    response={200: AppointmentOut, **_WRITE},
    operation_id="visits_cancel_appointment",
    summary="Cancel a booking with a reason code and the caller's words",
    description=(
        "409 APPOINTMENT_NOT_BOOKED, REASON_REQUIRED, REASON_UNKNOWN, REASON_NOTE_REQUIRED."
    ),
)
@require_perm("visits.manage_appointments")
def cancel_appointment(
    request: HttpRequest, appointment_id: int, payload: AppointmentCancelIn
) -> Any:
    return services.cancel_appointment(
        get_object_or_404(Appointment, pk=appointment_id),
        actor=_actor(request),
        reason_code=payload.reason_code,
        note=payload.note,
    )


@visits_router.post(
    "/appointments/{int:appointment_id}/no-show",
    response={200: AppointmentOut, **_WRITE},
    operation_id="visits_mark_appointment_no_show",
    summary="The patient did not come",
)
@require_perm("visits.manage_appointments")
def mark_no_show(request: HttpRequest, appointment_id: int) -> Any:
    return services.mark_appointment_no_show(
        get_object_or_404(Appointment, pk=appointment_id), actor=_actor(request)
    )


@visits_router.post(
    "/appointments/{int:appointment_id}/check-in",
    response={201: VisitDetailOut, **_WRITE},
    operation_id="visits_check_in_appointment",
    summary="The patient arrived: open the visit from the booking",
    description=(
        "A booking for a caller without a file needs patient_id. 409 APPOINTMENT_NOT_BOOKED, "
        "PATIENT_REQUIRED, APPOINTMENT_PATIENT_MISMATCH and the create-visit errors."
    ),
)
@require_perm("visits.create")
def check_in(request: HttpRequest, appointment_id: int, payload: CheckInIn) -> Status[Any]:
    view = services.check_in(
        get_object_or_404(Appointment, pk=appointment_id),
        actor=_actor(request),
        patient=_opt(Patient, payload.patient_id),
        coverage=_opt(PatientCoverage, payload.coverage_id),
        use_default_coverage=payload.use_default_coverage,
        card_number=payload.card_number,
        chief_complaint=payload.chief_complaint,
    )
    return Status(201, view)


# --- the online booking inbox (ADR 0029 A9, D, E, F, G) -------------------------------------
# Each answer carries the booker's wa.me link with a prefilled status message (never a PIN).


@visits_router.get(
    "/online-bookings",
    response={200: list[OnlineBookingOut], **_READ},
    operation_id="visits_list_online_bookings",
    summary="The reception inbox: bookings made online by patients and guests",
    description=(
        "status `requested` (default) lists the requests still waiting, oldest expiry first; "
        "other statuses by time. Without `day`, requested and booked list from now on. At "
        "most 200 rows."
    ),
)
@require_perm("visits.manage_online_bookings")
def list_online_bookings(request: HttpRequest, params: Query[OnlineBookingParams]) -> list[Any]:
    return inbox.list_online_bookings(
        status=params.status, day=params.day, doctor_id=params.doctor_id
    )


@visits_router.post(
    "/online-bookings/{int:appointment_id}/approve",
    response={200: OnlineBookingOut, **_WRITE},
    operation_id="visits_approve_online_booking",
    summary="Confirm an online request (requested -> booked, who and when recorded)",
    description="409 APPOINTMENT_NOT_REQUESTED, ONLINE_REQUEST_EXPIRED.",
)
@require_perm("visits.manage_online_bookings")
def approve_online_booking(request: HttpRequest, appointment_id: int) -> Any:
    return inbox.approve(appointment_id, actor=_actor(request))


@visits_router.post(
    "/online-bookings/{int:appointment_id}/reject",
    response={200: OnlineBookingOut, **_WRITE},
    operation_id="visits_reject_online_booking",
    summary="Decline an online request with a reason code and a note",
    description=(
        "409 APPOINTMENT_NOT_REQUESTED, REASON_REQUIRED, REASON_UNKNOWN, REASON_NOTE_REQUIRED."
    ),
)
@require_perm("visits.manage_online_bookings")
def reject_online_booking(
    request: HttpRequest, appointment_id: int, payload: OnlineBookingRejectIn
) -> Any:
    return inbox.reject(
        appointment_id, actor=_actor(request), reason_code=payload.reason_code, note=payload.note
    )


@visits_router.post(
    "/online-bookings/{int:appointment_id}/cancel",
    response={200: OnlineBookingOut, **_WRITE},
    operation_id="visits_cancel_online_booking",
    summary="Cancel an online booking or request on the booker's behalf (reason and note)",
    description=(
        "409 APPOINTMENT_NOT_BOOKED, REASON_REQUIRED, REASON_UNKNOWN, REASON_NOTE_REQUIRED."
    ),
)
@require_perm("visits.manage_online_bookings")
def cancel_online_booking(
    request: HttpRequest, appointment_id: int, payload: OnlineBookingCancelIn
) -> Any:
    return inbox.cancel_on_behalf(
        appointment_id, actor=_actor(request), reason_code=payload.reason_code, note=payload.note
    )


@visits_router.post(
    "/online-bookings/{int:appointment_id}/reject-phone",
    response={200: OnlineBookingBulkRejectOut, **_WRITE},
    operation_id="visits_reject_online_bookings_from_phone",
    summary="Decline every open guest request with this booking's phone (one reason, one note)",
    description=(
        "Does not block the phone. 409 GUEST_PHONE_INVALID, REASON_REQUIRED, REASON_UNKNOWN, "
        "REASON_NOTE_REQUIRED."
    ),
)
@require_perm("visits.manage_online_bookings")
def reject_online_bookings_from_phone(
    request: HttpRequest, appointment_id: int, payload: OnlineBookingBulkRejectIn
) -> Any:
    rows = inbox.reject_all_from_phone(
        appointment_id, actor=_actor(request), reason_code=payload.reason_code, note=payload.note
    )
    return {"rejected": len(rows), "bookings": rows}


@visits_router.post(
    "/online-bookings/{int:appointment_id}/link-patient",
    response={200: OnlineBookingOut, **_WRITE},
    operation_id="visits_link_online_booking_patient",
    summary="Link a booking made without a file to the patient's file (reception checked them)",
    description=(
        "Explicit and audited; never automatic by name or phone. 409 "
        "APPOINTMENT_PATIENT_MISMATCH (another file is linked), APPOINTMENT_NOT_BOOKED."
    ),
)
@require_perm("visits.manage_online_bookings")
def link_online_booking_patient(
    request: HttpRequest, appointment_id: int, payload: OnlineBookingLinkIn
) -> Any:
    return inbox.link_patient(appointment_id, payload.patient_id, actor=_actor(request))


@visits_router.post(
    "/online-bookings/{int:appointment_id}/reissue-pin",
    response={200: GuestPinReissuedOut, **_WRITE},
    operation_id="visits_reissue_guest_pin",
    summary="Issue a new PIN for a guest booking (shown once; the old PIN stops working)",
    description=(
        "Unlocks a booking locked after wrong PINs and ends the guest's open sessions. 409 "
        "REASON_REQUIRED, NOT_A_GUEST_BOOKING."
    ),
)
@require_perm("visits.manage_online_bookings")
def reissue_guest_pin(request: HttpRequest, appointment_id: int, payload: GuestPinReissueIn) -> Any:
    issued = inbox.reissue_pin(
        appointment_id, actor=_actor(request), reason=payload.reason, request=request
    )
    return {"pin": issued.pin, "booking": issued.booking}


# --- doctor time off (ADR 0029 C) -----------------------------------------------------------


@visits_router.get(
    "/doctors/{int:doctor_id}/time-off",
    response={200: list[TimeOffOut], **_READ},
    operation_id="visits_list_time_off",
    summary="A doctor's time off that has not ended yet",
)
@require_perm("core.manage_departments")
def list_time_off(request: HttpRequest, doctor_id: int) -> list[Any]:
    return services.list_time_off(get_object_or_404(DoctorProfile, pk=doctor_id).pk)


@visits_router.post(
    "/doctors/{int:doctor_id}/time-off",
    response={201: TimeOffAddedOut, **_WRITE},
    operation_id="visits_add_time_off",
    summary="Block a period of a doctor's calendar (no slot inside it is offered or booked)",
    description=(
        "Bookings already inside the period are returned, not cancelled. 409 "
        "TIME_OFF_INVALID_RANGE, TIME_OFF_IN_PAST, TIME_OFF_REASON_REQUIRED, TIME_OFF_OVERLAP."
    ),
)
@require_perm("core.manage_departments")
def add_time_off(request: HttpRequest, doctor_id: int, payload: TimeOffIn) -> Status[Any]:
    doctor = get_object_or_404(DoctorProfile, pk=doctor_id)
    return Status(201, services.add_time_off(_actor(request), doctor.pk, **payload.dict()))


@visits_router.delete(
    "/time-off/{int:time_off_id}",
    response={204: None, **_WRITE},
    operation_id="visits_remove_time_off",
    summary="Give a period of time off back to the doctor's calendar",
)
@require_perm("core.manage_departments")
def remove_time_off(request: HttpRequest, time_off_id: int) -> Status[None]:
    services.remove_time_off(_actor(request), get_object_or_404(DoctorTimeOff, pk=time_off_id).pk)
    return Status(204, None)


# Minimal inpatient for the nursing screens (FEATURES 10.5).
visits_router.add_router("/inpatient", inpatient_router)
