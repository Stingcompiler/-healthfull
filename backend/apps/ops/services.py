"""Operations (FEATURES 0.8, 13.8, 13.10, 14.1): health, the system status page, manual backup
requests and update history.

* :func:`health` is the unauthenticated liveness probe.
* :func:`system_status` gathers the status page: database, disk space, application version,
  migrations, the last backups and restore tests, pending cloud uploads, backup requests and
  warnings. Backups and restore tests come from the JSON lines the backup scripts write
  (``BACKUP_STATUS_DIR``: ``backup-runs.jsonl``, ``restore-tests.jsonl``; the app mounts the
  directory read-only) and from ``BackupRun`` / ``RestoreTest`` rows; the newest wins.
* :func:`request_backup` records a :class:`BackupRequest`; the backup service picks it up
  (``infra/backup/backup-requests.sh``). A request never runs a command on the app server.
* :func:`record_update_run` stores one run of ``infra/update.sh`` (``manage.py record_update``);
  :func:`update_runs` lists the recorded updates.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pghistory
import structlog
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import User
from apps.core.services import require_permission
from apps.ops.models import (
    OPEN_BACKUP_REQUESTS,
    BackupRequest,
    BackupRun,
    CloudStatus,
    RestoreTest,
    RunStatus,
    UpdateResult,
    UpdateRun,
)
from domain.errors import DomainError

logger = structlog.get_logger(__name__)

__all__ = [
    "BACKUP_STALE_HOURS",
    "DISK_LOW_PERCENT",
    "RESTORE_TEST_STALE_DAYS",
    "UpdateRecord",
    "check_database",
    "health",
    "last_backup",
    "record_update_run",
    "request_backup",
    "system_status",
    "update_log",
    "update_runs",
]

#: A backup older than this is a warning on the status page (and a daily alert).
BACKUP_STALE_HOURS = 36
#: A restore test older than this (monthly tests) is a warning.
RESTORE_TEST_STALE_DAYS = 35
#: Free space below this percentage of a disk is a warning.
DISK_LOW_PERCENT = 10
#: Status log lines read from the end of each file.
_TAIL_BYTES = 256 * 1024


def check_database() -> bool:
    """True if a trivial query succeeds on the default database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
    except Exception:
        logger.warning("health.db_unavailable", exc_info=True)
        return False
    return row is not None and row[0] == 1


def health() -> dict[str, Any]:
    db_ok = check_database()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "version": settings.APP_VERSION,
        "time": timezone.now(),
    }


# --- backup status lines --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunInfo:
    """A backup or restore test as the status page shows it, from either source."""

    source: str  # "log" (status JSON lines) or "db" (BackupRun / RestoreTest)
    status: str  # backups: ok, partial, failed, running; restore tests: ok, failed, running
    started_at: datetime | None
    finished_at: datetime | None
    size_bytes: int | None
    label: str
    file: str
    error: str


def status_dir() -> Path | None:
    raw = str(getattr(settings, "BACKUP_STATUS_DIR", "") or "")
    return Path(raw) if raw else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


def _tail_lines(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    if len(raw.encode()) >= _TAIL_BYTES and lines:
        lines = lines[1:]  # the first line may be cut
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _log_runs(kind: str) -> list[RunInfo]:
    """Backup (``backup``) or restore test (``restore_test``) lines, newest last."""
    folder = status_dir()
    if folder is None:
        return []
    name = "backup-runs.jsonl" if kind == "backup" else "restore-tests.jsonl"
    runs: list[RunInfo] = []
    for line in _tail_lines(folder / name):
        if line.get("type") != kind:
            continue
        dump = line.get("dump")
        if isinstance(dump, dict):
            file, size = str(dump.get("file") or ""), _int(dump.get("size_bytes"))
        else:
            file, size = str(dump or ""), _int(line.get("dump_size_bytes"))
        runs.append(
            RunInfo(
                source="log",
                status=str(line.get("status") or "failed")[:20],
                started_at=_when(line.get("started_at")),
                finished_at=_when(line.get("finished_at")),
                size_bytes=size,
                label=str(line.get("label") or "")[:64],
                file=Path(file).name[:200],
                error=str(line.get("error") or "")[:500],
            )
        )
    return runs


_BACKUP_DB_STATUS: dict[str, str] = {
    RunStatus.SUCCEEDED: "ok",
    RunStatus.PARTIAL: "partial",
    RunStatus.FAILED: "failed",
    RunStatus.RUNNING: "running",
}


def _db_backups(limit: int) -> list[RunInfo]:
    return [
        RunInfo(
            source="db",
            status=_BACKUP_DB_STATUS.get(r.status, r.status),
            started_at=r.started_at,
            finished_at=r.finished_at,
            size_bytes=r.size_bytes,
            label=r.kind,
            file=Path(r.location).name[:200],
            error=r.message[:500],
        )
        for r in BackupRun.objects.order_by("-started_at")[:limit]
    ]


def _db_restore_tests(limit: int) -> list[RunInfo]:
    return [
        RunInfo(
            source="db",
            status={"passed": "ok"}.get(r.status, r.status),
            started_at=r.started_at,
            finished_at=r.finished_at,
            size_bytes=None,
            label="",
            file="",
            error=r.message[:500],
        )
        for r in RestoreTest.objects.order_by("-started_at")[:limit]
    ]


def _newest_first(runs: list[RunInfo], limit: int) -> list[RunInfo]:
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(runs, key=lambda r: r.finished_at or r.started_at or epoch, reverse=True)[:limit]


def recent_backups(limit: int = 10) -> list[RunInfo]:
    return _newest_first([*_log_runs("backup"), *_db_backups(limit)], limit)


def recent_restore_tests(limit: int = 5) -> list[RunInfo]:
    return _newest_first([*_log_runs("restore_test"), *_db_restore_tests(limit)], limit)


def last_backup(*, successful: bool = True) -> RunInfo | None:
    """The newest backup (only ok or partial ones with ``successful``)."""
    for run in recent_backups(limit=50):
        if not successful or run.status in ("ok", "partial"):
            return run
    return None


# --- the status page ------------------------------------------------------------------------


def _database() -> dict[str, Any]:
    ok = check_database()
    info: dict[str, Any] = {"ok": ok, "server_version": "", "size_bytes": None}
    if not ok:
        return info
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('server_version'), pg_database_size(current_database())"
        )
        row = cursor.fetchone()
    if row is not None:
        info["server_version"] = str(row[0])
        info["size_bytes"] = int(row[1])
    return info


def _disks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    folder = status_dir()
    for label, path in (("media", Path(settings.MEDIA_ROOT)), ("backups", folder)):
        if path is None:
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        free_percent = round(usage.free * 100 / usage.total, 1) if usage.total else 0.0
        out.append(
            {
                "label": label,
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "free_percent": free_percent,
            }
        )
    return out


def _migrations() -> dict[str, Any]:
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    pending = [f"{m.app_label}.{m.name}" for m, backwards in plan if not backwards]
    applied = len(executor.loader.applied_migrations)
    return {"applied": applied, "pending": len(pending), "pending_names": pending[:20]}


def _run_dict(run: RunInfo | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "source": run.source,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "size_bytes": run.size_bytes,
        "label": run.label,
        "file": run.file,
        "error": run.error,
    }


def system_status(*, now: datetime | None = None) -> dict[str, Any]:
    """Everything the status page shows (FEATURES 0.8, 13.8, 14.1), with warning codes."""
    at = now or timezone.now()
    folder = status_dir()
    backups = recent_backups()
    restores = recent_restore_tests()
    last_ok = next((r for r in backups if r.status in ("ok", "partial")), None)
    last_restore = next((r for r in restores if r.status != "running"), None)
    db = _database()
    disks = _disks()
    migrations = _migrations() if db["ok"] else {"applied": 0, "pending": 0, "pending_names": []}
    warnings: list[str] = []
    if not db["ok"]:
        warnings.append("DB_UNAVAILABLE")
    if folder is None or not folder.is_dir():
        warnings.append("BACKUP_STATUS_UNAVAILABLE")
    last_time = last_ok.finished_at if last_ok else None
    if last_time is None or at - last_time > timedelta(hours=BACKUP_STALE_HOURS):
        warnings.append("BACKUP_STALE")
    if backups and backups[0].status == "failed":
        warnings.append("BACKUP_FAILED")
    if last_restore is None or (
        last_restore.finished_at is not None
        and at - last_restore.finished_at > timedelta(days=RESTORE_TEST_STALE_DAYS)
    ):
        warnings.append("RESTORE_TEST_STALE")
    elif last_restore.status == "failed":
        warnings.append("RESTORE_TEST_FAILED")
    if any(d["free_percent"] < DISK_LOW_PERCENT for d in disks):
        warnings.append("DISK_LOW")
    if migrations["pending"]:
        warnings.append("MIGRATIONS_PENDING")
    pending_cloud = BackupRun.objects.filter(
        cloud_status=CloudStatus.PENDING, status__in=[RunStatus.SUCCEEDED, RunStatus.PARTIAL]
    ).count()
    latest_update = UpdateRun.objects.order_by("-started_at").first()
    return {
        "version": settings.APP_VERSION,
        "time": at,
        "database": db,
        "disks": disks,
        "migrations": migrations,
        "last_backup": _run_dict(last_ok),
        "last_restore_test": _run_dict(last_restore),
        "backups": [_run_dict(r) for r in backups],
        "restore_tests": [_run_dict(r) for r in restores],
        "pending_cloud_uploads": pending_cloud,
        "backup_requests": list(
            BackupRequest.objects.select_related("requested_by").order_by("-requested_at", "-id")[
                :5
            ]
        ),
        "status_dir_configured": folder is not None,
        "last_update": latest_update,
        "warnings": warnings,
    }


# --- manual backup --------------------------------------------------------------------------


def request_backup(*, actor: User, note: str = "") -> BackupRequest:
    """Ask the backup service for a backup now (FEATURES 13.8).

    Only a row is written; the backup sidecar or host timer claims it within its polling
    interval and records the outcome on it.

    Raises:
        PermissionRequired: the actor lacks ``ops.trigger_backup``.
        DomainError: ``BACKUP_REQUEST_OPEN`` (one is already waiting or running).
    """
    require_permission(actor, "ops.trigger_backup")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="manual backup request"):
        with connection.cursor() as cursor:
            # One writer at a time decides whether a request is already open.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('ops.backup_request'))")
        open_request = BackupRequest.objects.filter(status__in=OPEN_BACKUP_REQUESTS).first()
        if open_request is not None:
            raise DomainError(
                "BACKUP_REQUEST_OPEN",
                "A manual backup is already waiting or running",
                request_id=open_request.pk,
                status=open_request.status,
            )
        return BackupRequest.objects.create(requested_by=actor, note=note.strip()[:200])


# --- updates --------------------------------------------------------------------------------


#: ``infra/update.sh`` outcomes to ``UpdateRun.result``.
SCRIPT_RESULTS: dict[str, str] = {
    "ok": UpdateResult.SUCCEEDED,
    "succeeded": UpdateResult.SUCCEEDED,
    "failed": UpdateResult.FAILED,
    "rolled_back": UpdateResult.ROLLED_BACK,
    "running": UpdateResult.RUNNING,
}
_TAG_MAX = 50
#: Text columns are trimmed to keep a runaway log from bloating the table.
_TEXT_MAX = 64 * 1024


def _clip(text: str, limit: int = _TEXT_MAX) -> str:
    text = text.replace("\x00", "")
    return text if len(text) <= limit else "...\n" + text[-(limit - 4) :]


@dataclass(frozen=True, slots=True)
class UpdateRecord:
    """One run of ``infra/update.sh`` as the script reports it (``manage.py record_update``)."""

    run_key: str
    version: str
    previous_version: str
    result: str
    started_at: datetime
    finished_at: datetime | None
    migration_plan: str = ""
    migrations_applied: bool = False
    db_restored: bool = False
    backup_file: str = ""
    detail: str = ""
    log: str = ""
    release_notes: str = ""


def record_update_run(record: UpdateRecord) -> UpdateRun:
    """Insert or complete the ``UpdateRun`` of one update script run (FEATURES 13.10).

    Keyed by ``run_key``, so the script may call it again for the same run (a retry, or an
    interrupted run recorded by the next one) without creating a second row. Release notes
    already recorded are kept when the new call brings none.

    Raises:
        ValueError: an unknown result, a missing run key or version, a finish before the
            start, or a finished result without a finish time (the script's input, never a
            user's: it is not an API error code).
    """
    result = SCRIPT_RESULTS.get(record.result)
    problems: list[str] = []
    if result is None:
        problems.append("result")
    if not record.run_key.strip() or len(record.run_key) > 100:
        problems.append("run_key")
    if not record.version.strip() or len(record.version) > _TAG_MAX:
        problems.append("version")
    if len(record.previous_version) > _TAG_MAX:
        problems.append("previous_version")
    if record.finished_at is not None and record.finished_at < record.started_at:
        problems.append("finished_at")
    if result != UpdateResult.RUNNING and record.finished_at is None:
        problems.append("finished_at")
    if problems:
        raise ValueError(f"invalid update record: {', '.join(sorted(set(problems)))}")
    values: dict[str, Any] = {
        "version": record.version.strip(),
        "previous_version": record.previous_version.strip(),
        "result": result,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "migration_plan": _clip(record.migration_plan),
        "migrations_applied": record.migrations_applied,
        "db_restored": record.db_restored,
        "backup_file": record.backup_file.strip()[:500],
        "detail": _clip(record.detail, 4000),
        "log": _clip(record.log),
    }
    if record.release_notes.strip():
        values["release_notes"] = _clip(record.release_notes)
    with (
        transaction.atomic(),
        pghistory.context(reason=f"infra/update.sh {record.result}", run=record.run_key),
    ):
        run, _ = UpdateRun.objects.select_for_update().update_or_create(
            run_key=record.run_key.strip(), defaults=values
        )
    logger.info("update_run_recorded", run_key=run.run_key, version=run.version, result=run.result)
    return run


def update_runs() -> QuerySet[UpdateRun]:
    """Recorded updates with their release notes, newest first (FEATURES 13.10; read-only)."""
    return UpdateRun.objects.select_related("started_by").order_by("-started_at", "-id")


def update_log(limit: int = 20) -> list[dict[str, Any]]:
    """The update script's own log (``update-runs.jsonl`` in ``BACKUP_STATUS_DIR``), newest
    first: every update ``infra/update.sh`` ran, with its outcome (ok, failed, rolled_back)."""
    folder = status_dir()
    if folder is None:
        return []
    rows: list[dict[str, Any]] = []
    for line in _tail_lines(folder / "update-runs.jsonl"):
        if line.get("type") != "update":
            continue
        rows.append(
            {
                "status": str(line.get("status") or "failed")[:20],
                "from_tag": str(line.get("from_tag") or "")[:64],
                "to_tag": str(line.get("to_tag") or "")[:64],
                "started_at": _when(line.get("started_at")),
                "finished_at": _when(line.get("finished_at")),
                "migrations_applied": bool(line.get("migrations_applied")),
                "db_restored": bool(line.get("db_restored")),
                "detail": str(line.get("detail") or "")[:500],
            }
        )
    return list(reversed(rows))[:limit]
