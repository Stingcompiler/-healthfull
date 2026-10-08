from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.portal.models import PortalAccessCode


@admin.register(PortalAccessCode)
class PortalAccessCodeAdmin(ReadOnlyAdmin[PortalAccessCode]):
    """Read-only, and the hash is never shown."""

    list_display = ("patient", "purpose", "expires_at", "failed_attempts", "revoked_at")
    list_filter = ("purpose",)
    exclude = ("code_hash",)
