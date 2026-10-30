from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.portal.models import (
    GuestBookingAccess,
    GuestSession,
    IdempotentRequest,
    PortalAccessCode,
    PortalEvent,
    PortalSession,
    PortalThrottle,
    UsedChallenge,
)


@admin.register(PortalAccessCode)
class PortalAccessCodeAdmin(ReadOnlyAdmin[PortalAccessCode]):
    """Read-only, and the hash is never shown."""

    list_display = ("patient", "purpose", "expires_at", "failed_attempts", "revoked_at")
    list_filter = ("purpose",)
    exclude = ("code_hash",)


@admin.register(PortalSession)
class PortalSessionAdmin(ReadOnlyAdmin[PortalSession]):
    """Read-only sign-in record; the token hash is never shown."""

    list_display = ("patient", "created_at", "last_seen_at", "ended_at", "end_reason", "ip_address")
    list_filter = ("end_reason",)
    exclude = ("token_hash",)


@admin.register(PortalThrottle)
class PortalThrottleAdmin(ReadOnlyAdmin[PortalThrottle]):
    list_display = ("scope", "key", "count", "window_started_at", "locked_until", "updated_at")
    list_filter = ("scope",)


@admin.register(PortalEvent)
class PortalEventAdmin(ReadOnlyAdmin[PortalEvent]):
    list_display = ("kind", "file_no", "patient", "ip_address", "created_at")
    list_filter = ("kind",)


@admin.register(GuestBookingAccess)
class GuestBookingAccessAdmin(ReadOnlyAdmin[GuestBookingAccess]):
    """Read-only; the PIN hash is never shown (ADR 0029 D)."""

    list_display = ("reference", "appointment", "failed_attempts", "locked_at", "created_at")
    exclude = ("pin_hash",)


@admin.register(GuestSession)
class GuestSessionAdmin(ReadOnlyAdmin[GuestSession]):
    """Read-only sign-in record; the token hash is never shown."""

    list_display = ("access", "created_at", "last_seen_at", "ended_at", "end_reason", "ip_address")
    exclude = ("token_hash",)


@admin.register(IdempotentRequest)
class IdempotentRequestAdmin(ReadOnlyAdmin[IdempotentRequest]):
    """Read-only; the sealed PIN and the key hash are never shown."""

    list_display = ("scope", "status", "created_at")
    exclude = ("sealed", "key_hash", "request_hash")


@admin.register(UsedChallenge)
class UsedChallengeAdmin(ReadOnlyAdmin[UsedChallenge]):
    list_display = ("challenge_id", "expires_at", "used_at")
