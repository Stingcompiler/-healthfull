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


class PortalThrottle(models.Model):
    """Abuse counters of the portal (ADR 0016), like ``core.LoginThrottle`` for staff.

    * ``ip``: failed sign-ins per address in a fixed window (``domain.throttle``): 429.
    * ``file``: the lockout state (``domain.lockout``) of a typed file number, whether a file
      has it or not, so a locked answer never tells which file numbers exist.
    * ``verify_ip``: public receipt checks per address in a fixed window: 429.

    Bookkeeping, not audit (that is ``PortalEvent``).
    """

    scope = models.CharField(max_length=10, choices=PortalThrottleScope.choices)
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


class PortalEvent(models.Model):
    """Append-only audit of portal access (FEATURES 14.4 for patients). Protected by a DB
    trigger. ``file_no`` is what was typed (normalized), kept even when no file has it."""

    kind = models.CharField(max_length=20, choices=PortalEventKind.choices)
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
