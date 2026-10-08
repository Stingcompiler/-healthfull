from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin
from apps.imports.models import ImportJob, ImportRow


@admin.register(ImportJob)
class ImportJobAdmin(ReadOnlyAdmin[ImportJob]):
    list_display = (
        "id",
        "kind",
        "status",
        "original_filename",
        "total_rows",
        "error_rows",
        "created_at",
    )
    list_filter = ("kind", "status")


@admin.register(ImportRow)
class ImportRowAdmin(ReadOnlyAdmin[ImportRow]):
    list_display = ("job", "row_no", "status")
    list_filter = ("status",)
