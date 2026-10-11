"""``seed_demo``: the demo dataset made through the services (ADR 0017)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.billing.models import DocumentStatus, Invoice, InvoiceLine
from apps.core.demo import data
from apps.core.demo.clock import DemoClock, simulated_time
from apps.core.demo.names import make_people
from apps.core.models import User
from apps.lab.models import LabTest
from apps.ledger.models import JournalEntry, JournalLine
from apps.orders.models import BillingStatus, FulfilmentStatus, ServiceLine
from apps.patients.models import Patient
from apps.payments.models import Payment, PaymentMethod, Shift, ShiftStatus, Verification
from apps.pharmacy.models import Item, StockBalance
from apps.visits.models import Visit

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def test_refuses_a_database_that_is_not_a_demo_one(monkeypatch: Any) -> None:
    monkeypatch.setitem(connection.settings_dict, "NAME", "hospital_prod")
    with pytest.raises(CommandError, match="Refusing to run seed_demo"):
        _run("--days", "1")
    assert not Visit.objects.exists()


def test_reference_data_has_the_promised_sizes() -> None:
    clinical = {code for code, _, _ in data.CLINICAL_DEPARTMENTS}
    assert len(clinical) == 5
    assert len(data.DOCTORS) == 10
    assert {d.department for d in data.DOCTORS} == clinical
    assert 190 <= len(data.DRUGS) <= 230
    assert 45 <= len(data.LAB_TESTS) <= 55
    assert len(data.PAYERS) == 3
    assert len({p.rules[0].rule_kind for p in data.PAYERS}) == 3
    assert len({d.code for d in data.DRUGS}) == len(data.DRUGS)
    for scenarios in data.SCENARIOS.values():
        for s in scenarios:
            for code in (*s.labs, *s.extra_labs):
                assert any(t.code == code for t in data.LAB_TESTS), code
            for rx in s.rx:
                assert any(d.code == rx.drug for d in data.DRUGS), rx.drug


def test_people_are_deterministic_distinct_and_sudanese() -> None:
    today = timezone.localdate()
    first = make_people(random.Random(7), 120, today=today)
    second = make_people(random.Random(7), 120, today=today)
    assert first == second
    assert len({p.full_name_ar for p in first}) == 120
    assert len({p.phone for p in first}) == 120
    assert all(p.phone.startswith(("09", "01")) and len(p.phone) == 10 for p in first)
    assert all(p.date_of_birth < today for p in first)
    assert all(len(p.full_name_ar.split()) >= 3 for p in first)
    assert {p.sex for p in first} == {"male", "female"}


def test_simulated_clock_moves_time_and_is_restored() -> None:
    start = timezone.now() - timedelta(days=20)
    clock = DemoClock(start)
    with simulated_time(clock):
        assert timezone.now() >= start
        assert timezone.localdate() == timezone.localtime(start).date()
        clock.at(timezone.localdate() + timedelta(days=1), 9)
        assert timezone.localtime(timezone.now()).hour == 9
        # Never backwards: rows keep their order.
        clock.set(start)
        assert timezone.now() > start + timedelta(hours=12)
    assert abs(timezone.now() - datetime.now(tz=timezone.get_current_timezone())) < timedelta(
        seconds=5
    )


def test_a_small_month_is_complete_consistent_and_idempotent() -> None:
    out = _run("--days", "4", "--patients", "50", "--visits-per-day", "7", "--seed", "11")
    assert "activity:" in out
    today = timezone.localdate()
    start = today - timedelta(days=4)

    # Configuration.
    assert Item.objects.count() == len(data.DRUGS) + len(data.SUPPLIES)
    assert LabTest.objects.count() == len(data.LAB_TESTS)
    assert User.objects.filter(username__startswith="dr.").count() == 10

    # History is dated inside the month, never in the future.
    visits = Visit.objects.all()
    assert visits.count() >= 12
    first = timezone.localdate(visits.order_by("created_at").first().created_at)  # type: ignore[union-attr]
    assert start <= first < today
    assert not visits.filter(created_at__gt=timezone.now()).exists()
    assert Patient.objects.count() <= 50

    # Invoices with insurance splits; the patient and payer shares add up to the net.
    approved = InvoiceLine.objects.filter(invoice__status=DocumentStatus.APPROVED, frozen=True)
    assert approved.filter(payer__isnull=False, payer_share__gt=0).exists()
    for il in approved:
        assert il.payer_share + il.patient_share == il.gross - il.discount

    # Money: cash and transfers, pending and confirmed; every entry balances.
    assert Payment.objects.filter(method=PaymentMethod.CASH).exists()
    transfers = Payment.objects.filter(method=PaymentMethod.BANK_TRANSFER)
    assert transfers.filter(verification=Verification.PENDING).exists()
    # Transfers of the last two days wait for the accountant; older ones were checked.
    older = transfers.filter(reversal_of__isnull=True, transfer_date__lt=today - timedelta(days=2))
    if older.exists():
        assert older.exclude(verification=Verification.PENDING).exists()
    unbalanced = (
        JournalEntry.objects.annotate(d=Sum("lines__debit"), c=Sum("lines__credit"))
        .exclude(d=F("c"))
        .count()
    )
    assert unbalanced == 0
    totals = JournalLine.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
    assert totals["d"] == totals["c"]

    # Shifts: the past ones closed with a frozen report; a variance carries its reason.
    closed = Shift.objects.filter(status=ShiftStatus.CLOSED)
    assert closed.count() >= 4
    assert not closed.filter(close_report__isnull=True).exists()
    assert not closed.exclude(variance=Decimal(0)).filter(variance_reason__isnull=True).exists()
    assert not Shift.objects.filter(status=ShiftStatus.OPEN, opened_at__date__lt=today).exists()

    # Invariant 1: nothing was given unbilled without an authorization.
    given = ServiceLine.objects.filter(fulfilment_status=FulfilmentStatus.PERFORMED)
    assert given.exists()
    assert (
        not given.filter(billing_status=BillingStatus.UNBILLED, authorization__isnull=True)
        .exclude(kind="consultation")
        .exists()
    )
    # Invariant 5: stock never negative, and it moved at dispense.
    assert not StockBalance.objects.filter(qty_base__lt=0).exists()
    assert ServiceLine.objects.filter(kind="drug", fulfilment_status="performed").exists()

    # Approved results exist; a second run makes nothing new.
    counts = (
        Visit.objects.count(),
        Payment.objects.count(),
        Invoice.objects.count(),
        JournalEntry.objects.count(),
    )
    again = _run("--days", "4", "--patients", "50", "--visits-per-day", "7", "--seed", "11")
    assert "already has visits" in again
    assert "nothing new" in again
    assert counts == (
        Visit.objects.count(),
        Payment.objects.count(),
        Invoice.objects.count(),
        JournalEntry.objects.count(),
    )
    assert Patient.objects.annotate(n=Count("visits")).filter(Q(n=0)).count() == 0
