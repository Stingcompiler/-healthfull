"""``manage.py record_update``: infra/update.sh records each run in ``UpdateRun`` (FEATURES
13.10) through the ops services."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.ops import services as ops
from apps.ops.management.commands.record_update import parse_sections
from apps.ops.models import UpdateRun
from conftest import ApiClient

pytestmark = pytest.mark.django_db

START = "2026-10-10T12:00:00Z"
END = "2026-10-10T12:04:30Z"


def record(*extra: str, stdin: str | None = None, monkeypatch: Any = None) -> str:
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    out = io.StringIO()
    call_command(
        "record_update",
        "--run-key",
        "20261010T120000Z-v2.0.0",
        "--to",
        "v2.0.0",
        "--from",
        "v1.0.0",
        "--started-at",
        START,
        *extra,
        stdout=out,
    )
    return out.getvalue()


def test_success_is_recorded_with_plan_notes_and_log(monkeypatch: Any) -> None:
    text = (
        "ignored preamble\n"
        "@@plan\nPlanned operations:\nops.0004_update_run_script_record\n"
        "@@notes\nLab fixes\n- faster work list\n"
        "@@log\n2026-10-10T12:00:00Z [update] ==> 1/7 get images\n"
    )
    out = record(
        "--result",
        "ok",
        "--finished-at",
        END,
        "--migrations-applied",
        "--backup",
        "/backups/dumps/hospital-20261010T120000Z-pre-update-v2.0.0.dump",
        "--stdin",
        stdin=text,
        monkeypatch=monkeypatch,
    )
    run = UpdateRun.objects.get()
    assert f"update run {run.pk} v2.0.0 succeeded" in out
    assert run.run_key == "20261010T120000Z-v2.0.0"
    assert (run.version, run.previous_version, run.result) == ("v2.0.0", "v1.0.0", "succeeded")
    assert run.started_at == datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    assert run.finished_at == datetime(2026, 10, 10, 12, 4, 30, tzinfo=UTC)
    assert run.migration_plan == "Planned operations:\nops.0004_update_run_script_record"
    assert run.release_notes == "Lab fixes\n- faster work list"
    assert run.log.startswith("2026-10-10T12:00:00Z [update]")
    assert run.migrations_applied is True
    assert run.db_restored is False
    assert run.backup_file.endswith("pre-update-v2.0.0.dump")


def test_rollback_records_the_reason_and_the_restore() -> None:
    record(
        "--result",
        "rolled_back",
        "--finished-at",
        END,
        "--migrations-applied",
        "--db-restored",
        "--detail",
        "v2.0.0 did not become healthy (during 6/7 health check)",
    )
    run = UpdateRun.objects.get()
    assert run.result == "rolled_back"
    assert run.db_restored is True
    assert "6/7 health check" in run.detail


def test_the_same_run_key_updates_one_row_and_keeps_its_release_notes(monkeypatch: Any) -> None:
    record("--result", "running", "--stdin", stdin="@@notes\nRelease 2\n", monkeypatch=monkeypatch)
    record("--result", "failed", "--finished-at", END, "--detail", "interrupted during 4/7")
    run = UpdateRun.objects.get()
    assert run.result == "failed"
    assert run.release_notes == "Release 2"
    assert run.detail == "interrupted during 4/7"
    # The audit trail keeps both writes (pghistory, with the script as the reason).
    assert run.events.count() == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "extra",
    [
        ("--result", "ok"),  # finished result without a finish time
        ("--result", "ok", "--finished-at", "2026-10-10T11:00:00Z"),  # before the start
        ("--result", "ok", "--finished-at", "yesterday"),
    ],
)
def test_invalid_records_are_refused(extra: tuple[str, ...]) -> None:
    with pytest.raises(CommandError):
        record(*extra)
    assert not UpdateRun.objects.exists()


def test_unknown_result_is_refused_by_the_parser() -> None:
    with pytest.raises(CommandError):
        record("--result", "maybe", "--finished-at", END)


def test_service_rejects_an_overlong_tag() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    with pytest.raises(ValueError, match="version"):
        ops.record_update_run(
            ops.UpdateRecord(
                run_key="k",
                version="v" * 51,
                previous_version="",
                result="ok",
                started_at=now,
                finished_at=now + timedelta(minutes=1),
            )
        )


def test_long_texts_are_clipped_from_the_start() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    run = ops.record_update_run(
        ops.UpdateRecord(
            run_key="k",
            version="v2",
            previous_version="v1",
            result="ok",
            started_at=now,
            finished_at=now,
            log="x" * 100_000 + "END",
        )
    )
    assert len(run.log) <= 64 * 1024
    assert run.log.endswith("END")


def test_parse_sections_ignores_unknown_lines_and_keeps_order() -> None:
    parsed = parse_sections("junk\n@@log\na\n@@plan\np1\np2\n@@log\nb\n")
    assert parsed == {"plan": "p1\np2", "notes": "", "log": "a\nb"}


def test_an_older_image_can_still_insert_rows() -> None:
    """A rollback starts the previous image, whose code does not know the new columns: the
    database defaults let its INSERT through."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ops_updaterun (version, previous_version, release_notes, result,"
            " started_at, finished_at, log) VALUES ('v1', '', '', 'succeeded', now(), now(), '')"
        )
    run = UpdateRun.objects.get()
    assert (run.migration_plan, run.migrations_applied, run.db_restored, run.detail) == (
        "",
        False,
        False,
        "",
    )
    assert run.run_key is None


def test_recorded_runs_show_in_the_update_history(make_user: Any, api_client: ApiClient) -> None:
    make_user("opsadmin", roles=["admin"])
    record("--result", "rolled_back", "--finished-at", END, "--detail", "health")
    assert api_client.login("opsadmin").status_code == 200
    body = api_client.get("/api/ops/updates").json()
    assert [(r["version"], r["result"]) for r in body["items"]] == [("v2.0.0", "rolled_back")]
