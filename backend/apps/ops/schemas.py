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


OpsWarningCode = Literal[
    "DB_UNAVAILABLE",
    "BACKUP_STATUS_UNAVAILABLE",
    "BACKUP_STALE",
    "BACKUP_FAILED",
    "RESTORE_TEST_STALE",
    "RESTORE_TEST_FAILED",
    "DISK_LOW",
    "MIGRATIONS_PENDING",
]


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
