from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.portal.models import PortalAccessCode, PortalEvent, PortalSession, PortalThrottle


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
