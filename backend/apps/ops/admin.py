from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.ops.models import BackupRun, RestoreTest


@admin.register(BackupRun)
class BackupRunAdmin(ReadOnlyAdmin[BackupRun]):
    list_display = ("started_at", "kind", "status", "size_bytes", "cloud_status", "finished_at")
    list_filter = ("kind", "status", "cloud_status")


@admin.register(RestoreTest)
class RestoreTestAdmin(ReadOnlyAdmin[RestoreTest]):
    list_display = ("started_at", "status", "backup", "finished_at")
    list_filter = ("status",)
