"""The daily integrity check of the maintenance loop (ADR 0021): recorded once a day, an
alert with a link the readers may open when anything fails, the newest run on the status
page."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.core.models import Notification
from apps.ops import integrity_runs
from apps.ops.models import IntegrityRun
from apps.ops.tests.test_integrity_check import entry
from conftest import ApiClient

pytestmark = pytest.mark.django_db


def daily() -> str:
    out = StringIO()
    call_command("integrity_check", "--daily", stdout=out)
    return out.getvalue()


def test_the_daily_run_is_recorded_once_a_day_and_quiet_when_all_match(make_user: Any) -> None:
    make_user("ops-mgr", roles=["manager"])
    assert "integrity_check: recorded" in daily()
    run = IntegrityRun.objects.get()
    assert run.ok is True
    assert run.source == "scheduled"
    assert {r["name"] for r in run.results} >= {"ledger_balanced", "stock", "allocations"}
    assert "already ran today" in daily()
    assert IntegrityRun.objects.count() == 1
    assert not Notification.objects.filter(kind="integrity_failed").exists()


def test_findings_alert_admins_and_managers_once_and_exit_cleanly(make_user: Any) -> None:
    admin = make_user("ops-admin", roles=["admin"])
    manager = make_user("ops-mgr2", roles=["manager"])
    make_user("ops-cash", roles=["cashier"])
    entry("payment", 999_999, [{"account": "CASH_SAFE", "debit": "10.00"}])
    out = daily()  # no CommandError: the loop must not read a finding as a failed job
    assert "FINDINGS" in out
    run = IntegrityRun.objects.get()
    assert run.ok is False
    failed = [r for r in run.results if not r["ok"]]
    assert [r["name"] for r in failed] == ["ledger_balanced"]
    assert failed[0]["problems"] >= 1
    notes = Notification.objects.filter(kind="integrity_failed")
    assert set(notes.values_list("user", flat=True)) == {admin.pk, manager.pk}
    assert notes.first() is not None
    assert notes.first().payload["failed"] == ["ledger_balanced"]  # type: ignore[union-attr]
    # A second recorded run the same day (by hand) does not alert the same people again.
    integrity_runs.run_and_record(source="manual")
    assert notes.count() == 2


def test_the_status_page_shows_the_newest_run(make_user: Any, api_client: ApiClient) -> None:
    make_user("ops-admin2", roles=["admin"])
    assert api_client.login("ops-admin2").status_code == 200
    assert api_client.get("/api/ops/status").json()["last_integrity_check"] is None
    entry("payment", 999_998, [{"account": "CASH_SAFE", "debit": "5.00"}])
    daily()
    body = api_client.get("/api/ops/status").json()
    last = body["last_integrity_check"]
    assert last["ok"] is False
    assert last["source"] == "scheduled"
    assert any(c["name"] == "ledger_balanced" and not c["ok"] for c in last["results"])
    assert "INTEGRITY_FAILED" in body["warnings"]


def test_record_by_hand_is_marked_manual() -> None:
    out = StringIO()
    call_command("integrity_check", "--record", stdout=out)
    assert IntegrityRun.objects.get().source == "manual"
