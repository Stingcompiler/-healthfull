"""``/api/portal``: the patient portal (FEATURES 15.1, 15.2; ADR 0016).

Three kinds of operation:

* Patient operations authenticate with :data:`~apps.portal.security.portal_auth` (the portal
  cookie, scoped to ``/api/portal``) and read or change only the signed-in person's own
  rows: anyone else's id answers 404 ``NOT_FOUND``, never 403.
* Public operations (``auth=None``): sign-in, sign-out and the receipt check. Unsafe ones
  still pass the API-wide CSRF guard.
* Staff operations use the staff session and a permission code: issuing an access code from
  the cashier's receipt, and the module ping.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import Query, Router, Status

from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ErrorOut
from api.security import session_auth
from apps.portal import conf, queries, services
from apps.portal.schemas import (
    PortalAppointmentOut,
    PortalAppointmentsOut,
    PortalBalanceOut,
    PortalBookIn,
    PortalDoctorOut,
    PortalInvoiceDetailOut,
    PortalInvoiceOut,
    PortalIssueCodeIn,
    PortalIssuedCodeOut,
    PortalLoginIn,
    PortalMeOut,
    PortalPrescriptionsOut,
    PortalReceiptDetailOut,
    PortalReceiptOut,
    PortalResultOut,
    PortalResultSummaryOut,
    PortalSlotsOut,
    PortalSummaryOut,
    PortalVerifyOut,
)
from apps.portal.security import portal_auth, principal

portal_router = Router(tags=["portal"])
add_ping(portal_router, "portal")

_READ: dict[int, type[ErrorOut]] = {401: ErrorOut, 404: ErrorOut}
_WRITE: dict[int, type[ErrorOut]] = {
    401: ErrorOut,
    403: ErrorOut,
    404: ErrorOut,
    409: ErrorOut,
    422: ErrorOut,
}

#: Operations a patient calls with the portal cookie (every other one is public or staff).
PATIENT_OPERATIONS: set[str] = set()


def _patient_op(operation_id: str) -> str:
    PATIENT_OPERATIONS.add(operation_id)
    return operation_id


def _set_cookie(response: HttpResponse, token: str) -> None:
    response.set_cookie(
        conf.COOKIE_NAME,
        token,
        max_age=int(conf.session_absolute().total_seconds()),
        path="/api/portal",
        secure=conf.cookie_secure(),
        httponly=True,
        samesite="Strict",
    )


# --- public: sign-in, sign-out, receipt check ----------------------------------------------


@portal_router.post(
    "/session",
    auth=None,
    response={
        200: PortalMeOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ErrorOut,
        423: ErrorOut,
        429: ErrorOut,
    },
    operation_id="portal_login",
    summary="Patient sign-in with file number, phone and the code printed on a receipt",
    description=(
        "Sets the portal session cookie (HttpOnly, SameSite=Strict, path /api/portal). Every "
        "refusal is 401 `PORTAL_INVALID_CREDENTIALS`; 423 `PORTAL_LOCKED` after repeated "
        "failures for a file number; 429 `RATE_LIMITED` for an address. Needs X-CSRFToken."
    ),
)
def login(request: HttpRequest, response: HttpResponse, payload: PortalLoginIn) -> Any:
    result = services.login(
        request, file_no=payload.file_no, phone=payload.phone, code=payload.code
    )
    _set_cookie(response, result.token)
    return queries.me(services.PortalPrincipal(result.session.pk, result.patient.pk))


@portal_router.post(
    "/session/logout",
    auth=None,
    response={204: None, 403: ErrorOut},
    operation_id="portal_logout",
    summary="End the portal session (idempotent) and clear its cookie",
)
def logout(request: HttpRequest, response: HttpResponse) -> Status[None]:
    services.logout(request, request.COOKIES.get(conf.COOKIE_NAME))
    response.delete_cookie(conf.COOKIE_NAME, path="/api/portal", samesite="Strict")
    return Status(204, None)


@portal_router.get(
    "/verify",
    auth=None,
    response={200: PortalVerifyOut, 404: ErrorOut, 422: ErrorOut, 429: ErrorOut},
    operation_id="portal_verify_receipt",
    summary="Public check of a printed receipt by its number and QR token",
    description=(
        "Center, number, day, amount, status (valid, pending, void) and the payer's initials. "
        "404 when the number is unknown or the token is not its own (not told apart); 429 "
        "after too many checks from one address."
    ),
)
def verify_receipt(
    request: HttpRequest,
    receipt: str = Query(..., min_length=1, max_length=40),
    token: str = Query(..., min_length=1, max_length=64),
) -> Any:
    return services.verify_receipt(request, number=receipt, token=token)


# --- staff: issue an access code -----------------------------------------------------------


@portal_router.post(
    "/access-codes",
    auth=session_auth,
    response={201: PortalIssuedCodeOut, **_WRITE},
    operation_id="portal_issue_access_code",
    summary="Issue a portal access code for the patient of a receipt (shown once)",
    description="Earlier codes of the file are revoked. 409 `PORTAL_PHONE_REQUIRED`.",
)
@require_perm("portal.issue_access_code")
def issue_access_code(request: HttpRequest, payload: PortalIssueCodeIn) -> Status[Any]:
    issued = services.issue_access_code(payload.payment_id, actor=request.user, request=request)  # type: ignore[arg-type]
    return Status(
        201, {"code": issued.code, "expires_at": issued.expires_at, "file_no": issued.file_no}
    )


# --- patient: own data ---------------------------------------------------------------------


@portal_router.get(
    "/me",
    auth=portal_auth,
    response={200: PortalMeOut, 401: ErrorOut},
    operation_id=_patient_op("portal_get_me"),
    summary="The signed-in patient's profile summary",
)
def get_me(request: HttpRequest) -> Any:
    return queries.me(principal(request))


@portal_router.get(
    "/summary",
    auth=portal_auth,
    response={200: PortalSummaryOut, 401: ErrorOut},
    operation_id=_patient_op("portal_get_summary"),
    summary="Home cards: next appointment, latest results, balance",
)
def get_summary(request: HttpRequest) -> Any:
    return queries.summary(principal(request))


@portal_router.get(
    "/appointments",
    auth=portal_auth,
    response={200: PortalAppointmentsOut, 401: ErrorOut},
    operation_id=_patient_op("portal_list_appointments"),
    summary="The patient's upcoming and past appointments",
)
def list_appointments(request: HttpRequest) -> Any:
    return queries.appointments(principal(request))


@portal_router.post(
    "/appointments",
    auth=portal_auth,
    response={201: PortalAppointmentOut, **_WRITE},
    operation_id=_patient_op("portal_book_appointment"),
    summary="Book a free slot of a doctor's schedule",
    description=(
        "409 `PORTAL_SLOT_UNAVAILABLE`, `PORTAL_BOOKING_LIMIT`, `PORTAL_ALREADY_BOOKED`, "
        "`APPOINTMENT_CONFLICT`; 404 for a doctor without a schedule."
    ),
)
def book_appointment(request: HttpRequest, payload: PortalBookIn) -> Status[Any]:
    who = principal(request)
    booked = services.book_appointment(
        who, doctor_id=payload.doctor_id, starts_at=payload.starts_at
    )
    return Status(201, queries.appointment(who, booked.pk))


@portal_router.post(
    "/appointments/{appointment_id}/cancel",
    auth=portal_auth,
    response={200: PortalAppointmentOut, **_WRITE},
    operation_id=_patient_op("portal_cancel_appointment"),
    summary="Cancel one's own future appointment before the cut-off",
    description="409 `PORTAL_CANCEL_TOO_LATE`, `APPOINTMENT_NOT_BOOKED`; 404 if not one's own.",
)
def cancel_appointment(request: HttpRequest, appointment_id: int) -> Any:
    who = principal(request)
    services.cancel_appointment(who, appointment_id)
    return queries.appointment(who, appointment_id)


@portal_router.get(
    "/doctors",
    auth=portal_auth,
    response={200: list[PortalDoctorOut], 401: ErrorOut},
    operation_id=_patient_op("portal_list_doctors"),
    summary="Doctors who take online bookings",
)
def list_doctors(request: HttpRequest) -> Any:
    return queries.booking_doctors()


@portal_router.get(
    "/doctors/{doctor_id}/days",
    auth=portal_auth,
    response={200: list[date], **_READ},
    operation_id=_patient_op("portal_list_booking_days"),
    summary="Days with free slots, from today to the booking horizon",
)
def list_booking_days(request: HttpRequest, doctor_id: int) -> Any:
    return queries.booking_days(doctor_id)


@portal_router.get(
    "/doctors/{doctor_id}/slots",
    auth=portal_auth,
    response={200: PortalSlotsOut, **_READ, 422: ErrorOut},
    operation_id=_patient_op("portal_list_slots"),
    summary="A doctor's free slots on one day that can be booked online",
)
def list_slots(request: HttpRequest, doctor_id: int, on: date) -> Any:
    return queries.booking_slots(doctor_id, on)


@portal_router.get(
    "/results",
    auth=portal_auth,
    response={200: list[PortalResultSummaryOut], 401: ErrorOut},
    operation_id=_patient_op("portal_list_results"),
    summary="The patient's approved lab results, newest first",
)
def list_results(request: HttpRequest) -> Any:
    return queries.results(principal(request))


@portal_router.get(
    "/results/{line_id}",
    auth=portal_auth,
    response={200: PortalResultOut, **_READ},
    operation_id=_patient_op("portal_get_result"),
    summary="One approved lab result with its values (404 until approved, or if not one's own)",
)
def get_result(request: HttpRequest, line_id: int) -> Any:
    return queries.result_detail(principal(request), line_id)


@portal_router.get(
    "/prescriptions",
    auth=portal_auth,
    response={200: PortalPrescriptionsOut, 401: ErrorOut},
    operation_id=_patient_op("portal_get_prescriptions"),
    summary="Prescriptions with dosing instructions, and lab preparation instructions",
)
def get_prescriptions(request: HttpRequest) -> Any:
    return queries.prescriptions(principal(request))


@portal_router.get(
    "/invoices",
    auth=portal_auth,
    response={200: list[PortalInvoiceOut], 401: ErrorOut},
    operation_id=_patient_op("portal_list_invoices"),
    summary="The patient's approved invoices: their share, paid and outstanding",
)
def list_invoices(request: HttpRequest) -> Any:
    return queries.invoices(principal(request))


@portal_router.get(
    "/invoices/{invoice_id}",
    auth=portal_auth,
    response={200: PortalInvoiceDetailOut, **_READ},
    operation_id=_patient_op("portal_get_invoice"),
    summary="One approved invoice of the patient, with lines and receipts",
)
def get_invoice(request: HttpRequest, invoice_id: int) -> Any:
    return queries.invoice_detail(principal(request), invoice_id)


@portal_router.get(
    "/receipts",
    auth=portal_auth,
    response={200: list[PortalReceiptOut], 401: ErrorOut},
    operation_id=_patient_op("portal_list_receipts"),
    summary="The patient's receipts with their status",
)
def list_receipts(request: HttpRequest) -> Any:
    return queries.receipts(principal(request))


@portal_router.get(
    "/receipts/{payment_id}",
    auth=portal_auth,
    response={200: PortalReceiptDetailOut, **_READ},
    operation_id=_patient_op("portal_get_receipt"),
    summary="One receipt of the patient and the invoices it paid",
)
def get_receipt(request: HttpRequest, payment_id: int) -> Any:
    return queries.receipt_detail(principal(request), payment_id)


@portal_router.get(
    "/balance",
    auth=portal_auth,
    response={200: PortalBalanceOut, 401: ErrorOut},
    operation_id=_patient_op("portal_get_balance"),
    summary="What the patient owes and holds as credit",
)
def get_balance(request: HttpRequest) -> Any:
    return queries.balance(principal(request))
