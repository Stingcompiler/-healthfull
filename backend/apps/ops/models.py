"""Backup runs and restore tests shown on the status page (FEATURES 0.8, 13.8, 14.1)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, track_history


class BackupKind(models.TextChoices):
    NIGHTLY = "nightly", "Nightly"
    MANUAL = "manual", "Manual"
    PRE_UPDATE = "pre_update", "Before an update"


class RunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    PARTIAL = "partial", "Partial (some files missing)"
    FAILED = "failed", "Failed"


class CloudStatus(models.TextChoices):
    PENDING = "pending", "Waiting for internet"
    UPLOADED = "uploaded", "Uploaded"
    FAILED = "failed", "Upload failed"
    SKIPPED = "skipped", "Not configured"


@track_history()
class BackupRun(models.Model):
    """One backup attempt, written by the backup scripts."""

    kind = models.CharField(max_length=20, choices=BackupKind.choices)
    status = models.CharField(max_length=20, choices=RunStatus.choices, default=RunStatus.RUNNING)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    location = models.CharField(max_length=500, blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    cloud_status = models.CharField(
        max_length=20, choices=CloudStatus.choices, default=CloudStatus.PENDING
    )
    cloud_uploaded_at = models.DateTimeField(null=True, blank=True)
    message = models.TextField(blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "backup run"
        ordering: ClassVar[list[str]] = ["-started_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", BackupKind, "ops_backup_kind_valid"),
            choice_check("status", RunStatus, "ops_backup_status_valid"),
            choice_check("cloud_status", CloudStatus, "ops_backup_cloud_status_valid"),
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="ops_backup_finish_after_start",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__isnull=True) | Q(size_bytes__gte=0),
                name="ops_backup_size_non_negative",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "-started_at"], name="ops_backup_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} backup {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class RestoreStatus(models.TextChoices):
    RUNNING = "running", "Running"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"


@track_history()
class RestoreTest(models.Model):
    """A restore of a backup into a scratch database with sanity checks (FEATURES 14.1)."""

    backup = models.ForeignKey(
        BackupRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="restore_tests"
    )
    status = models.CharField(
        max_length=20, choices=RestoreStatus.choices, default=RestoreStatus.RUNNING
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    checks = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        verbose_name = "restore test"
        ordering: ClassVar[list[str]] = ["-started_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", RestoreStatus, "ops_restore_status_valid"),
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="ops_restore_finish_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"restore test {self.started_at:%Y-%m-%d} ({self.status})"
