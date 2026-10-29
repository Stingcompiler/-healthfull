"""Guest booking on the public website (ADR 0029 D, F, G; plan Phase 4).

A person without a file books a doctor's free slot with a name and an (unverified) phone. The
booking is an ``Appointment`` with ``source = guest``, ``patient = NULL``; it creates **no**
patient, visit, service line, invoice or payment, so the seven invariants are untouched.
Reception verifies the person at arrival and links a file explicitly
(``apps.portal.inbox.link_patient``); ``convert_appointment`` is unchanged.

The guest gets a reference (10 base32 characters) and a 6-digit PIN shown once (stored as a
password hash). Reference plus PIN opens a view of that one booking under its own cookie
(``hospital_guest``, path ``/api/portal/guest``): never a patient file, never a staff or a
patient endpoint. Sign-in follows ADR 0016: one uniform ``401 GUEST_INVALID_CREDENTIALS``, a
password hash spent on every attempt, a lock after 5 wrong PINs on a booking (until staff
issue a new PIN), a per-address 429 and a ``PortalEvent`` for each outcome.

Abuse limits (ADR 0029 F), all from the settings row: open bookings per phone, requests per
doctor per day, requests per client address per day, an offline proof-of-work, and the
``Idempotency-Key`` every booking POST carries (a retry returns the stored answer).

Lock order: the guest access, the phone's row, the doctors (by id), then the appointment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pghistory
import structlog
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.core import services as core
from apps.core.db import violated_constraint
from apps.core.models import CenterProfile, DoctorProfile, PublicSiteSettings
from apps.core.services import client_ip
from apps.portal import conf
from apps.portal.models import (
    GuestBookingAccess,
    GuestSession,
    IdempotentRequest,
    PortalEventKind,
    PortalThrottle,
    PortalThrottleScope,
    UsedChallenge,
)
from apps.portal.services import (
    _aware,
    _check_new_slot,
    _event,
    _hash_token,
    _locked_throttle,
    _rate_limited,
    _window,
    bookable_doctor,
    notify_cancelled,
    notify_requested,
    portal_actor,
)
from apps.visits import services as visits
from apps.visits.models import (
    SLOT_HOLDING_STATUSES,
    Appointment,
    AppointmentSource,
    AppointmentStatus,
)
from domain import appointments as dappt
from domain import guest_booking as dguest
from domain import portal as dportal
from domain import proof_of_work as dpow
from domain.errors import DomainError
from domain.portal_status import booking_display
from domain.throttle import hit, is_limited, retry_after_seconds

logger = structlog.get_logger(__name__)

__all__ = [
    "GUEST_PLACEHOLDER_NAME",
    "GuestPrincipal",
    "anonymize_old_guest_bookings",
    "authenticate",
    "booking_view",
    "cancel",
    "create_booking",
    "issue_challenge",
    "notify_cancelled",
    "notify_requested",
    "purge_stale",
    "reschedule",
    "sign_in",
    "sign_out",
]

#: What the retention sweep leaves in ``contact_name`` (the has-person check needs a value).
GUEST_PLACEHOLDER_NAME = "(removed)"
#: ``IdempotentRequest.scope`` of the guest booking POST.
BOOKING_SCOPE = "guest_booking"

_INVALID_MESSAGE = "The booking reference or PIN is not right"
_LAST_SEEN_RESOLUTION_SECONDS = 30
_DAY = timedelta(days=1)


@dataclass(slots=True)
class GuestPrincipal:
    """Who a guest request acts for: one guest access (one booking chain)."""

    session_id: int
    access_id: int


# --- helpers -------------------------------------------------------------------------------


def _settings() -> PublicSiteSettings:
    return core.public_site_settings()


def _require_guest_booking(row: PublicSiteSettings) -> None:
    """Raises: DomainError ``GUEST_BOOKING_DISABLED`` while guests cannot book."""
    if not row.guest_booking_enabled:
        raise DomainError("GUEST_BOOKING_DISABLED", "Booking without a file is switched off")


def _caps(row: PublicSiteSettings) -> dguest.GuestCaps:
    return dguest.GuestCaps(
        per_phone=row.max_guest_bookings_per_phone,
        pending_per_doctor_day=row.max_pending_per_doctor_day,
        per_address_day=row.max_requests_per_address_day,
    )


def _derived_key(purpose: bytes) -> bytes:
    return hmac.new(str(settings.SECRET_KEY).encode(), purpose, hashlib.sha256).digest()


def _held(now: datetime) -> Q:
    return Q(status=AppointmentStatus.BOOKED) | Q(
        status=AppointmentStatus.REQUESTED, expires_at__gt=now
    )


def _event_details(access: GuestBookingAccess | None, **more: Any) -> dict[str, Any]:
    if access is None:
        return more
    return {"reference": access.reference, "appointment": access.appointment_id, **more}


# --- proof-of-work (ADR 0029 F) ------------------------------------------------------------


def _pow_key() -> bytes:
    return _derived_key(b"hospital.portal.pow")


def _address_row(ip: str | None) -> PortalThrottle | None:
    if not ip:
        return None
    return PortalThrottle.objects.filter(scope=PortalThrottleScope.BOOK_IP, key=ip[:64]).first()


def issue_challenge(request: HttpRequest) -> dict[str, Any]:
    """A signed, expiring, single-use challenge for the booking form. Its difficulty is the
    settings' ``pow_difficulty_bits``, two bits more for an address one request short of its
    daily limit.

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED``, ``GUEST_BOOKING_DISABLED``.
    """
    core.require_online_booking()
    row = _settings()
    _require_guest_booking(row)
    now = timezone.now()
    bits = row.pow_difficulty_bits
    address = _address_row(client_ip(request))
    if address is not None and is_limited(
        _window(address), now, limit=max(row.max_requests_per_address_day - 1, 1), window=_DAY
    ):
        bits = min(bits + 2, dpow.MAX_BITS)
    expires = now + conf.challenge_ttl()
    challenge = dpow.issue(
        _pow_key(),
        challenge_id=secrets.token_hex(8),
        expires=int(expires.timestamp()),
        bits=bits,
    )
    return {
        "challenge": challenge.token,
        "bits": bits,
        "expires_at": datetime.fromtimestamp(challenge.expires, tz=UTC),
    }


def _spend_challenge(token: str, nonce: str, *, now: datetime, min_bits: int) -> None:
    """Verify a solved challenge and record it as used, committed at once (so a refused
    booking still spends it).

    Raises:
        DomainError: ``POW_INVALID``, ``POW_EXPIRED``, ``POW_ALREADY_USED``.
    """
    challenge = dpow.verify(_pow_key(), token, nonce, now=int(now.timestamp()), min_bits=min_bits)
    try:
        with transaction.atomic():
            UsedChallenge.objects.create(
                challenge_id=challenge.id,
                expires_at=datetime.fromtimestamp(challenge.expires, tz=UTC),
            )
    except IntegrityError as exc:
        raise DomainError(
            "POW_ALREADY_USED", "This form was already sent; reload the page and try again"
        ) from exc


# --- idempotency (ADR 0029 C) --------------------------------------------------------------


def _idempotency_key(raw: str | None) -> str:
    """Raises: DomainError ``IDEMPOTENCY_KEY_REQUIRED`` (400) without a UUID key."""
    try:
        return str(uuid.UUID((raw or "").strip()))
    except ValueError as exc:
        raise DomainError(
            "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header (a UUID)"
        ) from exc


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _request_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, cls=DjangoJSONEncoder, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _pad(key: str) -> bytes:
    return _derived_key(b"hospital.portal.idempotency-pin:" + key.encode())


def _seal(key: str, secret: str) -> str:
    data = secret.encode()
    return bytes(a ^ b for a, b in zip(data, _pad(key), strict=False)).hex()


def _unseal(key: str, sealed: str) -> str:
    data = bytes.fromhex(sealed)
    return bytes(a ^ b for a, b in zip(data, _pad(key), strict=False)).decode()


def _replay(key: str, request_hash: str, now: datetime) -> dict[str, Any] | None:
    """The stored answer of an earlier request with this key, or None.

    Raises:
        DomainError: ``IDEMPOTENCY_MISMATCH`` (the key came with another body).
    """
    row = IdempotentRequest.objects.filter(scope=BOOKING_SCOPE, key_hash=_key_hash(key)).first()
    if row is None:
        return None
    if row.created_at <= now - conf.idempotency_ttl():
        row.delete()  # past its life: the key may be used again
        return None
    if not hmac.compare_digest(row.request_hash, request_hash):
        raise DomainError(
            "IDEMPOTENCY_MISMATCH", "This Idempotency-Key was already used for another request"
        )
    body = dict(row.body)
    pin = _unseal(key, row.sealed) if row.sealed else None
    access = GuestBookingAccess.objects.filter(reference=body.get("reference_raw", "")).first()
    # A PIN staff replaced since, or a purged booking, is not shown again.
    if access is None or access.pin_issued_by_id is not None:
        pin = None
    body["pin"] = pin
    body["replayed"] = True
    return body


# --- booking -------------------------------------------------------------------------------


def _check_address_day(request: HttpRequest, ip: str | None, now: datetime, limit: int) -> None:
    """Raises: DomainError ``RATE_LIMITED`` (429) once the address made ``limit`` guest
    booking requests in the last day."""
    row = _address_row(ip)
    if row is None or not is_limited(_window(row), now, limit=limit, window=_DAY):
        return
    retry = retry_after_seconds(_window(row), now, window=_DAY)
    _event(PortalEventKind.BOOKING_THROTTLED, request, retry_after_seconds=retry)
    raise _rate_limited(retry, "Too many booking requests from this address today")


def _count_address(ip: str | None, now: datetime) -> None:
    if not ip:
        return
    row = _locked_throttle(PortalThrottleScope.BOOK_IP, ip)
    state = hit(_window(row), now, window=_DAY)
    row.count, row.window_started_at = state.count, state.window_started_at
    row.save(update_fields=["count", "window_started_at", "updated_at"])


def _phone_bookings(phone: str, now: datetime, *, exclude: int | None = None) -> list[Appointment]:
    """Future guest bookings of the phone that hold a slot."""
    rows = Appointment.objects.filter(
        _held(now), source=AppointmentSource.GUEST, starts_at__gt=now
    ).only("pk", "doctor_id", "starts_at", "contact_phone")
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    return [a for a in rows if dguest.phone_key(a.contact_phone) == phone]


def _pending_for_doctor_day(doctor: DoctorProfile, start: datetime, now: datetime) -> int:
    day = timezone.localtime(start).date()
    return Appointment.objects.filter(
        status=AppointmentStatus.REQUESTED,
        expires_at__gt=now,
        doctor=doctor,
        starts_at__date=day,
    ).count()


def _check_guest_slot(
    doctor: DoctorProfile,
    start: datetime,
    *,
    phone: str,
    now: datetime,
    row: PublicSiteSettings,
    moving: int | None = None,
) -> datetime | None:
    """Every rule of a guest booking at ``start`` (``moving``: the booking being moved, not
    counted). Call under the phone's lock and the doctor's. Returns the request expiry while
    approval is required, else None.

    Raises:
        DomainError: ``PORTAL_SLOT_UNAVAILABLE``, ``ONLINE_REVIEW_WINDOW_TOO_SHORT``,
            ``PORTAL_ALREADY_BOOKED``, ``GUEST_PHONE_LIMIT``, ``ONLINE_DOCTOR_DAY_FULL``.
    """
    rules, requests = core.booking_rules(), core.request_rules()
    expires = _check_new_slot(doctor, start, files=[], now=now, rules=rules, requests=requests)
    held = _phone_bookings(phone, now, exclude=moving)
    day = timezone.localtime(start).date()
    if any(
        a.doctor_id == doctor.pk and timezone.localtime(a.starts_at).date() == day for a in held
    ):
        raise DomainError(
            "PORTAL_ALREADY_BOOKED", "There is already a booking with this doctor on that day"
        )
    dguest.check_guest_caps(
        _caps(row),
        open_for_phone=len(held),
        pending_for_doctor_day=_pending_for_doctor_day(doctor, start, now),
        will_be_request=expires is not None,
    )
    return expires


def _new_access(appointment: Appointment, pin: str, now: datetime) -> GuestBookingAccess:
    for _ in range(5):
        reference = dguest.generate_reference(secrets.randbelow)
        if not GuestBookingAccess.objects.filter(reference=reference).exists():
            break
    return GuestBookingAccess.objects.create(
        appointment=appointment,
        reference=reference,
        pin_hash=make_password(pin),
        max_attempts=conf.guest_max_attempts(),
        pin_issued_at=now,
    )


def _doctor_json(doctor: DoctorProfile) -> dict[str, Any]:
    return {
        "id": doctor.pk,
        "name_ar": doctor.user.display_name_ar,
        "name_en": doctor.user.display_name_en,
        "specialty_ar": doctor.specialty_ar,
        "specialty_en": doctor.specialty_en,
        "department_ar": doctor.department.name_ar,
        "department_en": doctor.department.name_en,
    }


def display_of(a: Appointment, now: datetime) -> str:
    holds = dappt.holds_slot(a.status, a.expires_at, now=now)
    return str(
        booking_display(
            a.status,
            cancel_reason=a.cancel_reason.code if a.cancel_reason is not None else None,
            was_request=a.expires_at is not None and a.approved_at is None,
            expired=a.status == AppointmentStatus.REQUESTED and not holds,
        )
    )


def _share(reference: str) -> str:
    center = CenterProfile.load()
    text = dguest.share_message(
        center_ar=center.name_ar, center_en=center.name_en, reference=reference, page=""
    )
    return dguest.share_url(text)


def _created_body(appointment: Appointment, access: GuestBookingAccess) -> dict[str, Any]:
    shown = dguest.format_reference(access.reference)
    body = {
        "reference": shown,
        "reference_raw": access.reference,
        "status": appointment.status,
        "display_status": display_of(appointment, timezone.now()),
        "starts_at": appointment.starts_at,
        "ends_at": appointment.ends_at,
        "expires_at": appointment.expires_at,
        "doctor": _doctor_json(appointment.doctor),
        "share_url": _share(shown),
    }
    # Stored as JSON (the replay answer): dates become ISO strings, read back by the schema.
    stored: dict[str, Any] = json.loads(json.dumps(body, cls=DjangoJSONEncoder))
    return stored


def create_booking(
    request: HttpRequest,
    *,
    idempotency_key: str | None,
    doctor_id: int,
    starts_at: datetime,
    contact_name: str,
    contact_phone: str,
    challenge: str,
    nonce: str,
) -> dict[str, Any]:
    """Book a free slot for a guest without a file (ADR 0029 D). The answer carries the
    reference and the PIN, shown once; a retry with the same ``Idempotency-Key`` and body gets
    the same answer (``replayed`` true) and creates nothing.

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED``, ``GUEST_BOOKING_DISABLED``,
            ``IDEMPOTENCY_KEY_REQUIRED`` (400), ``IDEMPOTENCY_MISMATCH``, ``RATE_LIMITED``
            (429), ``GUEST_NAME_REQUIRED``, ``GUEST_PHONE_INVALID``, ``POW_INVALID``,
            ``POW_EXPIRED``, ``POW_ALREADY_USED``, ``PORTAL_SLOT_UNAVAILABLE``,
            ``ONLINE_REVIEW_WINDOW_TOO_SHORT``, ``PORTAL_ALREADY_BOOKED``,
            ``GUEST_PHONE_LIMIT``, ``ONLINE_DOCTOR_DAY_FULL``, ``APPOINTMENT_CONFLICT``.
        DoctorProfile.DoesNotExist: a doctor not offered online (404).
    """
    core.require_online_booking()
    row = _settings()
    _require_guest_booking(row)
    key = _idempotency_key(idempotency_key)
    start = _aware(starts_at)
    request_hash = _request_hash(
        {
            "doctor_id": doctor_id,
            "starts_at": start.astimezone(UTC).isoformat(),
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "challenge": challenge,
            "nonce": nonce,
        }
    )
    now = timezone.now()
    replayed = _replay(key, request_hash, now)
    if replayed is not None:
        return replayed
    ip = client_ip(request)
    _check_address_day(request, ip, now, row.max_requests_per_address_day)
    name = dguest.validate_contact_name(contact_name)
    phone = dguest.require_phone_key(contact_phone)
    try:
        _spend_challenge(challenge, nonce, now=now, min_bits=row.pow_difficulty_bits)
    except DomainError as exc:
        # A retry racing the first request (same key and body) finds its challenge spent:
        # answer with the first request's result once it is stored.
        again = (
            _replay(key, request_hash, timezone.now()) if exc.code == "POW_ALREADY_USED" else None
        )
        if again is not None:
            return again
        raise
    doctor = bookable_doctor(doctor_id)
    actor = portal_actor()
    pin = dguest.generate_pin(secrets.randbelow)
    try:
        with (
            transaction.atomic(),
            pghistory.context(user=actor.pk, reason="guest booking"),
        ):
            _locked_throttle(PortalThrottleScope.GUEST_PHONE, phone)
            visits.lock_doctors(doctor.pk)
            expires = _check_guest_slot(doctor, start, phone=phone, now=now, row=row)
            appointment = visits.book_appointment(
                doctor=doctor,
                starts_at=start,
                actor=actor,
                contact_name=name,
                contact_phone=" ".join(contact_phone.split())[:30],
                notes="Booked by a guest on the website",
                source=AppointmentSource.GUEST,
                expires_at=expires,
            )
            access = _new_access(appointment, pin, now)
            _count_address(ip, now)
            body = _created_body(appointment, access)
            IdempotentRequest.objects.create(
                scope=BOOKING_SCOPE,
                key_hash=_key_hash(key),
                request_hash=request_hash,
                status=201,
                body=body,
                sealed=_seal(key, pin),
            )
            _event(
                PortalEventKind.GUEST_BOOKING_CREATED,
                request,
                **_event_details(access, status=appointment.status),
            )
            notify_requested(appointment)
    except IntegrityError as exc:
        if violated_constraint(exc) == "portal_idempotent_unique":
            # The same key raced in from a second connection: answer with its result.
            again = _replay(key, request_hash, timezone.now())
            if again is not None:
                return again
        raise
    return {**body, "pin": pin, "replayed": False}


# --- sign-in and the guest session ---------------------------------------------------------


def _invalid() -> DomainError:
    return DomainError("GUEST_INVALID_CREDENTIALS", _INVALID_MESSAGE)


def _ip_limited(request: HttpRequest, ip: str | None, now: datetime) -> DomainError | None:
    if not ip:
        return None
    row = PortalThrottle.objects.filter(scope=PortalThrottleScope.GUEST_IP, key=ip[:64]).first()
    limit, window = conf.guest_ip_rule()
    if row is None or not is_limited(_window(row), now, limit=limit, window=window):
        return None
    retry = retry_after_seconds(_window(row), now, window=window)
    _event(PortalEventKind.GUEST_THROTTLED, request, retry_after_seconds=retry)
    return _rate_limited(retry, "Too many failed sign-ins from this address; try again later")


def _count_ip_failure(ip: str | None, now: datetime) -> None:
    if not ip:
        return
    _, window = conf.guest_ip_rule()
    row = _locked_throttle(PortalThrottleScope.GUEST_IP, ip)
    state = hit(_window(row), now, window=window)
    row.count, row.window_started_at = state.count, state.window_started_at
    row.save(update_fields=["count", "window_started_at", "updated_at"])


def _attempt(
    request: HttpRequest, *, reference: str, pin: str, now: datetime
) -> tuple[str, GuestPrincipal] | DomainError:
    ip = client_ip(request)
    throttled = _ip_limited(request, ip, now)
    if throttled is not None:
        return throttled
    ref = dguest.normalize_reference(reference)
    entered = dguest.normalize_pin(pin)
    access = (
        GuestBookingAccess.objects.select_for_update().filter(reference=ref).first()
        if ref
        else None
    )
    ok = False
    if access is None or access.locked_at is not None or entered is None:
        make_password(entered or "x")  # the same work whatever was wrong
    else:
        ok = check_password(entered, access.pin_hash)
    if not ok:
        _count_ip_failure(ip, now)
        details = _event_details(access) if access else {"reference": (ref or "")[:10]}
        _event(PortalEventKind.GUEST_VIEW_REFUSED, request, **details)
        if access is not None and access.locked_at is None and entered is not None:
            access.failed_attempts = min(access.failed_attempts + 1, access.max_attempts)
            fields = ["failed_attempts"]
            if access.failed_attempts >= access.max_attempts:
                access.locked_at = now
                fields.append("locked_at")
                _event(PortalEventKind.GUEST_LOCKED, request, **_event_details(access))
            access.save(update_fields=fields)
        return _invalid()
    if access is None:  # pragma: no cover - ok implies an access
        return _invalid()
    if access.failed_attempts:
        access.failed_attempts = 0
        access.save(update_fields=["failed_attempts"])
    token = secrets.token_urlsafe(32)
    session = GuestSession.objects.create(
        token_hash=_hash_token(token),
        access=access,
        created_at=now,
        last_seen_at=now,
        ip_address=ip,
        user_agent=request.headers.get("User-Agent", "")[:300],
    )
    _event(PortalEventKind.GUEST_VIEW, request, **_event_details(access, session=session.pk))
    return token, GuestPrincipal(session_id=session.pk, access_id=access.pk)


def sign_in(request: HttpRequest, *, reference: str, pin: str) -> tuple[str, GuestPrincipal]:
    """Open a guest session on one booking with its reference and PIN.

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED`` (before any check),
            ``GUEST_INVALID_CREDENTIALS`` (401, whatever was wrong, also for a locked
            booking), ``RATE_LIMITED`` (429). Bookkeeping is committed before the raise.
    """
    core.require_online_booking()
    with transaction.atomic(), pghistory.context(reason="guest sign-in"):
        outcome = _attempt(request, reference=reference, pin=pin, now=timezone.now())
    if isinstance(outcome, DomainError):
        raise outcome
    return outcome


def authenticate(token: str | None) -> GuestPrincipal | None:
    """The principal of a live guest session token, or None (the guest auth).

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED`` while online booking is off, with or without
            a token, so every guest operation answers it.
    """
    core.require_online_booking()
    if not token or len(token) > 128:
        return None
    session = (
        GuestSession.objects.filter(token_hash=_hash_token(token), ended_at__isnull=True)
        .only("pk", "access_id", "created_at", "last_seen_at")
        .first()
    )
    if session is None:
        return None
    now = timezone.now()
    if dportal.session_expired(
        session.created_at,
        session.last_seen_at,
        now,
        idle=conf.guest_session_idle(),
        absolute=conf.guest_session_absolute(),
    ):
        GuestSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
            ended_at=now, end_reason="expired"
        )
        return None
    if (now - session.last_seen_at).total_seconds() >= _LAST_SEEN_RESOLUTION_SECONDS:
        GuestSession.objects.filter(pk=session.pk).update(last_seen_at=now)
    return GuestPrincipal(session_id=session.pk, access_id=session.access_id)


def sign_out(request: HttpRequest, token: str | None) -> None:
    """End the guest session of ``token`` if it is live. Idempotent."""
    if not token or len(token) > 128:
        return
    session = (
        GuestSession.objects.select_related("access")
        .filter(token_hash=_hash_token(token), ended_at__isnull=True)
        .first()
    )
    if session is None:
        return
    ended = GuestSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
        ended_at=timezone.now(), end_reason="logout"
    )
    if ended:
        _event(
            PortalEventKind.GUEST_LOGOUT,
            request,
            **_event_details(session.access, session=session.pk),
        )


def end_sessions(access: GuestBookingAccess, *, reason: str) -> int:
    return GuestSession.objects.filter(access=access, ended_at__isnull=True).update(
        ended_at=timezone.now(), end_reason=reason[:20]
    )


# --- the guest's booking -------------------------------------------------------------------


def _access(principal: GuestPrincipal) -> GuestBookingAccess:
    return GuestBookingAccess.objects.select_related(
        "appointment__doctor__user",
        "appointment__doctor__department",
        "appointment__cancel_reason",
    ).get(pk=principal.access_id)


def booking_view(principal: GuestPrincipal) -> dict[str, Any]:
    """The one booking a guest may see: status, time, doctor, and what they may still do."""
    access = _access(principal)
    a = access.appointment
    now = timezone.now()
    rules = core.booking_rules()
    holds = dappt.holds_slot(a.status, a.expires_at, now=now)
    booked = a.status == AppointmentStatus.BOOKED
    row = _settings()
    return {
        "reference": dguest.format_reference(access.reference),
        "status": a.status,
        "display_status": display_of(a, now),
        "starts_at": a.starts_at,
        "ends_at": a.ends_at,
        "expires_at": a.expires_at if a.status == AppointmentStatus.REQUESTED else None,
        "doctor": _doctor_json(a.doctor),
        "contact_name": a.contact_name,
        "phone_masked": dportal.mask_phone(dguest.phone_key(a.contact_phone) or ""),
        "can_cancel": dportal.can_cancel(a.starts_at, booked=holds, now=now, rules=rules),
        "cancel_until": a.starts_at - rules.cancel_cutoff if holds else None,
        "can_reschedule": row.guest_booking_enabled
        and dportal.can_reschedule(a.starts_at, booked=booked, now=now, rules=rules),
        "reschedule_until": (
            a.starts_at - rules.reschedule_cutoff if booked and rules.reschedule_allowed else None
        ),
        "rules": {
            "cancel_cutoff_hours": int(rules.cancel_cutoff.total_seconds() // 3600),
            "reschedule_allowed": rules.reschedule_allowed,
            "reschedule_cutoff_hours": int(rules.reschedule_cutoff.total_seconds() // 3600),
            "require_approval": core.request_rules().require_approval,
        },
    }


def cancel(request: HttpRequest, principal: GuestPrincipal) -> dict[str, Any]:
    """The guest cancels their booking or request before the cut-off (reason
    ``PATIENT_REQUEST``); reception is notified.

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED``, ``APPOINTMENT_NOT_BOOKED``,
            ``PORTAL_CANCEL_TOO_LATE``.
    """
    core.require_online_booking()
    actor = portal_actor()
    with (
        transaction.atomic(),
        pghistory.context(
            user=actor.pk, reason="guest cancellation", guest_session=principal.session_id
        ),
    ):
        access = GuestBookingAccess.objects.select_for_update().get(pk=principal.access_id)
        appointment = Appointment.objects.select_for_update().get(pk=access.appointment_id)
        dportal.check_cancel(
            appointment.starts_at,
            booked=appointment.status in SLOT_HOLDING_STATUSES,
            now=timezone.now(),
            rules=core.booking_rules(),
        )
        visits.cancel_appointment(
            appointment,
            actor=actor,
            reason_code="PATIENT_REQUEST",
            note="Cancelled by the guest on the website",
        )
        _event(PortalEventKind.GUEST_CANCELLED, request, **_event_details(access))
        notify_cancelled(appointment)
    return booking_view(principal)


def reschedule(
    request: HttpRequest,
    principal: GuestPrincipal,
    *,
    starts_at: datetime,
    doctor_id: int | None = None,
) -> dict[str, Any]:
    """Move the guest's confirmed booking to another free slot (ADR 0029 A7): the same cut-off
    family as cancelling, the new slot checked like a new guest booking, the old row
    ``rescheduled`` and linked from the new one, and the guest access moved to the new row in
    the same transaction (the access belongs to the chain, ADR 0029 D).

    Raises:
        DomainError: ``ONLINE_BOOKING_DISABLED``, ``GUEST_BOOKING_DISABLED``,
            ``PORTAL_RESCHEDULE_DISABLED``, ``APPOINTMENT_NOT_BOOKED``,
            ``PORTAL_RESCHEDULE_TOO_LATE`` and the refusals of :func:`create_booking`.
        DoctorProfile.DoesNotExist: the new doctor is not offered online (404).
    """
    core.require_online_booking()
    row = _settings()
    _require_guest_booking(row)
    start = _aware(starts_at)
    now = timezone.now()
    actor = portal_actor()
    with (
        transaction.atomic(),
        pghistory.context(
            user=actor.pk, reason="guest reschedule", guest_session=principal.session_id
        ),
    ):
        access = GuestBookingAccess.objects.select_for_update().get(pk=principal.access_id)
        current = Appointment.objects.get(pk=access.appointment_id)
        doctor = bookable_doctor(doctor_id if doctor_id is not None else current.doctor_id)
        phone = dguest.require_phone_key(current.contact_phone)
        _locked_throttle(PortalThrottleScope.GUEST_PHONE, phone)
        rules = core.booking_rules()

        def check(old: Appointment) -> datetime | None:
            dportal.check_reschedule(
                old.starts_at, booked=old.status == AppointmentStatus.BOOKED, now=now, rules=rules
            )
            return _check_guest_slot(doctor, start, phone=phone, now=now, row=row, moving=old.pk)

        moved = visits.move_appointment(
            current,
            starts_at=start,
            doctor=doctor,
            actor=actor,
            reason="guest reschedule",
            check=check,
        )
        access.appointment = moved
        access.save(update_fields=["appointment"])
        _event(
            PortalEventKind.BOOKING_RESCHEDULED,
            request,
            **_event_details(access, moved_from=current.pk, status=moved.status),
        )
        notify_requested(moved)
    return booking_view(principal)


# --- housekeeping and retention (ADR 0029 C, G) --------------------------------------------


def purge_stale(now: datetime | None = None) -> tuple[int, int, int]:
    """End idle or too old guest sessions, delete idempotent answers past their 24 hours and
    spent challenges past their expiry. Returns (sessions ended, answers removed, challenges
    removed)."""
    now = now or timezone.now()
    ended = GuestSession.objects.filter(
        Q(last_seen_at__lte=now - conf.guest_session_idle())
        | Q(created_at__lte=now - conf.guest_session_absolute()),
        ended_at__isnull=True,
    ).update(ended_at=now, end_reason="expired")
    answers, _ = IdempotentRequest.objects.filter(
        created_at__lte=now - conf.idempotency_ttl()
    ).delete()
    spent, _ = UsedChallenge.objects.filter(expires_at__lte=now).delete()
    return ended, answers, spent


def _with_predecessors(ids: set[int]) -> set[int]:
    """``ids`` and every earlier row of their reschedule chains still without a file."""
    found = set(ids)
    frontier = set(ids)
    while frontier:
        earlier = set(
            Appointment.objects.filter(
                pk__in=frontier,
                rescheduled_from__isnull=False,
                rescheduled_from__patient__isnull=True,
                rescheduled_from__source=AppointmentSource.GUEST,
            ).values_list("rescheduled_from_id", flat=True)
        )
        frontier = earlier - found
        found |= frontier
    return found


def _purgeable(cut: datetime) -> QuerySet[Appointment]:
    return Appointment.objects.filter(
        source=AppointmentSource.GUEST,
        patient__isnull=True,
        status=AppointmentStatus.CANCELLED,
        cancelled_at__lt=cut,
    ).exclude(contact_name=GUEST_PLACEHOLDER_NAME)


def anonymize_old_guest_bookings(now: datetime | None = None) -> int:
    """Retention (ADR 0029 G): guest bookings never linked to a file that ended cancelled or
    expired more than ``guest_retention_days`` ago lose the guest's name (a fixed placeholder,
    so the has-person check holds), phone and notes, with the earlier rows of their reschedule
    chain; their guest access is deleted. One ``PortalEvent`` with counts only.

    Limit (accepted by the owner on 2026-10-29): the append-only appointment history keeps the
    earlier copies of the name and phone. Returns how many bookings were anonymized.
    """
    now = now or timezone.now()
    cut = now - timedelta(days=_settings().guest_retention_days)
    ids = _with_predecessors(set(_purgeable(cut).values_list("pk", flat=True)))
    if not ids:
        return 0
    actor = portal_actor()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="guest retention"):
        _, deleted = GuestBookingAccess.objects.filter(appointment_id__in=ids).delete()
        accesses = deleted.get(GuestBookingAccess._meta.label, 0)
        count = Appointment.objects.filter(pk__in=ids).update(
            contact_name=GUEST_PLACEHOLDER_NAME, contact_phone="", notes="", updated_at=now
        )
        _event(PortalEventKind.GUEST_PURGED, None, bookings=count, accesses=accesses)
    return count
