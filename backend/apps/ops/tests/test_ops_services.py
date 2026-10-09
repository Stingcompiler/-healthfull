"""System status, manual backup requests, update history, full data export and the daily
alert scan (FEATURES 0.8, 0.13, 13.8, 13.9, 13.10, 14.1)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.errors import PermissionRequired
from apps.core.models import Notification
from apps.core.tests import builders as b
from apps.ops import export, notify
from apps.ops import services as ops
from apps.ops.models import BackupRequest, DataExport, UpdateRun
from apps.patients import services as patient_services
from apps.pharmacy.models import Item
from conftest import ApiClient
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


def iso(delta: timedelta) -> str:
    return (timezone.now() - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_lines(folder: Path, name: str, lines: list[Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


@pytest.fixture
def status_dir(settings: Any, tmp_path: Path) -> Path:
    folder = tmp_path / "status"
    settings.BACKUP_STATUS_DIR = str(folder)
    settings.MEDIA_ROOT = str(tmp_path)
    return folder


@pytest.fixture
def admin(make_user):
    return make_user("opsadmin", roles=["admin"])


# --- status ---------------------------------------------------------------------------------


def test_status_reads_the_backup_logs_and_flags_a_failed_last_run(status_dir: Path) -> None:
    write_lines(
        status_dir,
        "backup-runs.jsonl",
        [
            {
                "type": "backup",
                "status": "ok",
                "started_at": iso(timedelta(hours=5, minutes=3)),
                "finished_at": iso(timedelta(hours=5)),
                "label": None,
                "dump": {
                    "file": "/backups/dumps/hospital-1.dump",
                    "size_bytes": 2048,
                    "sha256": "x",
                },
                "error": None,
            },
            "not json at all",
            {
                "type": "backup",
                "status": "failed",
                "started_at": iso(timedelta(hours=1)),
                "finished_at": iso(timedelta(minutes=59)),
                "dump": None,
                "error": "cannot connect",
            },
        ],
    )
    write_lines(
        status_dir,
        "restore-tests.jsonl",
        [
            {
                "type": "restore_test",
                "status": "ok",
                "started_at": iso(timedelta(days=2)),
                "finished_at": iso(timedelta(days=2)),
                "dump": "/backups/dumps/hospital-1.dump",
                "dump_size_bytes": 2048,
                "error": None,
            }
        ],
    )
    status = ops.system_status()
    assert status["version"]
    assert status["database"]["ok"] is True
    assert status["database"]["size_bytes"] > 0
    assert status["migrations"]["pending"] == 0
    assert {d["label"] for d in status["disks"]} == {"media", "backups"}
    last = status["last_backup"]
    assert (last["status"], last["file"], last["size_bytes"]) == ("ok", "hospital-1.dump", 2048)
    assert [r["status"] for r in status["backups"]] == ["failed", "ok"]
    assert status["backups"][0]["error"] == "cannot connect"
    assert status["last_restore_test"]["status"] == "ok"
    assert "BACKUP_FAILED" in status["warnings"]
    assert "BACKUP_STALE" not in status["warnings"]
    assert "RESTORE_TEST_STALE" not in status["warnings"]


def test_status_without_logs_warns(settings: Any) -> None:
    settings.BACKUP_STATUS_DIR = ""
    status = ops.system_status()
    assert status["status_dir_configured"] is False
    assert status["last_backup"] is None
    assert {"BACKUP_STATUS_UNAVAILABLE", "BACKUP_STALE", "RESTORE_TEST_STALE"} <= set(
        status["warnings"]
    )


def test_an_old_backup_is_stale(status_dir: Path) -> None:
    write_lines(
        status_dir,
        "backup-runs.jsonl",
        [
            {
                "type": "backup",
                "status": "partial",
                "started_at": iso(timedelta(hours=50)),
                "finished_at": iso(timedelta(hours=49)),
                "dump": None,
                "error": "media",
            }
        ],
    )
    status = ops.system_status()
    assert status["last_backup"]["status"] == "partial"
    assert "BACKUP_STALE" in status["warnings"]


# --- manual backup --------------------------------------------------------------------------


def test_one_manual_backup_request_at_a_time(admin, make_user) -> None:
    first = ops.request_backup(actor=admin, note="before the audit")
    assert (first.status, first.note, first.requested_by) == ("pending", "before the audit", admin)
    with pytest.raises(DomainError) as open_one:
        ops.request_backup(actor=admin)
    assert open_one.value.code == "BACKUP_REQUEST_OPEN"
    # The backup service claims it, then records the outcome.
    BackupRequest.objects.filter(pk=first.pk).update(status="running", started_at=timezone.now())
    with pytest.raises(DomainError):
        ops.request_backup(actor=admin)
    BackupRequest.objects.filter(pk=first.pk).update(
        status="succeeded", finished_at=timezone.now(), dump_file="/backups/dumps/x.dump"
    )
    assert ops.request_backup(actor=admin).status == "pending"
    manager = make_user("mgr", roles=["manager"])
    with pytest.raises(PermissionRequired):
        ops.request_backup(actor=manager)


# --- export ---------------------------------------------------------------------------------


def test_csv_cells_never_run_as_formulas() -> None:
    assert export.csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert export.csv_cell("+249912") == "'+249912"
    assert export.csv_cell("@SUM") == "'@SUM"
    assert export.csv_cell("-1+1") == "'-1+1"
    assert export.csv_cell(Decimal("-5.00")) == "-5.00"
    assert export.csv_cell(-3) == "-3"
    assert export.csv_cell(None) == ""
    assert export.csv_cell({"a": "ب"}) == '{"a": "ب"}'


def test_export_streams_a_zip_of_csvs_and_is_audited(admin, make_user) -> None:
    clerk = make_user("desk", roles=["receptionist"])
    patient = patient_services.register_patient(
        patient_services.PatientData(sex="female", full_name_ar="=CMD()", phone="0912000999"),
        actor=clerk,
    )
    record = export.begin_export(actor=admin)
    data = b"".join(export.stream_export(record, chunk_rows=1))
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(archive.namelist()) == sorted(
        ["README.txt", *(f"{t}.csv" for t in export.EXPORT_TABLES)]
    )
    text = archive.read("patients.csv").decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    assert "file_no" in header
    assert "full_name_ar" in header
    mine = next(r for r in body if r[header.index("id")] == str(patient.pk))
    assert mine[header.index("full_name_ar")] == "'=CMD()"
    record.refresh_from_db()
    assert record.finished_at is not None
    assert record.row_counts["patients"] >= 1
    assert record.size_bytes == len(data)
    assert record.tables == list(export.EXPORT_TABLES)
    with pytest.raises(PermissionRequired):
        export.begin_export(actor=clerk)


def test_export_api_downloads_and_is_post_only(admin, api_client: ApiClient) -> None:
    assert api_client.login("opsadmin").status_code == 200
    assert api_client.get("/api/ops/export").status_code == 405
    response = api_client.post("/api/ops/export")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"].startswith('attachment; filename="hospital-export-')
    data = b"".join(response.streaming_content)
    assert "patients.csv" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert DataExport.objects.filter(requested_by=admin, finished_at__isnull=False).exists()


# --- updates --------------------------------------------------------------------------------


def test_update_history_newest_first(admin, api_client: ApiClient) -> None:
    now = timezone.now()
    UpdateRun.objects.create(
        version="1.0.0",
        result="succeeded",
        started_at=now - timedelta(days=9),
        finished_at=now - timedelta(days=9),
        release_notes="First",
    )
    UpdateRun.objects.create(
        version="1.1.0",
        previous_version="1.0.0",
        result="rolled_back",
        started_at=now - timedelta(days=1),
        finished_at=now,
        release_notes="Lab fixes",
    )
    assert api_client.login("opsadmin").status_code == 200
    body = api_client.get("/api/ops/updates").json()
    assert body["current_version"]
    assert [r["version"] for r in body["items"]] == ["1.1.0", "1.0.0"]
    assert body["items"][0]["result"] == "rolled_back"
    assert body["items"][0]["release_notes"] == "Lab fixes"


# --- the daily alert scan -------------------------------------------------------------------


def test_scan_alerts_reviewers_pharmacists_and_admins_once_a_day(make_user, settings) -> None:
    settings.BACKUP_STATUS_DIR = ""
    manager = make_user("mgr2", roles=["manager"])
    pharmacist = make_user("pharm", roles=["pharmacist"])
    admin = make_user("adm2", roles=["admin"])
    shift = b.close_shift(b.shift())
    item = b.item(generic_name="Ceftriaxone")
    Item.objects.filter(pk=item.pk).update(min_stock=Decimal(20))

    today = timezone.localdate()
    first = notify.scan(today=today)
    assert first["shift_review_pending"] >= 1
    assert first["stock_low_summary"] >= 1
    assert first["backup_stale"] >= 1
    review = Notification.objects.get(user=manager, kind="shift_review_pending")
    assert review.payload["shifts"][0]["number"] == shift.number
    assert review.key == f"shift_review_pending:{today.isoformat()}"
    low = Notification.objects.get(user=pharmacist, kind="stock_low_summary")
    assert {"item_id": item.pk, "name": "Ceftriaxone", "on_hand": 0, "min_stock": 20} in (
        low.payload["items"]
    )
    assert Notification.objects.filter(user=admin, kind="backup_stale").exists()

    again = notify.scan(today=today)
    assert again["shift_review_pending"] == 0
    assert again["stock_low_summary"] == 0
    assert Notification.objects.filter(user=manager, kind="shift_review_pending").count() == 1
    tomorrow = notify.scan(today=today + timedelta(days=1))
    assert tomorrow["shift_review_pending"] >= 1


def test_notify_scan_command_reports(settings) -> None:
    settings.BACKUP_STATUS_DIR = ""
    out = io.StringIO()
    call_command("notify_scan", stdout=out)
    assert out.getvalue().startswith("notify_scan: transfers_pending_overdue")
