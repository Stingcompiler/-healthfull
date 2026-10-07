"""Concurrency regressions from the Phase 1 review, on separate database connections.

Pattern: thread A runs a real service inside an outer transaction and holds its commit; thread
B runs the competing service on its own connection. Each race the review found let B finish
on a stale read; with the locks in place B either waits for A or sees A's result, and the
documents, the ledger and the invariants agree afterwards.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections, transaction
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import InvoiceLine
from apps.catalog.tests.seeding import restore_reference_data
from apps.claims import services as claims
from apps.claims.models import ClaimLine
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.models import JournalEntry
from apps.orders import services as orders
from apps.payments import services as pay
from apps.payments.models import Allocation, Bank
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _seed() -> None:
    restore_reference_data()
    fin.seed()


class Held:
    """Run ``fn`` in a thread inside an outer transaction; commit only when released."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.ready = threading.Event()
        self.release = threading.Event()
        self.result: Any = None
        self.thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        try:
            with transaction.atomic():
                self.result = self.fn()
                self.ready.set()
                self.release.wait(30)
        except Exception as exc:
            self.result = exc
        finally:
            self.ready.set()
            connections.close_all()

    def start(self) -> Held:
        self.thread.start()
        assert self.ready.wait(30)
        return self

    def commit(self) -> Any:
        self.release.set()
        self.thread.join(60)
        return self.result


class Other:
    """Run ``fn`` in a thread on its own connection."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.result: Any = None
        self.thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        try:
            self.result = self.fn()
        except Exception as exc:
            self.result = exc
        finally:
            connections.close_all()

    def start(self) -> Other:
        self.thread.start()
        return self

    def finished_within(self, seconds: float) -> bool:
        self.thread.join(seconds)
        return not self.thread.is_alive()


def _code(result: Any) -> str:
    if isinstance(result, DomainError):
        return result.code
    if isinstance(result, Exception):
        return f"{type(result).__name__}: {result}"
    return "ok"


def test_claim_batch_and_credit_note_never_both_take_a_payer_share() -> None:
    """Review: a claim built while a credit note was being approved claimed the payer share
    the credit note reversed (claimed 70.00, AR_PAYER 0.00)."""
    cashier = fin.staff("cashier")
    accountant = fin.staff("accountant")
    payer = fin.payer(percent="70")
    v = fin.visit(payer_obj=payer)
    fin.order(v, fin.staff("doctor"), fin.priced("lab", "100.00"))
    inv = fin.invoice(v, cashier)
    il = InvoiceLine.objects.get(invoice=inv)
    cn = billing.create_credit_note(inv, [(il, 1)], actor=cashier, reason="PRICE_ERROR")
    today = timezone.localdate()
    held = Held(lambda: billing.approve_credit_note(cn, actor=accountant)).start()
    other = Other(
        lambda: claims.build_claim(
            payer=payer, period_start=today, period_end=today, actor=accountant
        )
    ).start()
    assert not other.finished_within(1.5), "the claim did not wait for the credit note"
    assert _code(held.commit()) == "ok"
    other.thread.join(30)
    assert _code(other.result) == "CLAIM_EMPTY"
    assert not ClaimLine.objects.filter(invoice_line=il).exclude(status="withdrawn").exists()
    row = claims.payer_receivables(payer=payer).get(payer.pk)
    assert (row.receivable if row else D(0)) == ledger.account_balance("AR_PAYER", payer=payer)


def test_revocation_waits_for_work_starting_under_the_authorization() -> None:
    """Review: start_line and revoke_authorization both committed; the line was left in
    progress under a revoked authorization and could never be performed."""
    sup = fin.staff(superuser=True)
    tech = fin.staff("lab_tech")
    v = fin.visit()
    (line,) = fin.order(v, fin.staff("doctor"), fin.priced("lab", "100.00"))
    auth = orders.authorize_perform_first([line], actor=sup, reason="EMERGENCY", kind="emergency")
    held = Held(lambda: orders.start_line(line, tech)).start()
    other = Other(lambda: orders.revoke_authorization(auth, actor=sup, note="left")).start()
    assert not other.finished_within(1.5), "the revocation did not wait for the started line"
    assert _code(held.commit()) == "ok"
    other.thread.join(30)
    assert _code(other.result) == "AUTHORIZATION_IN_USE"
    orders.perform_line(line, tech)


def test_allocation_never_lands_in_a_shift_closed_while_it_waited() -> None:
    """Review: allocate read the open shift, waited for close_shift, and then booked the
    allocation and its journal entry into the closed shift."""
    cashier = fin.staff("cashier")
    patient = fin.patient()
    v = fin.visit(patient)
    fin.order(v, fin.staff("doctor"), fin.priced("lab", "100.00"))
    inv = fin.invoice(v, cashier)
    shift = pay.open_shift(cashier, D("0.00"))
    payment = pay.record_payment(shift, patient, "cash", D("100.00"), actor=cashier)
    counted = pay.expected_cash(shift)
    held = Held(lambda: pay.close_shift(shift, counted, actor=cashier)).start()
    other = Other(lambda: pay.allocate(payment, [(inv, D("100.00"))], actor=cashier)).start()
    assert not other.finished_within(1.0)
    assert _code(held.commit()) == "ok"
    other.thread.join(30)
    assert _code(other.result) == "ok"
    shift.refresh_from_db()
    rows = list(Allocation.objects.filter(payment=payment).values_list("shift_id", flat=True))
    assert rows == [None]  # no open shift of the actor any more: not the closed one
    assert not JournalEntry.objects.filter(shift_id=shift.pk, source_type="allocation").exists()
    assert not JournalEntry.objects.filter(
        shift_id=shift.pk, posted_at__gt=shift.closed_at
    ).exists()


def test_transfer_confirmation_never_books_into_a_shift_closing_meanwhile(monkeypatch) -> None:
    """Review: confirm_transfer read the original shift as open and posted into it after it
    had closed."""
    cashier = fin.staff("cashier")
    verifier = fin.staff("cashier_supervisor")
    shift = pay.open_shift(cashier, D("0.00"))
    payment = pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("50.00"),
        actor=cashier,
        bank=Bank.objects.get(code="BOK"),
        reference="FT-RACE",
    )
    gate = threading.Event()
    real = pay._share_open_shift

    def slow(shift_id: int | None) -> int | None:
        gate.set()
        time.sleep(1.0)  # close_shift runs in this window
        return real(shift_id)

    monkeypatch.setattr(pay, "_share_open_shift", slow)
    other = Other(
        lambda: pay.confirm_transfer(payment, actor=verifier, note="statement ok")
    ).start()
    assert gate.wait(10)
    monkeypatch.setattr(pay, "_share_open_shift", real)
    closed = pay.close_shift(shift, pay.expected_cash(shift), actor=cashier)
    other.thread.join(30)
    assert _code(other.result) == "ok"
    assert not JournalEntry.objects.filter(
        shift_id=shift.pk, posted_at__gt=closed.closed_at
    ).exists()


def test_one_patient_is_never_admitted_twice_at_once() -> None:
    from apps.visits import services as vs
    from apps.visits.models import Admission, Bed

    clerk = fin.staff("receptionist")
    doctor = b.doctor()
    patient = fin.patient()
    svc = b.service(kind="bed")
    beds = [
        Bed.objects.create(code=f"RB{i}", name_ar=f"سرير {i}", name_en=f"Bed {i}", bed_service=svc)
        for i in (1, 2)
    ]
    v1 = vs.create_visit(patient=patient, actor=clerk, department=b.department())
    v2 = vs.create_visit(patient=patient, actor=clerk, department=b.department())
    held = Held(lambda: vs.admit(v1, doctor=doctor, bed=beds[0], actor=clerk)).start()
    other = Other(lambda: vs.admit(v2, doctor=doctor, bed=beds[1], actor=clerk)).start()
    assert not other.finished_within(1.5)
    assert _code(held.commit()) == "ok"
    other.thread.join(30)
    assert _code(other.result) == "PATIENT_ALREADY_ADMITTED"
    assert Admission.objects.filter(patient=patient, status="admitted").count() == 1


def test_cancel_visit_and_finish_consultation_do_not_deadlock(monkeypatch) -> None:
    """Review: cancel_visit locked lines then queue entries, finish_consultation the queue
    entry then the fee line: Postgres aborted one with a deadlock (HTTP 500)."""
    from apps.visits import services as vs
    from apps.visits.models import QueueEntry

    clerk = fin.staff("receptionist")
    sup = fin.staff(superuser=True)
    doc = b.doctor()
    doc.consultation_service = fin.priced("consultation", "300.00")
    doc.save()
    visit = vs.create_visit(patient=fin.patient(), actor=clerk, doctor=doc)
    fee = visit.lines.get()
    orders.authorize_perform_first([fee], actor=sup, reason="EMERGENCY", kind="emergency")
    entry = vs.start_consultation(QueueEntry.objects.get(visit=visit), actor=clerk)
    real = orders.perform_line
    holding = threading.Event()

    def slow_perform(*args: Any, **kwargs: Any) -> Any:
        holding.set()
        time.sleep(1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(orders, "perform_line", slow_perform)
    out: dict[str, Any] = {}

    def finish() -> None:
        try:
            out["finish"] = vs.finish_consultation(entry, actor=clerk)
        except Exception as exc:
            out["finish"] = exc
        finally:
            connections.close_all()

    def cancel() -> None:
        try:
            holding.wait(10)
            out["cancel"] = vs.cancel_visit(visit, actor=sup, reason_code="PATIENT_LEFT")
        except Exception as exc:
            out["cancel"] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=finish), threading.Thread(target=cancel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    codes = {k: _code(v) for k, v in out.items()}
    assert not any("deadlock" in c.lower() for c in codes.values()), codes
    assert codes["finish"] == "ok"
    assert codes["cancel"] == "VISIT_HAS_PERFORMED_WORK"


def test_concurrent_price_updates_build_on_each_other() -> None:
    """Review: two bulk updates for d1 < d2 ran at once and d2 was built from the old base,
    silently reverting d1's +10% lab change from d2 on."""
    from apps.catalog import services as catalog
    from apps.catalog.models import PriceItem, PriceListVersion

    admin = fin.staff(superuser=True)
    plist = fin.cash_list()
    lab = fin.priced("lab", "100.00")
    drug = fin.priced("drug", "50.00")
    today = timezone.localdate()
    d1, d2 = today + timedelta(days=10), today + timedelta(days=20)
    held = Held(
        lambda: catalog.bulk_percentage_update(
            plist, percent=10, effective_from=d1, actor=admin, service_ids=[lab.pk]
        )
    ).start()
    other = Other(
        lambda: catalog.bulk_percentage_update(
            plist, percent=20, effective_from=d2, actor=admin, service_ids=[drug.pk]
        )
    ).start()
    assert not other.finished_within(1.0)
    assert _code(held.commit()) == "ok"
    other.thread.join(30)
    assert _code(other.result) == "ok"
    v2 = PriceListVersion.objects.get(price_list=plist, effective_from=d2)
    assert PriceItem.objects.get(version=v2, service=lab).unit_price == D("110.00")
    assert PriceItem.objects.get(version=v2, service=drug).unit_price == D("60.00")


def test_double_submitted_registration_makes_one_file() -> None:
    """Review: two registrations of one person at once both passed the duplicate check."""
    from apps.patients import services as pts
    from apps.patients.models import Patient

    clerks = [fin.staff("receptionist") for _ in range(2)]
    data = pts.PatientData(
        sex="female", full_name_ar="سلمى علي حسن", phone="0912345678", age_years=30
    )
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def register(clerk: Any) -> None:
        try:
            barrier.wait(10)
            results.append(pts.register_patient(data, actor=clerk))
        except Exception as exc:
            results.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=register, args=(c,)) for c in clerks]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(_code(r) for r in results) == ["DUPLICATE_PATIENT", "ok"]
    assert Patient.objects.filter(phone="0912345678").count() == 1
