"""Patient portal services (FEATURES 15.1, 15.2; ADR 0016): access codes, portal sessions,
online booking and cancellation, public receipt verification.

The portal never uses the staff session or staff permissions. A patient signs in with the
file number, the phone on file and the access code printed on a receipt; the session lives
in its own cookie (``conf.COOKIE_NAME``) whose token is stored only as a SHA-256 hash.

Abuse control (mirrors ADR 0005 for staff):

* every refusal is ``PORTAL_INVALID_CREDENTIALS`` (401), whatever was wrong, after the same
  password-hash work, so answers and timing do not tell which file numbers exist;
* a typed file number locks after ``PORTAL_FILE_MAX_FAILURES`` failures for
  ``PORTAL_FILE_LOCK_SECONDS`` (``PORTAL_LOCKED``, 423), known or not;
* a code locks for good after ``max_attempts`` wrong codes given with the right file number
  and phone (a new receipt brings a new code);
* a client address that fails ``PORTAL_LOGIN_IP_MAX_FAILURES`` times in a window gets 429
  ``RATE_LIMITED`` before any hashing.

Failure bookkeeping is committed before the error is raised.
"""

from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pghistory
import structlog
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from apps.core.models import CenterProfile, DoctorProfile, User
from apps.core.services import client_ip
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.payments.models import Payment
from apps.portal import conf
from apps.portal.models import (
    AccessPurpose,
    PortalAccessCode,
    PortalEvent,
    PortalEventKind,
    PortalSession,
    PortalThrottle,
    PortalThrottleScope,
)
from apps.visits import services as visits
from apps.visits.models import Appointment, AppointmentStatus
from domain import portal as dportal
from domain.errors import DomainError
from domain.lockout import LockState, is_locked, normalize, register_failure, register_success
from domain.money import money
from domain.payments import Verification
from domain.throttle import WindowState, hit, is_limited, retry_after_seconds

logger = structlog.get_logger(__name__)

__all__ = [
    "IssuedCode",
    "LoginResult",
    "PortalPrincipal",
    "authenticate",
    "book_appointment",
    "bookable_doctor",
    "cancel_appointment",
    "issue_access_code",
    "login",
    "logout",
    "portal_actor",
    "purge_stale",
    "receipt_verify_token",
    "verify_receipt",
]

#: The inactive, password-less user named as ``created_by`` / ``cancelled_by`` of bookings a
#: patient makes on the portal (those columns name a user). It can never sign in.
PORTAL_ACTOR_USERNAME = "portal-system"

_INVALID_MESSAGE = "The file number, phone number or code is not right"
_LAST_SEEN_RESOLUTION_SECONDS = 30


# --- principal -----------------------------------------------------------------------------


@dataclass(slots=True)
class PortalPrincipal:
    """Who a portal request acts for: one person, through every file merged into theirs."""

    session_id: int
    patient_id: int
    _files: list[int] | None = field(default=None, repr=False)

    def person(self) -> Patient:
        """The surviving file of the person (merges after sign-in are followed)."""
        return patients.resolve(Patient(pk=self.patient_id))

    def file_ids(self) -> list[int]:
        """Every file of the person; every portal query is limited to these."""
        if self._files is None:
            self._files = patients.person_file_ids(self.patient_id)
        return self._files


# --- helpers -------------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _event(
    kind: PortalEventKind,
    request: HttpRequest | None,
    *,
    patient: Patient | None = None,
    file_no: str = "",
    actor: User | None = None,
    **details: Any,
) -> None:
    """Append one ``PortalEvent`` in its own savepoint; a write failure is logged, never
    raised, so the surrounding bookkeeping still commits."""
    try:
        with transaction.atomic():
            PortalEvent.objects.create(
                kind=kind,
                patient=patient,
                file_no=file_no[:30],
                actor=actor,
                ip_address=client_ip(request) if request is not None else None,
                user_agent=(request.headers.get("User-Agent", "") if request else "")[:300],
                request_id=str(getattr(request, "request_id", "") or "")[:64],
                details=details,
            )
    except DatabaseError:
        logger.exception("portal_event_write_failed", kind=str(kind))
        return
    logger.info("portal_event", kind=str(kind), patient_id=patient.pk if patient else None)


def _locked_throttle(scope: PortalThrottleScope, key: str) -> PortalThrottle:
    PortalThrottle.objects.bulk_create(
        [PortalThrottle(scope=scope, key=key[:64])], ignore_conflicts=True
    )
    return PortalThrottle.objects.select_for_update().get(scope=scope, key=key[:64])


def _window(row: PortalThrottle) -> WindowState:
    return WindowState(count=row.count, window_started_at=row.window_started_at)


def _rate_limited(retry_after: int, message: str) -> DomainError:
    return DomainError("RATE_LIMITED", message, retry_after_seconds=retry_after)


def portal_actor() -> User:
    """The portal's system user (see ``PORTAL_ACTOR_USERNAME``), created on first use."""
    found = User.objects.filter(username=PORTAL_ACTOR_USERNAME).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            actor = User(
                username=PORTAL_ACTOR_USERNAME,
                full_name_ar="بوابة المرضى",
                full_name_en="Patient portal",
                is_active=False,
                must_change_password=False,
            )
            actor.set_unusable_password()
            actor.save()
            return actor
    except IntegrityError:  # created concurrently
        return User.objects.get(username=PORTAL_ACTOR_USERNAME)


# --- access codes --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str  # printed form, shown once
    expires_at: datetime
    file_no: str


def issue_access_code(
    payment_id: int, *, actor: User, request: HttpRequest | None = None
) -> IssuedCode:
    """A new portal access code for the patient of a receipt (FEATURES 15.1).

    The code is returned once and stored only as a password hash. Earlier codes of the same
    file are revoked by ``actor``, so only the latest printed code works.

    Raises:
        Payment.DoesNotExist: no such payment (404).
        DomainError: ``PORTAL_PHONE_REQUIRED`` (the file has no phone to sign in with).
    """
    payment = Payment.objects.select_related("patient").get(pk=payment_id)
    patient = payment.patient
    if not (patient.phone_norm or patient.phone_alt_norm):
        raise DomainError(
            "PORTAL_PHONE_REQUIRED", "Add a phone number to the file before giving portal access"
        )
    code = dportal.generate_access_code(secrets.randbelow)
    now = timezone.now()
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason="issue portal access code"),
    ):
        Patient.objects.select_for_update().get(pk=patient.pk)
        PortalAccessCode.objects.filter(patient=patient, revoked_at__isnull=True).update(
            revoked_at=now, revoked_by=actor
        )
        row = PortalAccessCode.objects.create(
            patient=patient,
            purpose=AccessPurpose.RESULTS,
            code_hash=make_password(code),
            expires_at=now + conf.code_ttl(),
            max_attempts=conf.code_max_attempts(),
            created_by=actor,
        )
        _event(
            PortalEventKind.CODE_ISSUED,
            request,
            patient=patient,
            file_no=patient.file_no,
            actor=actor,
            payment=payment.number,
            code_id=row.pk,
        )
    return IssuedCode(
        code=dportal.format_access_code(code), expires_at=row.expires_at, file_no=patient.file_no
    )


# --- sign-in -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    session: PortalSession
    patient: Patient


def _invalid() -> DomainError:
    return DomainError("PORTAL_INVALID_CREDENTIALS", _INVALID_MESSAGE)


def _ip_limited(
    request: HttpRequest, ip: str | None, typed: str, now: datetime
) -> DomainError | None:
    if not ip:
        return None
    row = PortalThrottle.objects.filter(scope=PortalThrottleScope.IP, key=ip).first()
    limit, window = conf.ip_rule()
    if row is None or not is_limited(_window(row), now, limit=limit, window=window):
        return None
    retry = retry_after_seconds(_window(row), now, window=window)
    _event(PortalEventKind.LOGIN_THROTTLED, request, file_no=typed, retry_after_seconds=retry)
    return _rate_limited(retry, "Too many failed sign-ins from this address; try again later")


def _count_ip_failure(ip: str | None, now: datetime) -> None:
    if not ip:
        return
    _, window = conf.ip_rule()
    row = _locked_throttle(PortalThrottleScope.IP, ip)
    state = hit(_window(row), now, window=window)
    row.count, row.window_started_at = state.count, state.window_started_at
    row.save(update_fields=["count", "window_started_at", "updated_at"])


def _match(
    typed: str, phone: str, code: str, now: datetime
) -> tuple[Patient | None, PortalAccessCode | None]:
    """The file and the code that sign in, or why not. Always spends at least one password
    hash, whichever part is wrong. Wrong codes given with the right file and phone count on
    that file's live codes (and lock them at ``max_attempts``)."""
    entered = dportal.normalize_access_code(code) or ""
    phone_norm = patients.normalize_phone(phone or "")
    patient = Patient.objects.filter(file_no__iexact=typed).first() if typed else None
    if patient is None or not entered:
        make_password(entered or "x")
        return patient, None
    if not dportal.phones_match(phone_norm, [patient.phone_norm, patient.phone_alt_norm]):
        make_password(entered)
        return patient, None
    live = list(
        PortalAccessCode.objects.select_for_update()
        .filter(
            patient=patient, revoked_at__isnull=True, locked_at__isnull=True, expires_at__gt=now
        )
        .order_by("id")
    )
    if not live:
        make_password(entered)
        return patient, None
    matched = None
    for row in live:  # check every live code, so the work does not depend on which matches
        if check_password(entered, row.code_hash) and matched is None:
            matched = row
    if matched is not None:
        return patient, matched
    for row in live:
        row.failed_attempts = min(row.failed_attempts + 1, row.max_attempts)
        fields = ["failed_attempts"]
        if row.failed_attempts >= row.max_attempts:
            row.locked_at = now
            fields.append("locked_at")
        row.save(update_fields=fields)
    return patient, None


def _attempt(
    request: HttpRequest, *, file_no: str, phone: str, code: str, now: datetime
) -> LoginResult | DomainError:
    ip = client_ip(request)
    typed = dportal.normalize_file_no(file_no)[:30]
    throttled = _ip_limited(request, ip, typed, now)
    if throttled is not None:
        return throttled
    max_failures, lock_for = conf.file_lock()
    row = _locked_throttle(PortalThrottleScope.FILE, typed or "-")
    state = normalize(LockState(failed_count=row.count, locked_until=row.locked_until), now)
    if is_locked(state, now) and state.locked_until is not None:
        _event(PortalEventKind.LOGIN_LOCKED, request, file_no=typed)
        return DomainError(
            "PORTAL_LOCKED",
            "Too many failed attempts for this file number; try again later",
            retry_after_seconds=math.ceil((state.locked_until - now).total_seconds()),
        )
    patient, matched = _match(typed, phone, code, now)
    if matched is None or patient is None:
        new_state = register_failure(state, now, max_attempts=max_failures, lock_for=lock_for)
        row.count, row.locked_until = new_state.failed_count, new_state.locked_until
        row.save(update_fields=["count", "locked_until", "updated_at"])
        _count_ip_failure(ip, now)
        _event(PortalEventKind.LOGIN_FAILED, request, patient=patient, file_no=typed)
        newly_locked = PortalAccessCode.objects.filter(patient=patient, locked_at=now)
        if patient is not None and newly_locked.exists():
            _event(PortalEventKind.CODE_LOCKED, request, patient=patient, file_no=typed)
        return _invalid()
    cleared = register_success()
    row.count, row.locked_until = cleared.failed_count, cleared.locked_until
    row.save(update_fields=["count", "locked_until", "updated_at"])
    matched.failed_attempts = 0
    matched.last_used_at = now
    matched.save(update_fields=["failed_attempts", "last_used_at"])
    person = patients.resolve(patient)
    token = secrets.token_urlsafe(32)
    session = PortalSession.objects.create(
        token_hash=_hash_token(token),
        patient=person,
        code=matched,
        created_at=now,
        last_seen_at=now,
        ip_address=ip,
        user_agent=request.headers.get("User-Agent", "")[:300],
    )
    _event(
        PortalEventKind.LOGIN_SUCCESS, request, patient=person, file_no=typed, session=session.pk
    )
    return LoginResult(token=token, session=session, patient=person)


def login(request: HttpRequest, *, file_no: str, phone: str, code: str) -> LoginResult:
    """Sign a patient in and start a portal session.

    Raises:
        DomainError: ``PORTAL_INVALID_CREDENTIALS`` (401), ``PORTAL_LOCKED`` (423, with
            ``retry_after_seconds``) or ``RATE_LIMITED`` (429). Bookkeeping is committed
            before the raise.
    """
    with transaction.atomic(), pghistory.context(reason="portal sign-in"):
        outcome = _attempt(request, file_no=file_no, phone=phone, code=code, now=timezone.now())
    if isinstance(outcome, DomainError):
        raise outcome
    return outcome


def authenticate(token: str | None) -> PortalPrincipal | None:
    """The principal of a live portal session token, or None.

    An idle, expired or revoked session (its code revoked by a newer receipt) is ended here.
    Use refreshes ``last_seen_at`` (at most every 30 seconds).
    """
    if not token or len(token) > 128:
        return None
    session = (
        PortalSession.objects.select_related("code")
        .filter(token_hash=_hash_token(token), ended_at__isnull=True)
        .first()
    )
    if session is None:
        return None
    now = timezone.now()
    reason = ""
    if dportal.session_expired(
        session.created_at,
        session.last_seen_at,
        now,
        idle=conf.session_idle(),
        absolute=conf.session_absolute(),
    ):
        reason = "expired"
    elif session.code is not None and session.code.revoked_at is not None:
        reason = "revoked"
    if reason:
        PortalSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
            ended_at=now, end_reason=reason
        )
        return None
    if (now - session.last_seen_at).total_seconds() >= _LAST_SEEN_RESOLUTION_SECONDS:
        PortalSession.objects.filter(pk=session.pk).update(last_seen_at=now)
    return PortalPrincipal(session_id=session.pk, patient_id=session.patient_id)


def logout(request: HttpRequest, token: str | None) -> None:
    """End the session of ``token`` if it is live. Idempotent."""
    if not token or len(token) > 128:
        return
    session = PortalSession.objects.filter(
        token_hash=_hash_token(token), ended_at__isnull=True
    ).first()
    if session is None:
        return
    ended = PortalSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
        ended_at=timezone.now(), end_reason="logout"
    )
    if ended:
        _event(
            PortalEventKind.LOGOUT,
            request,
            patient=session.patient,
            file_no=session.patient.file_no,
            session=session.pk,
        )


# --- appointments --------------------------------------------------------------------------


def bookable_doctor(doctor_id: int) -> DoctorProfile:
    """An active doctor with an active weekly schedule (only those take portal bookings).

    Raises:
        DoctorProfile.DoesNotExist: anything else (404).
    """
    return (
        DoctorProfile.objects.select_related("user", "department")
        .filter(pk=doctor_id, active=True, user__is_active=True, schedules__active=True)
        .distinct()
        .get()
    )


def book_appointment(
    principal: PortalPrincipal, *, doctor_id: int, starts_at: datetime
) -> Appointment:
    """Book one of a doctor's free schedule slots for the signed-in person (FEATURES 2.5, 15.2).

    Raises:
        DoctorProfile.DoesNotExist: unknown doctor or one without a schedule (404).
        DomainError: ``PORTAL_SLOT_UNAVAILABLE``, ``PORTAL_BOOKING_LIMIT``,
            ``PORTAL_ALREADY_BOOKED``, ``APPOINTMENT_CONFLICT`` (taken meanwhile).
    """
    doctor = bookable_doctor(doctor_id)
    start = starts_at if timezone.is_aware(starts_at) else timezone.make_aware(starts_at)
    now = timezone.now()
    day = timezone.localtime(start).date()
    rules = conf.booking_rules()
    actor = portal_actor()
    with (
        transaction.atomic(),
        pghistory.context(
            user=actor.pk, reason="portal booking", portal_session=principal.session_id
        ),
    ):
        # One booking at a time per person, so the limits cannot be raced past.
        person = Patient.objects.select_for_update().get(pk=principal.person().pk)
        files = patients.person_file_ids(person)
        upcoming = Appointment.objects.filter(
            patient_id__in=files, status=AppointmentStatus.BOOKED, starts_at__gt=now
        )
        dportal.check_booking(
            start,
            now=now,
            today=timezone.localdate(),
            start_day=day,
            offered=[s for s, _ in visits.available_slots(doctor, day)],
            open_count=upcoming.count(),
            same_day_with_doctor=upcoming.filter(doctor=doctor, starts_at__date=day).exists(),
            rules=rules,
        )
        return visits.book_appointment(
            doctor=doctor,
            starts_at=start,
            actor=actor,
            patient=person,
            notes="Booked by the patient on the portal",
        )


def cancel_appointment(principal: PortalPrincipal, appointment_id: int) -> Appointment:
    """Cancel the person's own future booking before the cut-off (reason ``PATIENT_REQUEST``).

    Raises:
        Appointment.DoesNotExist: not one of the person's appointments (404).
        DomainError: ``APPOINTMENT_NOT_BOOKED``, ``PORTAL_CANCEL_TOO_LATE``.
    """
    actor = portal_actor()
    with (
        transaction.atomic(),
        pghistory.context(
            user=actor.pk, reason="portal cancellation", portal_session=principal.session_id
        ),
    ):
        appointment = Appointment.objects.select_for_update().get(
            pk=appointment_id, patient_id__in=principal.file_ids()
        )
        dportal.check_cancel(
            appointment.starts_at,
            booked=appointment.status == AppointmentStatus.BOOKED,
            now=timezone.now(),
            rules=conf.booking_rules(),
        )
        return visits.cancel_appointment(
            appointment,
            actor=actor,
            reason_code="PATIENT_REQUEST",
            note="Cancelled by the patient on the portal",
        )


# --- housekeeping --------------------------------------------------------------------------


def purge_stale(now: datetime | None = None) -> tuple[int, int]:
    """Daily housekeeping (``manage.py maintenance``): end portal sessions that idled out or
    passed their limit (the rows stay as the sign-in record) and delete throttle rows whose
    window and lock are over. Returns (sessions ended, throttle rows removed)."""
    now = now or timezone.now()
    idle_cut = now - conf.session_idle()
    absolute_cut = now - conf.session_absolute()
    ended = PortalSession.objects.filter(
        Q(last_seen_at__lte=idle_cut) | Q(created_at__lte=absolute_cut), ended_at__isnull=True
    ).update(ended_at=now, end_reason="expired")
    longest = max(conf.ip_rule()[1], conf.verify_rule()[1], conf.file_lock()[1], timedelta(hours=1))
    removed, _ = (
        PortalThrottle.objects.filter(updated_at__lt=now - longest)
        .filter(Q(locked_until__isnull=True) | Q(locked_until__lt=now))
        .delete()
    )
    return ended, removed


# --- receipt verification ------------------------------------------------------------------


def _token_key() -> bytes:
    return str(settings.SECRET_KEY).encode()


def receipt_verify_token(number: str) -> str:
    """The token printed in a receipt's QR for the public check (``/verify/<token>``)."""
    return dportal.receipt_token(_token_key(), number)


def _verify_limited(request: HttpRequest, now: datetime) -> DomainError | None:
    ip = client_ip(request)
    if not ip:
        return None
    limit, window = conf.verify_rule()
    row = _locked_throttle(PortalThrottleScope.VERIFY_IP, ip)
    if is_limited(_window(row), now, limit=limit, window=window):
        retry = retry_after_seconds(_window(row), now, window=window)
        _event(PortalEventKind.VERIFY_THROTTLED, request, retry_after_seconds=retry)
        return _rate_limited(retry, "Too many receipt checks from this address; try again later")
    state = hit(_window(row), now, window=window)
    row.count, row.window_started_at = state.count, state.window_started_at
    row.save(update_fields=["count", "window_started_at", "updated_at"])
    return None


def verify_receipt(request: HttpRequest, *, number: str, token: str) -> dict[str, Any]:
    """The public check of a printed receipt (FEATURES 15.1): only what proves the receipt,
    never who paid for what (the payer's initials at most).

    Raises:
        DomainError: ``RATE_LIMITED`` (429; every check counts).
        Payment.DoesNotExist: unknown number or a token that does not belong to it (404; the
            two are not told apart).
    """
    with transaction.atomic():
        limited = _verify_limited(request, timezone.now())
    if limited is not None:
        raise limited
    wanted = (number or "").strip().upper()[:30]
    payment = (
        Payment.objects.select_related("patient").filter(number=wanted).first() if wanted else None
    )
    # Always compare, so a known number with a wrong token costs the same as an unknown one.
    token_ok = dportal.receipt_token_matches(_token_key(), wanted, token)
    if payment is None or not token_ok:
        raise Payment.DoesNotExist("No receipt matches")
    status = dportal.public_receipt_status(
        Verification(payment.verification),
        reversed_=Payment.objects.filter(reversal_of=payment).exists(),
        is_reversal=payment.reversal_of_id is not None,
    )
    center = CenterProfile.load()
    patient = payment.patient
    return {
        "center_name_ar": center.name_ar,
        "center_name_en": center.name_en,
        "receipt_number": payment.number,
        "date": timezone.localdate(payment.created_at),
        "amount": format(money(payment.amount), "f"),
        "status": str(status),
        "patient_initials": dportal.initials(patient.full_name_en or patient.full_name_ar),
    }
