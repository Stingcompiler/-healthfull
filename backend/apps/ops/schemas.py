"""Schemas of ``/api/ops`` (ARCHITECTURE 4.11): health, system status, manual backup requests,
update history."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.schemas import UserRefOut


class HealthOut(Schema):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    version: str
    time: datetime


class SiteOut(Schema):
    """What the SPA needs before its first render (ADR 0027, 0028). Public; contact values are
    only returned while the marketing page is on. ``center_site``, ``online_booking``,
    ``patient_tracking`` and ``guest_booking`` are the center administrator's switches: the
    root ``/`` shows the center website while ``center_site`` is on and no staff session
    exists."""

    marketing: bool
    contact_email: str | None = None
    contact_whatsapp: str | None = None
    center_site: bool = False
    online_booking: bool = False
    patient_tracking: bool = False
    guest_booking: bool = Field(
        False, description="Booking without a patient file (on only while online_booking is on)"
    )


class OpsDatabaseOut(Schema):
    ok: bool
    server_version: str
    size_bytes: int | None


class OpsDiskOut(Schema):
    label: Literal["media", "backups"]
    total_bytes: int
    free_bytes: int
    free_percent: float


class OpsMigrationsOut(Schema):
    applied: int
    pending: int
    pending_names: list[str]


class OpsRunOut(Schema):
    """A backup or restore test from the status logs (``log``) or the database (``db``)."""

    source: Literal["log", "db"]
    status: str = Field(..., description="ok, partial (backups), failed or running")
    started_at: datetime | None
    finished_at: datetime | None
    size_bytes: int | None
    label: str = Field(..., description="Backup label, e.g. manual-12 or pre-update-v1.4.0")
    file: str = Field(..., description="File name of the dump (no folder)")
    error: str


BackupRequestStatusCode = Literal["pending", "running", "succeeded", "partial", "failed"]


class BackupRequestOut(Schema):
    id: int
    status: BackupRequestStatusCode
    note: str
    requested_at: datetime
    requested_by: UserRefOut
    started_at: datetime | None
    finished_at: datetime | None
    dump_file: str = Field(..., description="File name of the dump (no folder)")
    message: str

    @staticmethod
    def resolve_dump_file(obj: object) -> str:
        return str(getattr(obj, "dump_file", "") or "").rsplit("/", 1)[-1]


class UpdateRunOut(Schema):
    id: int
    version: str
    previous_version: str
    release_notes: str
    result: Literal["running", "succeeded", "failed", "rolled_back"]
    started_at: datetime
    finished_at: datetime | None
    started_by: UserRefOut | None
    run_key: str | None = Field(..., description="The update script's run id; null when by hand")
    migration_plan: str = Field(..., description="`migrate --plan` of the new version")
    migrations_applied: bool
    db_restored: bool = Field(..., description="The rollback restored the pre-update dump")
    backup_file: str = Field(..., description="File name of the pre-update dump (no folder)")
    detail: str = Field(..., description="Why it failed or rolled back, and in which step")
    log: str = Field(..., description="The last lines of the update script's log")

    @staticmethod
    def resolve_backup_file(obj: object) -> str:
        return str(getattr(obj, "backup_file", "") or "").rsplit("/", 1)[-1]


OpsWarningCode = Literal[
    "DB_UNAVAILABLE",
    "BACKUP_STATUS_UNAVAILABLE",
    "BACKUP_STALE",
    "BACKUP_FAILED",
    "RESTORE_TEST_STALE",
    "RESTORE_TEST_FAILED",
    "DISK_LOW",
    "MIGRATIONS_PENDING",
    "INTEGRITY_FAILED",
]


class IntegrityCheckOut(Schema):
    name: str
    ok: bool
    checked: int
    problems: int
    examples: list[str]


class IntegrityRunOut(Schema):
    """The newest recorded ``manage.py integrity_check`` (daily from the maintenance loop)."""

    id: int
    started_at: datetime
    finished_at: datetime
    ok: bool
    source: Literal["scheduled", "manual"]
    results: list[IntegrityCheckOut]


class SystemStatusOut(Schema):
    version: str
    time: datetime
    database: OpsDatabaseOut
    disks: list[OpsDiskOut]
    migrations: OpsMigrationsOut
    last_backup: OpsRunOut | None = Field(..., description="The newest ok or partial backup")
    last_restore_test: OpsRunOut | None
    backups: list[OpsRunOut]
    restore_tests: list[OpsRunOut]
    pending_cloud_uploads: int
    backup_requests: list[BackupRequestOut]
    status_dir_configured: bool
    last_update: UpdateRunOut | None
    last_integrity_check: IntegrityRunOut | None
    warnings: list[OpsWarningCode]


class BackupRequestIn(Schema):
    note: str = Field("", max_length=200)


class UpdateLogOut(Schema):
    """One run of ``infra/update.sh`` from its status log (update-runs.jsonl)."""

    status: str = Field(..., description="ok, failed or rolled_back")
    from_tag: str
    to_tag: str
    started_at: datetime | None
    finished_at: datetime | None
    migrations_applied: bool
    db_restored: bool
    detail: str


class UpdateHistoryOut(Schema):
    current_version: str
    log: list[UpdateLogOut] = Field(..., description="The update script's log, newest first")
    items: list[UpdateRunOut]
    count: int
    page: int
    page_size: int


class UpdateParams(PageParams):
    pass
