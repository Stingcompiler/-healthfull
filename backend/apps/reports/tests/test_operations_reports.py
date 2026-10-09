"""Visits (12.8), lab turnaround and volume (12.9), stock (12.6) and the dashboard (12.10)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.core.tests import builders as b
from apps.lab.models import LabTest, ResultSet, Sample
from apps.payments.tests import fin
from apps.pharmacy import services as ps
from apps.reports import queries
from apps.reports.kit import Report, resolve_filters
from apps.reports.tests.scenario import Day
from apps.visits.models import Visit

D = Decimal
pytestmark = pytest.mark.django_db


def _period(**extra: Any) -> Any:
    today = timezone.localdate()
    return resolve_filters(date_from=today, date_to=today, **extra)


def _en(value: Any) -> Any:
    return value["en"] if isinstance(value, dict) else value


def _by(report: Report, section: str, column: str) -> dict[Any, dict[str, Any]]:
    return {_en(r[column]): r for r in report.section(section).rows}


# --- visits --------------------------------------------------------------------------------


def test_visits_by_department_doctor_and_day(day: Day) -> None:
    Visit.objects.filter(pk=day.visit_c.pk).update(visit_type="follow_up")
    r = queries.visits(_period())
    assert r.metric("visits") == 3
    assert r.metric("new") == 2
    assert r.metric("follow_up") == 1
    assert r.metric("patients") == 3
    depts = _by(r, "by_department", "department")
    assert (depts[day.opd.name_en]["total"], depts[day.opd.name_en]["follow_up"]) == (2, 1)
    assert depts[day.lab.name_en]["new"] == 1
    doctors = _by(r, "by_doctor", "doctor")
    assert doctors[day.doctor.user.display_name_en]["total"] == 1
    assert doctors["No doctor"]["total"] == 2
    (row,) = r.section("by_day").rows
    assert (row["date"], row["total"]) == (timezone.localdate(), 3)


def test_visits_filters(day: Day) -> None:
    assert queries.visits(_period(department_id=day.lab.pk)).metric("visits") == 1
    assert queries.visits(_period(user_id=day.doctor.user_id)).metric("visits") == 1
    Visit.objects.filter(pk=day.visit_b.pk).update(
        status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=day.receptionist,
        cancel_reason=b.reason("visit_cancel"),
    )
    r = queries.visits(_period())
    assert r.metric("visits") == 2
    assert r.section("by_day").rows[0]["cancelled"] == 1


# --- lab -----------------------------------------------------------------------------------


def test_lab_turnaround_and_volume(day: Day) -> None:
    test = LabTest.objects.create(
        service=day.cbc, code="RCBC", sample_type="whole_blood", turnaround_minutes=60
    )
    now = timezone.now()
    sample = Sample.objects.create(
        accession_no="ACC-R-1",
        visit=day.visit_a,
        sample_type="whole_blood",
        status="received",
        collected_at=now - timedelta(minutes=50),
        collected_by=day.lab_tech,
        received_at=now - timedelta(minutes=45),
        received_by=day.lab_tech,
    )
    ResultSet.objects.create(
        service_line=day.lab_a, test=test, sample=sample, first_approved_at=now
    )
    r = queries.lab_turnaround(_period())
    row = _by(r, "tests", "test")["RCBC"]
    assert (row["ordered"], row["performed"], row["cancelled"]) == (2, 1, 0)
    assert row["completed"] == 1
    assert row["median"] == 45
    assert row["within_target"] == D("100.0")
    assert r.metric("completed") == 1
    assert r.metric("median") == 45


# --- stock ---------------------------------------------------------------------------------


@pytest.fixture
def stock(db: None) -> dict[str, Any]:
    fin.seed()
    store = b.store()
    para = b.item(generic_name="Paracetamol", strength="500 mg")
    near = b.batch(para, expiry=timezone.localdate() + timedelta(days=20))  # cost 2.50
    far = b.batch(para, expiry=date(2030, 1, 1))
    expired = b.batch(para, expiry=timezone.localdate() - timedelta(days=3))
    b.stock_move(near, store, "100")
    b.stock_move(far, store, "40")
    b.stock_move(expired, store, "10")
    b.stock_move(near, store, "-30", kind="dispense")
    return {"store": store, "item": para, "near": near, "far": far, "expired": expired}


def test_stock_valuation(stock: dict[str, Any]) -> None:
    r = queries.stock_valuation(_period())
    (row,) = r.section("items").rows
    assert row["item"] == "Paracetamol 500 mg"
    assert row["on_hand"] == 120  # 70 + 40 + 10
    assert row["batches"] == 3
    assert row["value"] == D("300.00")  # 120 x 2.50
    assert row["nearest_expiry"] == stock["expired"].expiry_date
    assert r.metric("stock_value") == D("300.00")
    assert r.metric("expired_value") == D("25.00")


def test_stock_movement(stock: dict[str, Any]) -> None:
    r = queries.stock_movement(_period())
    (row,) = r.section("items").rows
    assert (row["opening"], row["receipts"], row["dispensed"], row["closing"]) == (0, 150, 30, 120)
    assert row["received_value"] == D("375.00")
    assert row["dispensed_value"] == D("75.00")
    tomorrow = timezone.localdate() + timedelta(days=1)
    later = queries.stock_movement(resolve_filters(date_from=tomorrow, date_to=tomorrow))
    (row,) = later.section("items").rows
    assert (row["opening"], row["receipts"], row["closing"]) == (120, 0, 120)


def test_stock_variance_from_a_posted_count(stock: dict[str, Any]) -> None:
    manager = fin.staff("manager", "pharmacist")
    count = ps.start_count(stock["store"], actor=manager, items=[stock["item"]])
    ps.record_count(count, batch=stock["near"], counted_qty=68, actor=manager)
    ps.record_count(count, batch=stock["far"], counted_qty=41, actor=manager)
    ps.record_count(count, batch=stock["expired"], counted_qty=10, actor=manager)
    ps.post_count(count, actor=manager)
    r = queries.stock_variance(_period())
    rows = {row["batch"]: row for row in r.section("lines").rows}
    assert set(rows) == {stock["near"].batch_no, stock["far"].batch_no}
    assert (rows[stock["near"].batch_no]["difference"], rows[stock["near"].batch_no]["value"]) == (
        -2,
        D("-5.00"),
    )
    assert rows[stock["far"].batch_no]["difference"] == 1
    assert r.metric("shortage_value") == D("-5.00")
    assert r.metric("surplus_value") == D("2.50")
    assert r.metric("net_value") == D("-2.50")


def test_stock_expiry(stock: dict[str, Any]) -> None:
    r = queries.stock_expiry(resolve_filters(date_from=None, date_to=None, days=30))
    batches = {row["batch"]: row for row in r.section("batches").rows}
    assert set(batches) == {stock["near"].batch_no, stock["expired"].batch_no}
    assert batches[stock["expired"].batch_no]["days_left"] == -3
    assert r.metric("expired_value") == D("25.00")
    assert r.metric("expiring_value") == D("200.00")  # 70 + 10 units at 2.50


# --- dashboard -----------------------------------------------------------------------------


def test_dashboard_today(day: Day) -> None:
    d = queries.dashboard()
    metrics = {m.key: m.value for m in d.metrics}
    assert metrics["collected_today"] == D("13500.00")
    assert metrics["cash_today"] == D("10500.00")
    assert metrics["pending_transfers"] == D("6000.00")
    assert metrics["pending_count"] == 1
    assert metrics["net_revenue_today"] == D("21500.00")
    assert metrics["visits_today"] == 3
    assert isinstance(metrics["queue_waiting"], int)
    assert metrics["queue_waiting"] >= 1  # patient A's consultation queue entry
    assert len(d.trend) == queries.TREND_DAYS
    assert d.trend[-1] == {
        "date": timezone.localdate(),
        "collected": D("13500.00"),
        "pending": D("6000.00"),
        "visits": 3,
    }
    assert {_en(r["department"]): r["net"] for r in d.departments} == {
        day.lab.name_en: D("20000.00"),
        day.opd.name_en: D("1500.00"),
    }
    alerts = {a.key: a for a in d.alerts}
    assert alerts["unreviewed_variances"].count == 1
    assert alerts["performed_by_authorization"].count == 1


def test_dashboard_tomorrow_flags_yesterdays_leaks(day: Day) -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)
    d = queries.dashboard(today=tomorrow)
    metrics = {m.key: m.value for m in d.metrics}
    assert metrics["collected_today"] == D("0.00")
    assert metrics["pending_transfers"] == D("6000.00")  # still pending, still not collected
    alerts = {a.key: a for a in d.alerts}
    assert alerts["paid_not_performed"].count == 2
    assert alerts["requested_not_invoiced"].count == 1
