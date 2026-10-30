"""``/api/portal``: the patient portal (FEATURES 15.1, 15.2; ADR 0016).

Three kinds of operation:

* Patient operations authenticate with :data:`~apps.portal.security.portal_auth` (the portal
  cookie, scoped to ``/api/portal``) and read or change only the signed-in person's own
  rows: anyone else's id answers 404 ``NOT_FOUND``, never 403.
* Public operations (``auth=None``): sign-in, sign-out, the receipt check, the center page and
  identity, the doctor, day and slot reads of online booking (free times only), the booking
  challenge, a guest's booking and sign-in. Unsafe ones still pass the API-wide CSRF guard
  (the token comes from ``GET /api/auth/csrf``, ADR 0028 decision 3).
* Guest operations (ADR 0029 D) authenticate with :data:`~apps.portal.security.guest_auth`
  (cookie ``hospital_guest``, path ``/api/portal/guest``) and reach only the guest's one
  booking. Neither the patient cookie nor a staff session opens them, and the guest cookie
  opens nothing else.

The administrator switches of ADR 0028/0029 are enforced by the services and queries these
operations call (``apps.core.services.require_*``): the center page answers 404
``SITE_DISABLED`` with the website off; the booking reads and the booking answer 409
``ONLINE_BOOKING_DISABLED`` with online booking off; sign-in, every patient operation and
issuing an access code answer 409 ``PORTAL_DISABLED`` with patient sign-in off.
* Staff operations use the staff session and a permission code: issuing an access code from
  the cashier's receipt, and the module ping.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from datetime import date
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseBase
from ninja import Header, Query, Router, Status

from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ErrorOut
from api.security import session_auth
from apps.core import services as core
from apps.portal import conf, guest, notices, queries, services
from apps.portal.schemas import (
    GuestBookingCreatedOut,
    GuestBookingIn,
    GuestBookingOut,
    GuestRescheduleIn,
    GuestSignInIn,
    PortalAccessCodesOut,
    PortalAppointmentOut,
    PortalAppointmentsOut,
    PortalBalanceOut,
    PortalBookIn,
    PortalCenterIdentityOut,
    PortalCenterPageOut,
    PortalChallengeOut,
    PortalCodeSlipOut,
    PortalDoctorOut,
    PortalInvoiceDetailOut,
    PortalInvoiceOut,
    PortalIssueCodeIn,
    PortalIssuedCodeOut,
    PortalLoginIn,
    PortalMeOut,
    PortalNoticeOut,
    PortalNoticesOut,
    PortalNoticesReadOut,
    PortalPrescriptionsOut,
    PortalReceiptDetailOut,
    PortalReceiptOut,
    PortalRescheduleIn,
    PortalResultOut,
    PortalResultSummaryOut,
    PortalRevokeCodeIn,
    PortalSessionOut,
    PortalSlotsOut,
    PortalSummaryOut,
    PortalVerifyOut,
    PortalVisitOut,
    PortalVisitTimelineOut,
)
from apps.portal.security import guest_auth, guest_principal, portal_auth, principal

portal_router = Router(tags=["portal"])
add_ping(portal_router, "portal")


def _no_store(run: Callable[..., HttpResponseBase]) -> Callable[..., HttpResponseBase]:
    """Patient data is never kept by the browser or a proxy (shared phones, clinic tablets)."""

    @functools.wraps(run)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        response = run(request, *args, **kwargs)
        # Only the public logo sets its own (public, short) caching; everything else, no-store.
        if "Cache-Control" not in response:
            response["Cache-Control"] = "no-store"
        return response

    return wrapper


portal_router.add_decorator(_no_store, mode="view")

#: Every patient operation also answers 409 ``PORTAL_DISABLED`` while sign-in is switched off.
_READ: dict[int, type[ErrorOut]] = {401: ErrorOut, 404: ErrorOut, 409: ErrorOut}
_WRITE: dict[int, type[ErrorOut]] = {
    401: ErrorOut,
    403: ErrorOut,
    404: ErrorOut,
    409: ErrorOut,
    422: ErrorOut,
}

#: Operations a patient calls with the portal cookie (every other one is public or staff).
PATIENT_OPERATIONS: set[str] = set()
#: Operations a guest calls with the guest cookie (ADR 0029 D).
GUEST_OPERATIONS: set[str] = set()


def _patient_op(operation_id: str) -> str:
    PATIENT_OPERATIONS.add(operation_id)
    return operation_id


def _guest_op(operation_id: str) -> str:
    GUEST_OPERATIONS.add(operation_id)
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
        409: ErrorOut,
        422: ErrorOut,
        423: ErrorOut,
        429: ErrorOut,
    },
    operation_id="portal_login",
    summary="Patient sign-in with file number, phone and the code printed on a receipt",
    description=(
        "Sets the portal session cookie (HttpOnly, SameSite=Strict, path /api/portal). Every "
        "refusal is 401 `PORTAL_INVALID_CREDENTIALS`; 423 `PORTAL_LOCKED` after repeated "
        "failures for a file number; 429 `RATE_LIMITED` for an address; 409 `PORTAL_DISABLED` "
        "while patient sign-in is switched off. Needs X-CSRFToken."
    ),
)
def login(request: HttpRequest, response: HttpResponse, payload: PortalLoginIn) -> Any:
    result = services.login(
        request, file_no=payload.file_no, phone=payload.phone, code=payload.code
    )
    _set_cookie(response, result.token)
    return queries.me(services.PortalPrincipal(result.session.pk, result.patient.pk))


@portal_router.get(
    "/session",
    auth=None,
    response={200: PortalSessionOut},
    operation_id="portal_get_session",
    summary="Whether this browser holds a live portal session, and whose",
    description=(
        "Always 200, so the sign-in page can ask without an error: `signed_in` false and `me` "
        "null without a live session (an idle or revoked one is ended here) and while patient "
        "sign-in is switched off."
    ),
)
def get_session(request: HttpRequest) -> Any:
    who = services.current_session(request.COOKIES.get(conf.COOKIE_NAME))
    return {"signed_in": who is not None, "me": queries.me(who) if who is not None else None}


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


@portal_router.get(
    "/center-page",
    auth=None,
    response={200: PortalCenterPageOut, 404: ErrorOut, 429: ErrorOut},
    operation_id="portal_get_center_page",
    summary="The public center page: identity, hours, departments, doctors, notices, contact",
    description=(
        "No sign-in. Only public fields: never prices and never staff other than the doctors "
        "shown. Hidden or empty sections come back empty. 404 `SITE_DISABLED` while the center "
        "website is switched off; 429 after too many reads from one address."
    ),
)
def get_center_page(request: HttpRequest) -> Any:
    services.check_public_page_rate(request)
    return queries.center_page()


@portal_router.get(
    "/center-identity",
    auth=None,
    response={200: PortalCenterIdentityOut, 429: ErrorOut},
    operation_id="portal_get_center_identity",
    summary="The center's name and logo (staff sign-in, portal header); answers with the site off",
    description="No sign-in. 429 after too many reads from one address (shared with the page).",
)
def get_center_identity(request: HttpRequest) -> Any:
    services.check_public_page_rate(request)
    return queries.center_identity()


@portal_router.get(
    "/center-logo",
    auth=None,
    response={200: None, 404: ErrorOut, 429: ErrorOut},
    operation_id="portal_get_center_logo",
    summary="The center logo for the public pages (portal and staff sign-in)",
    openapi_extra={
        "responses": {
            200: {
                "description": "The logo image",
                "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
            }
        }
    },
)
def get_center_logo(request: HttpRequest) -> HttpResponse:
    services.check_public_page_rate(request)
    data, content_type = core.center_logo()
    response = HttpResponse(data, content_type=content_type)
    # The URL carries the logo's version, so a short public cache is safe.
    response["Cache-Control"] = "public, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@portal_router.get(
    "/center-media/{media_id}",
    auth=None,
    response={200: None, 404: ErrorOut, 429: ErrorOut},
    operation_id="portal_get_center_media",
    summary="An image of the center website (hero, gallery, a shown doctor's photo)",
    description=(
        "No sign-in. Only images the center uploaded and shows; 404 for anything else and "
        "`SITE_DISABLED` while the website is off. The URL carries the image's version, so it "
        "may be cached for an hour. 429 after too many reads from one address."
    ),
    openapi_extra={
        "responses": {
            200: {
                "description": "The image",
                "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
            }
        }
    },
)
def get_center_media(request: HttpRequest, media_id: int) -> HttpResponse:
    services.check_public_page_rate(request)
    data, content_type = core.public_center_media(media_id)
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "public, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- staff: issue an access code -----------------------------------------------------------


@portal_router.post(
    "/access-codes",
    auth=session_auth,
    response={201: PortalIssuedCodeOut, **_WRITE},
    operation_id="portal_issue_access_code",
    summary="Issue a portal access code for the patient of a receipt (shown once)",
    description=(
        "Earlier codes of the file are revoked. 409 `PORTAL_PHONE_REQUIRED`, `PORTAL_DISABLED` "
        "(patient sign-in is switched off)."
    ),
)
@require_perm("portal.issue_access_code")
def issue_access_code(request: HttpRequest, payload: PortalIssueCodeIn) -> Status[Any]:
    issued = services.issue_access_code(payload.payment_id, actor=request.user, request=request)  # type: ignore[arg-type]
    return Status(
        201, {"code": issued.code, "expires_at": issued.expires_at, "file_no": issued.file_no}
    )


# --- staff: codes from the patient's file (reception) ------------------------------------


def _staff(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.pk, "full_name_ar": user.full_name_ar, "full_name_en": user.full_name_en}


def _codes_out(patient_id: int) -> dict[str, Any]:
    patient, rows = services.access_codes(patient_id)
    return {
        "patient_id": patient.pk,
        "file_no": patient.file_no,
        "has_phone": bool(patient.phone_norm or patient.phone_alt_norm),
        "codes": [
            {
                "id": r.code.pk,
                "state": r.state,
                "created_at": r.code.created_at,
                "created_by": _staff(r.code.created_by),
                "expires_at": r.code.expires_at,
                "last_used_at": r.code.last_used_at,
                "failed_attempts": r.code.failed_attempts,
                "revoked_at": r.code.revoked_at,
                "revoked_by": _staff(r.code.revoked_by),
                "revoke_note": r.code.revoke_note,
            }
            for r in rows
        ],
    }


@portal_router.get(
    "/patients/{patient_id}/access-codes",
    auth=session_auth,
    response={200: PortalAccessCodesOut, **_WRITE},
    operation_id="portal_list_patient_access_codes",
    summary="A file's portal access codes, newest first (their state, never the codes)",
)
@require_perm("portal.issue_access_code")
def list_patient_access_codes(request: HttpRequest, patient_id: int) -> Any:
    return _codes_out(patient_id)


@portal_router.post(
    "/patients/{patient_id}/access-codes",
    auth=session_auth,
    response={201: PortalCodeSlipOut, **_WRITE},
    operation_id="portal_issue_patient_access_code",
    summary="Issue a portal access code from the patient's file for a printed slip (shown once)",
    description=(
        "Earlier codes of the file are revoked. 409 `PORTAL_PHONE_REQUIRED`, `PORTAL_DISABLED` "
        "(patient sign-in is switched off)."
    ),
)
@require_perm("portal.issue_access_code")
def issue_patient_access_code(request: HttpRequest, patient_id: int) -> Status[Any]:
    slip = services.issue_slip_for_patient(
        patient_id,
        actor=request.user,  # type: ignore[arg-type]
        request=request,
    )
    return Status(201, slip)


@portal_router.post(
    "/access-codes/{code_id}/revoke",
    auth=session_auth,
    response={200: PortalAccessCodesOut, **_WRITE},
    operation_id="portal_revoke_access_code",
    summary="Revoke a portal access code (a lost slip): it stops working, its sessions end",
    description="409 `PORTAL_CODE_ALREADY_REVOKED`, `REASON_REQUIRED`.",
)
@require_perm("portal.revoke_access_code")
def revoke_access_code(request: HttpRequest, code_id: int, payload: PortalRevokeCodeIn) -> Any:
    code = services.revoke_access_code(
        code_id,
        actor=request.user,  # type: ignore[arg-type]
        note=payload.note,
        request=request,
    )
    return _codes_out(code.patient_id)


# --- patient: own data ---------------------------------------------------------------------


@portal_router.get(
    "/me",
    auth=portal_auth,
    response={200: PortalMeOut, 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_get_me"),
    summary="The signed-in patient's profile summary",
)
def get_me(request: HttpRequest) -> Any:
    return queries.me(principal(request))


@portal_router.get(
    "/summary",
    auth=portal_auth,
    response={200: PortalSummaryOut, 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_get_summary"),
    summary="Home cards: next appointment, latest results, balance",
)
def get_summary(request: HttpRequest) -> Any:
    return queries.summary(principal(request))


@portal_router.get(
    "/appointments",
    auth=portal_auth,
    response={200: PortalAppointmentsOut, 401: ErrorOut, 409: ErrorOut},
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
        "Status `requested` (waiting for reception) while approval is required, else "
        "`booked`. 409 `ONLINE_BOOKING_DISABLED`, `PORTAL_SLOT_UNAVAILABLE`, "
        "`PORTAL_BOOKING_LIMIT`, `PORTAL_ALREADY_BOOKED`, `ONLINE_REVIEW_WINDOW_TOO_SHORT`, "
        "`APPOINTMENT_CONFLICT`; 404 for a doctor not offered online or without a schedule."
    ),
)
def book_appointment(request: HttpRequest, payload: PortalBookIn) -> Status[Any]:
    who = principal(request)
    booked = services.book_appointment(
        who, doctor_id=payload.doctor_id, starts_at=payload.starts_at
    )
    return Status(201, queries.appointment(who, booked.pk))


@portal_router.post(
    "/appointments/{appointment_id}/reschedule",
    auth=portal_auth,
    response={201: PortalAppointmentOut, **_WRITE},
    operation_id=_patient_op("portal_reschedule_appointment"),
    summary="Move one's own confirmed booking to another free slot before the cut-off",
    description=(
        "The old booking becomes `rescheduled`; the answer is the new one (`requested` while "
        "approval is required). 409 `ONLINE_BOOKING_DISABLED`, `PORTAL_RESCHEDULE_DISABLED`, "
        "`PORTAL_RESCHEDULE_TOO_LATE`, `APPOINTMENT_NOT_BOOKED` and the booking refusals; "
        "404 if not one's own or the doctor is not offered online."
    ),
)
def reschedule_appointment(
    request: HttpRequest, appointment_id: int, payload: PortalRescheduleIn
) -> Status[Any]:
    who = principal(request)
    moved = services.reschedule_appointment(
        who, appointment_id, starts_at=payload.starts_at, doctor_id=payload.doctor_id
    )
    return Status(201, queries.appointment(who, moved.pk))


@portal_router.post(
    "/appointments/{appointment_id}/cancel",
    auth=portal_auth,
    response={200: PortalAppointmentOut, **_WRITE},
    operation_id=_patient_op("portal_cancel_appointment"),
    summary="Cancel one's own future appointment before the cut-off",
    description=(
        "A confirmed booking or a request waiting for reception. 409 `PORTAL_CANCEL_TOO_LATE`, "
        "`APPOINTMENT_NOT_BOOKED`; 404 if not one's own."
    ),
)
def cancel_appointment(request: HttpRequest, appointment_id: int) -> Any:
    who = principal(request)
    services.cancel_appointment(who, appointment_id)
    return queries.appointment(who, appointment_id)


@portal_router.get(
    "/doctors",
    auth=None,
    response={200: list[PortalDoctorOut], 409: ErrorOut, 429: ErrorOut},
    operation_id="portal_list_doctors",
    summary="Doctors who take online bookings (public)",
    description=(
        "No sign-in: patients and guests read the same list. 409 `ONLINE_BOOKING_DISABLED` "
        "while online booking is switched off; 429 after too many reads from one address."
    ),
)
def list_doctors(request: HttpRequest) -> Any:
    services.check_public_page_rate(request)
    return queries.booking_doctors()


@portal_router.get(
    "/doctors/{doctor_id}/days",
    auth=None,
    response={200: list[date], 404: ErrorOut, 409: ErrorOut, 429: ErrorOut},
    operation_id="portal_list_booking_days",
    summary="Days with free slots, from today to the booking horizon (public)",
    description=(
        "No sign-in. 404 for a doctor not offered online; 409 `ONLINE_BOOKING_DISABLED`; 429 "
        "after too many reads from one address."
    ),
)
def list_booking_days(request: HttpRequest, doctor_id: int) -> Any:
    services.check_public_page_rate(request)
    return queries.booking_days(doctor_id)


@portal_router.get(
    "/doctors/{doctor_id}/slots",
    auth=None,
    response={200: PortalSlotsOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut, 429: ErrorOut},
    operation_id="portal_list_slots",
    summary="A doctor's free slots on one day that can be booked online (public)",
    description=(
        "No sign-in: only free times, never who holds the others. 404 for a doctor not "
        "offered online; 409 `ONLINE_BOOKING_DISABLED`; 429 after too many reads."
    ),
)
def list_slots(request: HttpRequest, doctor_id: int, on: date) -> Any:
    services.check_public_page_rate(request)
    return queries.booking_slots(doctor_id, on)


# --- public: guest booking (ADR 0029 D, F) --------------------------------------------------


def _set_guest_cookie(response: HttpResponse, token: str) -> None:
    response.set_cookie(
        conf.GUEST_COOKIE_NAME,
        token,
        max_age=int(conf.guest_session_absolute().total_seconds()),
        path=conf.GUEST_COOKIE_PATH,
        secure=conf.cookie_secure(),
        httponly=True,
        samesite="Strict",
    )


@portal_router.get(
    "/challenge",
    auth=None,
    response={200: PortalChallengeOut, 409: ErrorOut, 429: ErrorOut},
    operation_id="portal_get_booking_challenge",
    summary="A proof-of-work challenge for the guest booking form (signed, single use)",
    description=(
        "Find a nonce (letters and digits, at most 64) so that SHA-256(challenge + nonce) "
        "starts with `bits` zero bits, then send both with the booking. 409 "
        "`ONLINE_BOOKING_DISABLED`, `GUEST_BOOKING_DISABLED`; 429 after too many reads."
    ),
)
def get_booking_challenge(request: HttpRequest) -> Any:
    services.check_public_page_rate(request)
    return guest.issue_challenge(request)


@portal_router.post(
    "/guest-bookings",
    auth=None,
    response={
        201: GuestBookingCreatedOut,
        400: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        422: ErrorOut,
        429: ErrorOut,
    },
    operation_id="portal_create_guest_booking",
    summary="Book a free slot without a file; answers the reference and the PIN (shown once)",
    description=(
        "Needs the `Idempotency-Key` header (a UUID kept across retries): the same key and "
        "body answers the stored result again (`replayed`), another body 409 "
        "`IDEMPOTENCY_MISMATCH`; no key 400 `IDEMPOTENCY_KEY_REQUIRED`. Status `requested` "
        "while approval is required, else `booked`. 409 `ONLINE_BOOKING_DISABLED`, "
        "`GUEST_BOOKING_DISABLED`, `GUEST_NAME_REQUIRED`, `GUEST_PHONE_INVALID`, `POW_INVALID`, "
        "`POW_EXPIRED`, `POW_ALREADY_USED`, `PORTAL_SLOT_UNAVAILABLE`, "
        "`ONLINE_REVIEW_WINDOW_TOO_SHORT`, `PORTAL_ALREADY_BOOKED`, `GUEST_PHONE_LIMIT`, "
        "`ONLINE_DOCTOR_DAY_FULL`, `APPOINTMENT_CONFLICT`; 404 for a doctor not offered online; "
        "429 `RATE_LIMITED` after the address's daily requests. Creates no patient file, visit, "
        "order, invoice or payment. Needs X-CSRFToken."
    ),
)
def create_guest_booking(
    request: HttpRequest,
    payload: GuestBookingIn,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Status[Any]:
    created = guest.create_booking(
        request,
        idempotency_key=idempotency_key,
        doctor_id=payload.doctor_id,
        starts_at=payload.starts_at,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        challenge=payload.challenge,
        nonce=payload.nonce,
    )
    return Status(201, created)


@portal_router.post(
    "/guest-bookings/sign-in",
    auth=None,
    response={200: GuestBookingOut, 401: ErrorOut, 403: ErrorOut, 409: ErrorOut, 429: ErrorOut},
    operation_id="portal_guest_sign_in",
    summary="Open one's guest booking with its reference and PIN",
    description=(
        "Sets the guest cookie (HttpOnly, SameSite=Strict, path /api/portal/guest). Every "
        "refusal is 401 `GUEST_INVALID_CREDENTIALS` (also for a booking locked after 5 wrong "
        "PINs: reception issues a new PIN); 429 `RATE_LIMITED` for an address; 409 "
        "`ONLINE_BOOKING_DISABLED`. Needs X-CSRFToken."
    ),
)
def guest_sign_in(request: HttpRequest, response: HttpResponse, payload: GuestSignInIn) -> Any:
    token, who = guest.sign_in(request, reference=payload.reference, pin=payload.pin)
    _set_guest_cookie(response, token)
    return guest.booking_view(who)


@portal_router.post(
    "/guest/sign-out",
    auth=None,
    response={204: None, 403: ErrorOut},
    operation_id="portal_guest_sign_out",
    summary="End the guest session (idempotent) and clear its cookie",
)
def guest_sign_out(request: HttpRequest, response: HttpResponse) -> Status[None]:
    guest.sign_out(request, request.COOKIES.get(conf.GUEST_COOKIE_NAME))
    response.delete_cookie(conf.GUEST_COOKIE_NAME, path=conf.GUEST_COOKIE_PATH, samesite="Strict")
    return Status(204, None)


# --- guest: the one booking ----------------------------------------------------------------


@portal_router.get(
    "/guest/booking",
    auth=guest_auth,
    response={200: GuestBookingOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    operation_id=_guest_op("portal_get_guest_booking"),
    summary="The signed-in guest's booking: status, time, doctor, what may still be done",
    description="409 `ONLINE_BOOKING_DISABLED` while online booking is switched off.",
)
def get_guest_booking(request: HttpRequest) -> Any:
    return guest.booking_view(guest_principal(request))


@portal_router.post(
    "/guest/booking/cancel",
    auth=guest_auth,
    response={200: GuestBookingOut, **_WRITE},
    operation_id=_guest_op("portal_cancel_guest_booking"),
    summary="Cancel the guest's booking or request before the cut-off",
    description=(
        "409 `PORTAL_CANCEL_TOO_LATE`, `APPOINTMENT_NOT_BOOKED`, `ONLINE_BOOKING_DISABLED`."
    ),
)
def cancel_guest_booking(request: HttpRequest) -> Any:
    return guest.cancel(request, guest_principal(request))


@portal_router.post(
    "/guest/booking/reschedule",
    auth=guest_auth,
    response={200: GuestBookingOut, **_WRITE, 429: ErrorOut},
    operation_id=_guest_op("portal_reschedule_guest_booking"),
    summary="Move the guest's confirmed booking to another free slot before the cut-off",
    description=(
        "The old booking becomes `rescheduled`, the reference and PIN now open the new one "
        "(`requested` while approval is required). 409 `PORTAL_RESCHEDULE_DISABLED`, "
        "`PORTAL_RESCHEDULE_TOO_LATE`, `APPOINTMENT_NOT_BOOKED`, `GUEST_BOOKING_DISABLED` and "
        "the booking refusals; 404 for a doctor not offered online."
    ),
)
def reschedule_guest_booking(request: HttpRequest, payload: GuestRescheduleIn) -> Any:
    return guest.reschedule(
        request, guest_principal(request), starts_at=payload.starts_at, doctor_id=payload.doctor_id
    )


@portal_router.get(
    "/results",
    auth=portal_auth,
    response={200: list[PortalResultSummaryOut], 401: ErrorOut, 409: ErrorOut},
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
    response={200: PortalPrescriptionsOut, 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_get_prescriptions"),
    summary="Prescriptions with dosing instructions, and lab preparation instructions",
)
def get_prescriptions(request: HttpRequest) -> Any:
    return queries.prescriptions(principal(request))


@portal_router.get(
    "/invoices",
    auth=portal_auth,
    response={200: list[PortalInvoiceOut], 401: ErrorOut, 409: ErrorOut},
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
    response={200: list[PortalReceiptOut], 401: ErrorOut, 409: ErrorOut},
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
    response={200: PortalBalanceOut, 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_get_balance"),
    summary="What the patient owes and holds as credit",
)
def get_balance(request: HttpRequest) -> Any:
    return queries.balance(principal(request))


# --- patient: visits and notices (public site Phase 5) -------------------------------------


@portal_router.get(
    "/visits",
    auth=portal_auth,
    response={200: list[PortalVisitOut], 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_list_visits"),
    summary="The patient's visits, newest first, with what each means for them",
)
def list_visits(request: HttpRequest) -> Any:
    return queries.visit_list(principal(request))


@portal_router.get(
    "/visits/{visit_id}/timeline",
    auth=portal_auth,
    response={200: PortalVisitTimelineOut, **_READ},
    operation_id=_patient_op("portal_get_visit_timeline"),
    summary="One visit as a timeline: booking, arrival, orders, payments, end",
    description=(
        "Patient-facing states only (domain.portal_status): no prices beyond the patient's "
        "share of approved invoices, no staff notes, a lab result only once approved. 404 "
        "if not one's own."
    ),
)
def get_visit_timeline(request: HttpRequest, visit_id: int) -> Any:
    return queries.visit_timeline(principal(request), visit_id)


@portal_router.get(
    "/notices",
    auth=portal_auth,
    response={200: PortalNoticesOut, 401: ErrorOut, 409: ErrorOut},
    operation_id=_patient_op("portal_list_notices"),
    summary="The patient's inbox: booking changes and published results, and the unread count",
)
def list_notices(request: HttpRequest) -> Any:
    return notices.list_notices(principal(request))


@portal_router.post(
    "/notices/read-all",
    auth=portal_auth,
    response={200: PortalNoticesReadOut, **_WRITE},
    operation_id=_patient_op("portal_mark_all_notices_read"),
    summary="Mark every unread notice read",
)
def mark_all_notices_read(request: HttpRequest) -> Any:
    who = principal(request)
    marked = notices.mark_all_read(who)
    return {"marked": marked, "unread": notices.unread_count(who)}


@portal_router.post(
    "/notices/{notice_id}/read",
    auth=portal_auth,
    response={200: PortalNoticeOut, **_WRITE},
    operation_id=_patient_op("portal_mark_notice_read"),
    summary="Mark one notice read (idempotent); 404 if not one's own",
)
def mark_notice_read(request: HttpRequest, notice_id: int) -> Any:
    return notices.mark_read(principal(request), notice_id)
