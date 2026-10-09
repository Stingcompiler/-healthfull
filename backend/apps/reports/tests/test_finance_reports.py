"""Shift variances (12.3), pending transfers (12.4), adjustments (12.5), payer receivables
(12.7) and the exception reports (4.5, 12.2) over the shared day."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.orders.models import ServiceLine
from apps.reports import queries
from apps.reports.kit import Report, resolve_filters
from apps.reports.tests.scenario import Day

D = Decimal
pytestmark = pytest.mark.django_db


def _period(**extra: Any) -> Any:
    today = timezone.localdate()
    return resolve_filters(date_from=today, date_to=today, **extra)


def _en(value: Any) -> Any:
    return value["en"] if isinstance(value, dict) else value


def _rows(report: Report, section: str, *columns: str) -> list[tuple[Any, ...]]:
    return [tuple(_en(r[c]) for c in columns) for r in report.section(section).rows]


# --- shift variances -----------------------------------------------------------------------


def test_shift_variances(day: Day) -> None:
    r = queries.shift_variances(_period())
    (row,) = r.section("shifts").rows
    assert row["shift"] == day.shift.number
    assert (row["expected"], row["counted"], row["variance"]) == (
        D("6500.00"),
        D("6400.00"),
        D("-100.00"),
    )
    assert _en(row["review"]) == "Not reviewed"
    assert _en(row["reason"]) != "No reason"
    assert _rows(r, "by_cashier", "cashier", "shifts", "short", "over", "net") == [
        (day.cashier.display_name_en, 1, D("-100.00"), D("0.00"), D("-100.00"))
    ]
    assert r.metric("net_variance") == D("-100.00")
    assert r.metric("unreviewed") == 1
    assert {o.id for o in r.users} == {day.cashier.pk}


def test_shift_variances_filter_by_cashier(day: Day) -> None:
    r = queries.shift_variances(_period(user_id=day.supervisor.pk))
    assert r.section("shifts").rows == []
    assert r.metric("shifts") == 0


# --- pending transfers ---------------------------------------------------------------------


def test_pending_transfers_by_age(day: Day) -> None:
    r = queries.pending_transfers(_period())
    assert _rows(r, "transfers", "payment", "amount", "age") == [
        (day.transfer_a.number, D("6000.00"), 0)
    ]
    assert r.section("transfers").rows[0]["file_no"] == day.patient_a.file_no
    by_age = {
        _en(row["age_bucket"]): (row["count"], row["amount"]) for row in r.section("by_age").rows
    }
    assert by_age["0-1 days"] == (1, D("6000.00"))
    assert r.metric("pending_total") == D("6000.00")
    assert r.metric("pending_count") == 1


def test_pending_transfers_age_counts_days(day: Day) -> None:
    later = timezone.localdate() + timedelta(days=5)
    r = queries.pending_transfers(_period(), today=later)
    assert r.section("transfers").rows[0]["age"] == 5
    by_age = {_en(row["age_bucket"]): row["count"] for row in r.section("by_age").rows}
    assert by_age["4-7 days"] == 1
    assert r.metric("oldest_age") == 5


def test_pending_transfers_by_taker(day: Day) -> None:
    assert (
        queries.pending_transfers(_period(user_id=day.supervisor.pk)).metric("pending_count") == 0
    )
    assert queries.pending_transfers(_period(user_id=day.cashier.pk)).metric("pending_count") == 1


# --- discounts, cancellations, refunds -----------------------------------------------------


def test_adjustments_by_user_and_reason(day: Day) -> None:
    r = queries.adjustments(_period())
    assert _rows(r, "discounts", "user", "reason", "count", "amount") == [
        (day.supervisor.display_name_en, "Financial hardship", 1, D("500.00"))
    ]
    assert _rows(r, "credit_notes", "user", "count", "gross", "patient_share", "payer_share") == [
        (day.supervisor.display_name_en, 1, D("5000.00"), D("5000.00"), D("0.00"))
    ]
    assert _rows(r, "line_cancellations", "user", "reason", "count") == [
        (day.cashier.display_name_en, "Patient refused", 1)
    ]
    assert _rows(r, "refunds", "user", "count", "amount") == [
        (day.accountant.display_name_en, 1, D("5000.00"))
    ]
    kinds = sorted(_en(row["kind"]) for row in r.section("detail").rows)
    assert kinds == ["Credit note", "Discount", "Line cancelled", "Refund"]
    assert r.metric("discounts") == D("500.00")
    assert r.metric("credit_notes") == D("5000.00")
    assert r.metric("refunds") == D("5000.00")
    assert r.metric("cancellations") == 1


def test_adjustments_filter_by_user(day: Day) -> None:
    r = queries.adjustments(_period(user_id=day.cashier.pk))
    assert r.section("discounts").rows == []
    assert r.section("refunds").rows == []
    assert len(r.section("line_cancellations").rows) == 1
    assert [_en(row["kind"]) for row in r.section("detail").rows] == ["Line cancelled"]


def test_adjustments_filter_by_department(day: Day) -> None:
    r = queries.adjustments(_period(department_id=day.lab.pk))
    assert r.metric("discounts") == D("0.00")
    assert r.metric("credit_notes") == D("0.00")
    assert r.metric("cancellations") == 0


# --- payer receivables ---------------------------------------------------------------------


def test_payer_receivables(day: Day) -> None:
    r = queries.payer_receivables(_period())
    (row,) = r.section("by_stage").rows
    assert _en(row["payer"]) == day.insurer.name_en
    assert row["accrued"] == D("7000.00")
    assert row["receivable"] == D("7000.00")
    assert row["collected"] == D("0.00")
    (aging,) = r.section("aging").rows
    assert aging["days_0_30"] == D("7000.00")
    assert aging["total"] == D("7000.00")
    assert r.metric("receivable") == D("7000.00")
    assert r.metric("collected") == D("0.00")


# --- exception reports ---------------------------------------------------------------------


def test_requested_not_invoiced(day: Day) -> None:
    r = queries.requested_not_invoiced(_period())
    (row,) = r.section("lines").rows
    assert row["visit"] == day.visit_b.number
    assert _en(row["service"]) == day.injection.name_en
    assert row["age"] == 0
    assert r.metric("lines") == 1
    assert _rows(r, "by_department", "department", "count") == [(day.opd.name_en, 1)]


def test_requested_not_invoiced_age_and_department(day: Day) -> None:
    ServiceLine.objects.filter(pk=day.inj_b_open.pk).update(
        ordered_at=timezone.now() - timedelta(days=4)
    )
    r = queries.requested_not_invoiced(_period())
    assert r.section("lines").rows[0]["age"] == 4
    assert r.metric("oldest_age") == 4
    by_age = {_en(row["age_bucket"]): row["count"] for row in r.section("by_age").rows}
    assert by_age["4-7 days"] == 1
    assert queries.requested_not_invoiced(_period(department_id=day.lab.pk)).metric("lines") == 0


def test_paid_not_performed(day: Day) -> None:
    r = queries.paid_not_performed(_period())
    rows = {row["visit"]: row for row in r.section("lines").rows}
    assert set(rows) == {day.visit_a.number, day.visit_b.number}
    assert rows[day.visit_a.number]["amount"] == D("1500.00")  # 2,000 less the 500 discount
    assert rows[day.visit_b.number]["amount"] == D("10000.00")
    assert r.metric("amount") == D("11500.00")
    assert r.metric("lines") == 2
    assert queries.paid_not_performed(_period(department_id=day.lab.pk)).metric("lines") == 1


def test_performed_by_authorization(day: Day) -> None:
    r = queries.performed_by_authorization(_period())
    (row,) = r.section("lines").rows
    assert row["visit"] == day.visit_c.number
    assert _en(row["authorization"]) == "Emergency"
    assert _en(row["authorized_by"]) == day.supervisor.display_name_en
    assert _en(row["performed_by"]) == day.nurse.display_name_en
    assert _en(row["billing"]) == "Not invoiced"
    assert _rows(r, "by_authorizer", "authorized_by", "count", "unbilled") == [
        (day.supervisor.display_name_en, 1, 1)
    ]
    yesterday = timezone.localdate() - timedelta(days=1)
    past = queries.performed_by_authorization(
        resolve_filters(date_from=yesterday, date_to=yesterday)
    )
    assert past.metric("lines") == 0
