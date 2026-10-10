from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.ops.models import BackupRequest, BackupRun, DataExport, RestoreTest, UpdateRun


@admin.register(BackupRun)
class BackupRunAdmin(ReadOnlyAdmin[BackupRun]):
    list_display = ("started_at", "kind", "status", "size_bytes", "cloud_status", "finished_at")
    list_filter = ("kind", "status", "cloud_status")


@admin.register(RestoreTest)
class RestoreTestAdmin(ReadOnlyAdmin[RestoreTest]):
    list_display = ("started_at", "status", "backup", "finished_at")
    list_filter = ("status",)


@admin.register(UpdateRun)
class UpdateRunAdmin(ReadOnlyAdmin[UpdateRun]):
    """Update history (FEATURES 13.10): written by the update script, never edited."""

    list_display = ("started_at", "version", "previous_version", "result", "finished_at")
    list_filter = ("result",)


@admin.register(BackupRequest)
class BackupRequestAdmin(ReadOnlyAdmin[BackupRequest]):
    """Manual backup requests (FEATURES 13.8): made on the status page, finished by the
    backup service."""

    list_display = ("requested_at", "requested_by", "status", "started_at", "finished_at")
    list_filter = ("status",)


@admin.register(DataExport)
class DataExportAdmin(ReadOnlyAdmin[DataExport]):
    """Full data exports (FEATURES 13.9): who took one and when."""

    list_display = ("created_at", "requested_by", "finished_at", "size_bytes")
