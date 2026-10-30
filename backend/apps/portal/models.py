"""Patient portal: access codes, sessions, abuse counters and audit (FEATURES 15.2, ADR 0016).

The code itself is never stored: ``code_hash`` holds a Django password hash of it. A code
expires, locks after ``max_attempts`` failed tries and can be revoked; issuing a new code for
a file revokes the earlier ones.
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, track_history


class AccessPurpose(models.TextChoices):
    RESULTS = "results", "View approved results"
    RECEIPT = "receipt", "Verify a receipt"
    APPOINTMENTS = "appointments", "Appointments"


@track_history(exclude=["code_hash"])
class PortalAccessCode(models.Model):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="portal_codes"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    purpose = models.CharField(
        max_length=20, choices=AccessPurpose.choices, default=AccessPurpose.RESULTS
    )
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    revoke_note = models.CharField(
        max_length=300,
        blank=True,
        help_text="Why staff revoked it; empty when a newer code replaced it.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "portal access code"
        ordering: ClassVar[list[str]] = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("purpose", AccessPurpose, "portal_code_purpose_valid"),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="portal_code_attempts_positive"
            ),
            models.CheckConstraint(
                condition=Q(failed_attempts__lte=F("max_attempts")),
                name="portal_code_attempts_within_max",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")), name="portal_code_expires_later"
            ),
            models.CheckConstraint(condition=~Q(code_hash=""), name="portal_code_hash_required"),
            models.CheckConstraint(
                condition=Q(revoked_at__isnull=True) | Q(revoked_by__isnull=False),
                name="portal_code_revoke_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "expires_at"], name="portal_code_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"portal code {self.pk} for {self.patient_id}"


class PortalSession(models.Model):
    """A signed-in patient on the portal (ADR 0016). Never a staff session.

    The browser holds a random token in its own cookie; only its SHA-256 is stored, so a
    database copy cannot be replayed. ``patient`` is the surviving file at sign-in; every
    request re-resolves merges. A session ends at logout, after ``PORTAL_SESSION_IDLE_SECONDS``
    without use, or ``PORTAL_SESSION_MAX_SECONDS`` after sign-in.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="portal_sessions"
    )
    code = models.ForeignKey(
        PortalAccessCode, on_delete=models.PROTECT, null=True, blank=True, related_name="sessions"
    )
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "portal session"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(last_seen_at__gte=F("created_at")), name="portal_session_seen_after"
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | ~Q(end_reason=""),
                name="portal_session_end_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "created_at"], name="portal_session_patient_idx"),
            models.Index(fields=["last_seen_at"], name="portal_session_seen_idx"),
        ]

    def __str__(self) -> str:
        return f"portal session {self.pk} for {self.patient_id}"


class PortalThrottleScope(models.TextChoices):
    IP = "ip", "Failed portal sign-ins per client address"
    FILE = "file", "Failed portal sign-ins per file number (known or not)"
    VERIFY_IP = "verify_ip", "Public receipt checks per client address"
    PAGE_IP = "page_ip", "Public center page reads per client address"
    GUEST_IP = "guest_ip", "Failed guest booking sign-ins per client address"
    BOOK_IP = "book_ip", "Guest booking requests per client address per day"
    GUEST_PHONE = "guest_phone", "Guest bookings of one phone number (the booking lock)"


class PortalThrottle(models.Model):
    """Abuse counters of the portal (ADR 0016), like ``core.LoginThrottle`` for staff.

    * ``ip``: failed sign-ins per address in a fixed window (``domain.throttle``): 429.
    * ``file``: the lockout state (``domain.lockout``) of a typed file number, whether a file
      has it or not, so a locked answer never tells which file numbers exist.
    * ``verify_ip``: public receipt checks per address in a fixed window: 429.
    * ``page_ip``: public center page and logo reads per address in a fixed window: 429.
    * ``guest_ip``: failed guest sign-ins per address in a fixed window: 429 (ADR 0029 D).
    * ``book_ip``: guest booking requests per address per day: 429 (ADR 0029 F).
    * ``guest_phone``: one row per phone number, row-locked while a guest books, so two
      requests cannot race past the per-phone cap (no count is kept in it).

    Bookkeeping, not audit (that is ``PortalEvent``).
    """

    scope = models.CharField(max_length=30, choices=PortalThrottleScope.choices)
    key = models.CharField(max_length=64)
    count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "portal throttle"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["scope", "key"], name="portal_throttle_unique"),
            choice_check("scope", PortalThrottleScope, "portal_throttle_scope_valid"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["updated_at"], name="portal_throttle_updated_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}={self.count}"


class PortalEventKind(models.TextChoices):
    CODE_ISSUED = "code_issued", "Access code issued"
    CODE_REVOKED = "code_revoked", "Access code revoked by staff"
    LOGIN_SUCCESS = "login_success", "Signed in"
    LOGIN_FAILED = "login_failed", "Sign-in refused: wrong details"
    LOGIN_LOCKED = "login_locked", "Sign-in refused: file number locked"
    LOGIN_THROTTLED = "login_throttled", "Sign-in refused: too many failures from this address"
    CODE_LOCKED = "code_locked", "Access code locked after repeated wrong codes"
    LOGOUT = "logout", "Signed out"
    VERIFY_THROTTLED = "verify_throttled", "Receipt check refused: too many from this address"
    PAGE_THROTTLED = "page_throttled", "Center page refused: too many reads from this address"
    # Guest booking (ADR 0029 D, F, G).
    GUEST_BOOKING_CREATED = "guest_booking_created", "Guest booking made on the website"
    GUEST_VIEW = "guest_view", "Guest signed in to their booking"
    GUEST_VIEW_REFUSED = "guest_view_refused", "Guest sign-in refused: wrong reference or PIN"
    GUEST_LOCKED = "guest_locked", "Guest booking locked after repeated wrong PINs"
    GUEST_THROTTLED = "guest_throttled", "Guest sign-in refused: too many from this address"
    GUEST_LOGOUT = "guest_logout", "Guest signed out"
    GUEST_CANCELLED = "guest_cancelled", "Guest cancelled their booking"
    GUEST_PIN_REISSUED = "guest_pin_reissued", "Staff issued a new guest PIN"
    GUEST_PURGED = "guest_purged", "Old guest bookings anonymized (counts only)"
    BOOKING_RESCHEDULED = "booking_rescheduled", "Booking moved online by its booker"
    BOOKING_THROTTLED = "booking_throttled", "Guest booking refused: too many from this address"


class PortalEvent(models.Model):
    """Append-only audit of portal access (FEATURES 14.4 for patients). Protected by a DB
    trigger. ``file_no`` is what was typed (normalized), kept even when no file has it."""

    kind = models.CharField(max_length=30, choices=PortalEventKind.choices)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    file_no = models.CharField(max_length=30, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "portal event"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", PortalEventKind, "portal_event_kind_valid"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.Protect(name="append_only", operation=pgtrigger.Update | pgtrigger.Delete),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.file_no} @ {self.created_at:%Y-%m-%d %H:%M}"


# --- guest booking (ADR 0029 D, F) ------------------------------------------------------


@track_history(exclude=["pin_hash"])
class GuestBookingAccess(models.Model):
    """How a guest without a file reaches their booking: a reference (10 base32 characters)
    and a PIN shown once, stored only as a password hash (ADR 0029 D).

    The access belongs to the booking **chain**, not to one appointment row: a reschedule
    creates a new appointment and the service moves ``appointment`` to it in the same
    transaction. ``failed_attempts`` wrong PINs lock it for good (``locked_at``) until staff
    issue a new PIN. The retention sweep deletes it with the guest's name and phone.
    """

    appointment = models.OneToOneField(
        "visits.Appointment", on_delete=models.PROTECT, related_name="guest_access"
    )
    reference = models.CharField(max_length=10, unique=True)
    pin_hash = models.CharField(max_length=256)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    locked_at = models.DateTimeField(null=True, blank=True)
    pin_issued_at = models.DateTimeField()
    pin_issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff who issued the current PIN; empty for the one shown at booking.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "guest booking access"
        verbose_name_plural = "guest booking access"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(reference__regex=r"^[A-Z2-7]{10}$"), name="portal_guest_reference_shape"
            ),
            models.CheckConstraint(condition=~Q(pin_hash=""), name="portal_guest_pin_required"),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="portal_guest_attempts_positive"
            ),
            models.CheckConstraint(
                condition=Q(failed_attempts__lte=F("max_attempts")),
                name="portal_guest_attempts_within_max",
            ),
        ]

    def __str__(self) -> str:
        return f"guest access {self.reference}"


class GuestSession(models.Model):
    """A guest signed in to one booking (cookie ``hospital_guest``, path ``/api/portal/guest``).

    Like ``PortalSession``: only the SHA-256 of the token is stored; it ends at sign-out, when
    idle or too old, when staff issue a new PIN, or when the access is deleted. Never a
    patient or staff session.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    access = models.ForeignKey(
        GuestBookingAccess, on_delete=models.CASCADE, related_name="sessions"
    )
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "guest session"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(last_seen_at__gte=F("created_at")), name="portal_guest_session_seen"
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | ~Q(end_reason=""),
                name="portal_guest_session_end_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["last_seen_at"], name="portal_guest_session_seen_idx"),
        ]

    def __str__(self) -> str:
        return f"guest session {self.pk}"


class IdempotentRequest(models.Model):
    """The stored answer of a public booking POST (ADR 0029 C): the same ``Idempotency-Key``
    with the same body gets this answer again; with another body, 409
    ``IDEMPOTENCY_MISMATCH``. Rows are deleted 24 hours after creation (``maintenance``).

    ``key_hash`` is the SHA-256 of the client's key, so a database copy cannot replay it. The
    PIN of a guest booking is not in ``body``: ``sealed`` holds it encrypted with a key derived
    from the server secret and the client's key (``apps.portal.guest``), so only the client
    that sent the request can get it back, and only for 24 hours.
    """

    scope = models.CharField(max_length=30)
    key_hash = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    status = models.PositiveSmallIntegerField()
    body = models.JSONField(default=dict)
    sealed = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "idempotent request"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["scope", "key_hash"], name="portal_idempotent_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key_hash[:8]}"


class UsedChallenge(models.Model):
    """A proof-of-work challenge already spent (ADR 0029 F: single use). Kept until it would
    have expired anyway, then deleted by ``maintenance``."""

    challenge_id = models.CharField(max_length=16, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "used challenge"

    def __str__(self) -> str:
        return self.challenge_id


# --- patient notices (ADR 0029 I; Phase 5) ------------------------------------------------


class PatientNoticeKind(models.TextChoices):
    """``domain.portal_status.NoticeKind`` (the values are the domain's)."""

    BOOKING_REQUESTED = "booking_requested", "Online booking waiting for reception"
    BOOKING_CONFIRMED = "booking_confirmed", "Booking confirmed"
    BOOKING_DECLINED = "booking_declined", "Online request declined"
    BOOKING_CANCELLED = "booking_cancelled", "Booking cancelled"
    BOOKING_RESCHEDULED = "booking_rescheduled", "Booking moved to another time"
    BOOKING_EXPIRED = "booking_expired", "Online request expired unanswered"
    RESULT_PUBLISHED = "result_published", "A lab result is approved and visible"


@track_history()
class PatientNotice(models.Model):
    """One line of a patient's portal inbox (ADR 0029 I): written by ``patients.notify`` in
    the same transaction as its event (a booking change, a result approval), so a rolled-back
    event leaves no notice. Only for a patient file: a guest has no inbox.

    ``payload`` holds what the inbox needs to say it in either language (doctor names, the
    slot, a test name, the reason label staff chose); never a price, a staff note or a value
    the portal does not already show. ``appointment`` / ``service_line`` link the notice to
    the row it is about; the portal still checks the row is the patient's before showing it.
    A notice never changes except ``read_at`` (once) and is never deleted (triggers).
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="portal_notices"
    )
    kind = models.CharField(max_length=30, choices=PatientNoticeKind.choices)
    payload = models.JSONField(default=dict, blank=True)
    channels = models.JSONField(
        default=list, blank=True, help_text='Channels it went out on; V1 is ["portal"] only.'
    )
    appointment = models.ForeignKey(
        "visits.Appointment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    service_line = models.ForeignKey(
        "orders.ServiceLine", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "patient notice"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", PatientNoticeKind, "portal_notice_kind_valid"),
            models.CheckConstraint(
                condition=Q(read_at__isnull=True) | Q(read_at__gte=F("created_at")),
                name="portal_notice_read_after_created",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "created_at"], name="portal_notice_patient_idx"),
            models.Index(
                fields=["patient"],
                condition=Q(read_at__isnull=True),
                name="portal_notice_unread_idx",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.Protect(name="notice_permanent", operation=pgtrigger.Delete),
            pgtrigger.Protect(
                name="notice_fixed",
                operation=pgtrigger.Update,
                condition=pgtrigger.AnyChange(exclude=["read_at"]),
            ),
            pgtrigger.Protect(
                name="notice_read_once",
                operation=pgtrigger.Update,
                condition=pgtrigger.Q(old__read_at__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} for {self.patient_id}"
