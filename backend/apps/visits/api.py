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
from apps.visits import services
from apps.visits.inpatient_api import inpatient_router
from apps.visits.models import Appointment, QueueEntry, Visit
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
    QueueMoveIn,
    QueueRowOut,
    RescheduleIn,
    TimelineOut,
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
    summary="Booked appointments of a patient that have not ended yet",
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
        "409 APPOINTMENT_CONFLICT (details.appointments), OUTSIDE_SCHEDULE, INVALID_SLOT, "
        "APPOINTMENT_IN_PAST, PATIENT_OR_CONTACT_REQUIRED, DOCTOR_INACTIVE."
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
    description="409 APPOINTMENT_NOT_BOOKED, APPOINTMENT_CONFLICT, OUTSIDE_SCHEDULE.",
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


# Minimal inpatient for the nursing screens (FEATURES 10.5).
visits_router.add_router("/inpatient", inpatient_router)
