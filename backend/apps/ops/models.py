"""Backup runs, restore tests and update runs shown on the status page (FEATURES 0.8,
13.8, 13.10, 14.1)."""

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


class UpdateResult(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    ROLLED_BACK = "rolled_back", "Rolled back"


@track_history()
class UpdateRun(models.Model):
    """One application update (FEATURES 13.10): version shown, release notes, rollback log.

    Written by ``infra/update.sh`` through ``manage.py record_update`` (one call per run, at
    its end; ``run_key`` makes a repeated call update the same row); the status page shows the
    running version and the history.

    The columns added after the first release carry database defaults, so an older image
    started by a rollback (which does not know them) can still insert rows.
    """

    #: The update script's run id (``<UTC stamp>-<tag>``); empty for rows written by hand.
    run_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    version = models.CharField(max_length=50)
    previous_version = models.CharField(max_length=50, blank=True)
    release_notes = models.TextField(blank=True)
    result = models.CharField(
        max_length=20, choices=UpdateResult.choices, default=UpdateResult.RUNNING
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    #: ``manage.py migrate --plan`` of the new version, read before anything changed.
    migration_plan = models.TextField(blank=True, default="", db_default="")
    migrations_applied = models.BooleanField(default=False, db_default=False)
    #: The rollback restored the pre-update dump (``--restore-db-on-failure``).
    db_restored = models.BooleanField(default=False, db_default=False)
    #: The verified pre-update dump a rollback can restore.
    backup_file = models.CharField(max_length=500, blank=True, default="", db_default="")
    #: Why it failed or rolled back, and in which step.
    detail = models.TextField(blank=True, default="", db_default="")
    log = models.TextField(blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "update run"
        ordering: ClassVar[list[str]] = ["-started_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("result", UpdateResult, "ops_update_result_valid"),
            models.CheckConstraint(
                condition=Q(result=UpdateResult.RUNNING) | Q(finished_at__isnull=False),
                name="ops_update_finished_documented",
            ),
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="ops_update_finish_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.version} ({self.result})"


class BackupRequestStatus(models.TextChoices):
    PENDING = "pending", "Waiting for the backup service"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    PARTIAL = "partial", "Partial (some files missing)"
    FAILED = "failed", "Failed"


#: Requests the backup service has not finished yet.
OPEN_BACKUP_REQUESTS = (BackupRequestStatus.PENDING, BackupRequestStatus.RUNNING)


@track_history()
class BackupRequest(models.Model):
    """A manual backup asked for on the status page (FEATURES 13.8).

    The app never runs a backup itself: it records the request, and the backup service
    (``infra/backup/backup-requests.sh``, polled by the sidecar's scheduler or a host timer)
    claims it, runs ``backup-nightly.sh --label manual-<id>`` and writes the outcome back.
    """

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20, choices=BackupRequestStatus.choices, default=BackupRequestStatus.PENDING
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    dump_file = models.CharField(max_length=500, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        verbose_name = "backup request"
        ordering: ClassVar[list[str]] = ["-requested_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", BackupRequestStatus, "ops_backup_request_status_valid"),
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status=BackupRequestStatus.PENDING),
                name="ops_backup_request_one_pending",
            ),
            models.CheckConstraint(
                condition=Q(status__in=OPEN_BACKUP_REQUESTS) | Q(finished_at__isnull=False),
                name="ops_backup_request_finish_documented",
            ),
        ]

    def __str__(self) -> str:
        return f"backup request {self.pk} ({self.status})"


@track_history()
class DataExport(models.Model):
    """One full data export (FEATURES 13.9): who took it, when, which tables and how many rows.

    Written before the first byte is sent and completed when the archive is finished, so an
    export that was started but not finished still shows in the audit trail.
    """

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    tables = models.JSONField(default=list)
    row_counts = models.JSONField(default=dict, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "data export"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(size_bytes__isnull=True) | Q(size_bytes__gte=0),
                name="ops_export_size_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"data export {self.pk} by {self.requested_by_id}"
