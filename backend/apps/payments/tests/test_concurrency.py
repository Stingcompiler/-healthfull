"""Races on real connections: row locks keep money operations consistent.

Each thread gets its own database connection and commits for real (transactional tests), so
the commit-time triggers run too. A barrier starts the threads together.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections

from apps.billing import services as billing
from apps.payments import services as pay
from apps.payments.models import Allocation, Bank, Payment, Shift
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db(transaction=True)


def _race(*calls: Callable[[], Any]) -> list[Any]:
    """Run ``calls`` in parallel threads; each result is a return value or an exception."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def run(i: int, call: Callable[[], Any]) -> None:
        try:
            barrier.wait(timeout=10)
            results[i] = call()
        except Exception as exc:
            results[i] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def _codes(results: list[Any]) -> list[str]:
    return sorted(r.code if isinstance(r, DomainError) else "ok" for r in results)


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def test_a_cashier_cannot_open_two_shifts_at_once() -> None:
    cashier = fin.staff("cashier")
    results = _race(*(lambda: pay.open_shift(cashier, D("100.00")) for _ in range(3)))
    assert _codes(results) == ["SHIFT_ALREADY_OPEN", "SHIFT_ALREADY_OPEN", "ok"]
    assert Shift.objects.filter(cashier=cashier, status="open").count() == 1


def test_one_payment_cannot_be_allocated_twice() -> None:
    cashier = fin.staff("cashier")
    doctor = fin.staff("doctor")
    patient = fin.patient()
    invoices = []
    for _ in range(2):
        visit = fin.visit(patient)
        fin.order(visit, doctor, fin.priced("lab", "100.00"))
        invoices.append(fin.invoice(visit, cashier))
    shift = pay.open_shift(cashier, D("0.00"))
    payment = pay.record_payment(shift, patient, "cash", D("100.00"), actor=cashier)
    results = _race(
        *(
            lambda inv=inv: pay.allocate(payment, [(inv, D("100.00"))], actor=cashier)
            for inv in invoices
        )
    )
    assert _codes(results) == ["ALLOCATION_EXCEEDS_PAYMENT", "ok"]
    assert sum(Allocation.objects.filter(payment=payment).values_list("amount", flat=True)) == D(
        "100.00"
    )
    assert [billing.invoice_position(inv).outstanding for inv in invoices].count(D("0.00")) == 1
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_concurrent_transfers_with_one_reference_store_one() -> None:
    bank = Bank.objects.get(code="BOK")
    cashiers = [fin.staff("cashier") for _ in range(2)]
    shifts = [pay.open_shift(c, D("0.00")) for c in cashiers]
    patients = [fin.patient() for _ in cashiers]
    results = _race(
        *(
            lambda i=i: pay.record_payment(
                shifts[i],
                patients[i],
                "bank_transfer",
                D("50.00"),
                actor=cashiers[i],
                bank=bank,
                reference="FT-777",
            )
            for i in range(2)
        )
    )
    assert _codes(results) == ["DUPLICATE_REFERENCE", "ok"]
    assert Payment.objects.filter(bank=bank).count() == 1
    fin.assert_books_balance()


def test_an_invoice_is_approved_once() -> None:
    cashiers = [fin.staff("cashier") for _ in range(2)]
    visit = fin.visit()
    (line,) = fin.order(visit, fin.staff("doctor"), fin.priced("lab", "100.00"))
    draft = billing.create_draft_invoice(visit, cashiers[0])
    results = _race(*(lambda c=c: billing.approve_invoice(draft, actor=c) for c in cashiers))
    assert _codes(results) == ["INVOICE_NOT_DRAFT", "ok"]
    line.refresh_from_db()
    assert line.billing_status == "invoiced"
    fin.assert_books_balance()
