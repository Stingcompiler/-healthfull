"""Excel imports with preview and confirm (FEATURES 1.8, 8.13).

An ``ImportJob`` holds the uploaded file; validation writes one ``ImportRow`` per sheet row
with its parsed data, errors and duplicate hints. Nothing reaches the real tables until a
user confirms the job.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.db import choice_check, track_history


class ImportKind(models.TextChoices):
    PATIENTS = "patients", "Patients"
    SERVICES = "services", "Services"
    PRICES = "prices", "Price list"
    ITEMS = "items", "Stock items"
    BATCHES = "batches", "Batches"
    OPENING_STOCK = "opening_stock", "Opening stock"
    ICD10 = "icd10", "ICD-10 codes"
    LAB_TESTS = "lab_tests", "Lab tests"


class ImportStatus(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    VALIDATED = "validated", "Validated (preview)"
    CONFIRMED = "confirmed", "Imported"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class ImportJob(models.Model):
    kind = models.CharField(max_length=20, choices=ImportKind.choices)
    status = models.CharField(
        max_length=20, choices=ImportStatus.choices, default=ImportStatus.UPLOADED
    )
    file = models.FileField(upload_to="imports/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    options = models.JSONField(default=dict, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "import job"
        ordering: ClassVar[list[str]] = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", ImportKind, "imports_job_kind_valid"),
            choice_check("status", ImportStatus, "imports_job_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=ImportStatus.CONFIRMED)
                | Q(confirmed_by__isnull=False, confirmed_at__isnull=False),
                name="imports_job_confirmation_documented",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} import {self.pk} ({self.status})"


class RowStatus(models.TextChoices):
    VALID = "valid", "Valid"
    WARNING = "warning", "Valid with warnings"
    ERROR = "error", "Error"
    DUPLICATE = "duplicate", "Possible duplicate"
    IMPORTED = "imported", "Imported"
    SKIPPED = "skipped", "Skipped"


class ImportRow(models.Model):
    """One parsed sheet row. Bulk bookkeeping of a job: not history-tracked."""

    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="rows")
    row_no = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=RowStatus.choices)
    data = models.JSONField(default=dict)
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    duplicate_of_id = models.BigIntegerField(null=True, blank=True)
    result_id = models.BigIntegerField(
        null=True, blank=True, help_text="Primary key of the created/updated row."
    )

    class Meta:
        verbose_name = "import row"
        ordering: ClassVar[list[str]] = ["job", "row_no"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", RowStatus, "imports_row_status_valid"),
            models.UniqueConstraint(fields=["job", "row_no"], name="imports_row_unique"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["job", "status"], name="imports_row_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.job_id}:{self.row_no} {self.status}"
