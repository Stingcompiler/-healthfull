"""Daily revenue (FEATURES 12.1): by department, doctor and payment method; pending apart."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.reports import queries
from apps.reports.kit import Report, resolve_filters
from apps.reports.tests.scenario import Day

D = Decimal
pytestmark = pytest.mark.django_db


def _today(department_id: int | None = None) -> Report:
    today = timezone.localdate()
    return queries.revenue(
        resolve_filters(date_from=today, date_to=today, department_id=department_id)
    )


def _rows_by(report: Report, section: str, column: str, lang: str = "en") -> dict[str, dict]:
    out = {}
    for row in report.section(section).rows:
        value = row[column]
        key = value[lang] if isinstance(value, dict) else str(value)
        out[key] = row
    return out


def test_totals_of_the_day(day: Day) -> None:
    r = _today()
    assert r.metric("gross") == D("27000.00")
    assert r.metric("discount") == D("500.00")
    assert r.metric("credited") == D("5000.00")
    assert r.metric("net_revenue") == D("21500.00")
    assert r.metric("payer_share") == D("7000.00")
    assert r.metric("patient_share") == D("14500.00")
    # Pending transfers are never collected (FEATURES 6.4); spent credit is not new money.
    assert r.metric("collected") == D("13500.00")
    assert r.metric("cash") == D("10500.00")
    assert r.metric("bank_confirmed") == D("3000.00")
    assert r.metric("pending_transfers") == D("6000.00")
    assert r.metric("rejected_transfers") == D("0.00")


def test_by_department_and_doctor_add_up_to_net(day: Day) -> None:
    r = _today()
    depts = _rows_by(r, "by_department", "department")
    assert depts[day.opd.name_en]["net"] == D("1500.00")
    assert depts[day.opd.name_en]["discount"] == D("500.00")
    assert depts[day.opd.name_en]["credited"] == D("5000.00")
    assert depts[day.lab.name_en]["net"] == D("20000.00")
    assert depts[day.lab.name_en]["payer_share"] == D("7000.00")
    assert r.section("by_department").totals == {
        "gross": D("27000.00"),
        "discount": D("500.00"),
        "credited": D("5000.00"),
        "net": D("21500.00"),
        "payer_share": D("7000.00"),
        "patient_share": D("14500.00"),
    }
    doctors = _rows_by(r, "by_doctor", "doctor")
    doctor_name = day.doctor.user.display_name_en
    assert doctors[doctor_name]["net"] == D("11500.00")
    # Patient B's visit had no doctor.
    assert doctors["No doctor"]["net"] == D("10000.00")
    doctor_totals = r.section("by_doctor").totals
    assert doctor_totals is not None
    assert doctor_totals["net"] == D("21500.00")


def test_by_method_keeps_pending_apart(day: Day) -> None:
    r = _today()
    methods = _rows_by(r, "by_method", "method")
    assert methods["Cash"]["confirmed"] == D("10500.00")
    assert methods["Cash"]["count"] == 2
    assert methods["Bank transfer"]["confirmed"] == D("3000.00")
    assert methods["Bank transfer"]["pending"] == D("6000.00")
    assert methods["Bank transfer"]["count"] == 2
    assert r.section("by_method").totals == {
        "count": 4,
        "confirmed": D("13500.00"),
        "pending": D("6000.00"),
        "rejected": D("0.00"),
    }


def test_by_day_row(day: Day) -> None:
    r = _today()
    (row,) = r.section("by_day").rows
    assert row["date"] == timezone.localdate()
    assert row["net"] == D("21500.00")
    assert row["collected"] == D("13500.00")
    assert row["pending"] == D("6000.00")


def test_department_filter_narrows_revenue_and_drops_collections(day: Day) -> None:
    r = _today(department_id=day.lab.pk)
    assert r.metric("net_revenue") == D("20000.00")
    assert [s.key for s in r.sections] == ["by_day", "by_department", "by_doctor"]
    assert "collected" not in {m.key for m in r.metrics}


def test_other_days_are_out(day: Day) -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)
    r = queries.revenue(resolve_filters(date_from=tomorrow, date_to=tomorrow))
    assert r.metric("gross") == D("0.00")
    assert r.metric("collected") == D("0.00")
    assert r.section("by_department").rows == []
