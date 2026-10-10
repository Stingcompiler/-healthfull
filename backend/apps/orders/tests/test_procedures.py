"""The procedure work list and one-tap "done" (FEATURES 10.1, 10.2; invariant 1).

Only paid or authorized open procedure lines are listed and performed; a done mark records
who and when (and the optional note); a second tap, a cancelled line, an unpaid line or a
line of another kind is refused with its own code; two nurses tapping the same line at once
perform it once.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.payments import services as pay
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def doctor():
    return fin.staff("doctor")


@pytest.fixture
def nurse():
    return fin.staff("nurse")


@pytest.fixture
def cashier():
    return fin.staff("cashier")


@pytest.fixture
def supervisor():
    return fin.staff("cashier_supervisor")


def _pay(visit, cashier, *lines):
    inv = fin.invoice(visit, cashier, list(lines))
    shift = pay.current_shift(cashier) or pay.open_shift(cashier, D("0.00"))
    pay.record_payment(shift, inv.patient, "cash", inv.patient_total, actor=cashier, auto=True)
    return inv


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


def test_worklist_lists_only_paid_or_authorized_open_procedures(
    doctor, nurse, cashier, supervisor
) -> None:
    prc, other = b.department(), b.department()
    visit = fin.visit()
    unpaid, paid, authorized, done, lab, elsewhere = fin.order(
        visit,
        doctor,
        fin.priced("procedure", department=prc),
        fin.priced("procedure", department=prc),
        fin.priced("procedure", department=prc),
        fin.priced("procedure", department=prc),
        fin.priced("lab", department=prc),
        fin.priced("procedure", department=other),
    )
    _pay(visit, cashier, paid, done, lab, elsewhere)
    orders.authorize_perform_first([authorized], actor=supervisor, reason="EMERGENCY")
    orders.perform_procedure(done, nurse)

    assert [ln.pk for ln in orders.procedure_worklist()] == [
        paid.pk,
        authorized.pk,
        elsewhere.pk,
    ]
    assert [ln.pk for ln in orders.procedure_worklist(department=prc.pk)] == [
        paid.pk,
        authorized.pk,
    ]
    assert unpaid.pk not in {ln.pk for ln in orders.procedure_worklist()}


def test_worklist_search_by_patient(doctor, cashier) -> None:
    salma = fin.visit(b.patient(full_name_ar="سلمى عثمان", full_name_en="Salma Osman"))
    ali = fin.visit(b.patient(full_name_ar="علي حسن", full_name_en="Ali Hassan"))
    svc = fin.priced("procedure")
    (s_line,) = fin.order(salma, doctor, svc)
    (a_line,) = fin.order(ali, doctor, svc)
    _pay(salma, cashier, s_line)
    _pay(ali, cashier, a_line)
    assert [ln.pk for ln in orders.procedure_worklist(q="salma")] == [s_line.pk]
    assert [ln.pk for ln in orders.procedure_worklist(q=ali.patient.file_no)] == [a_line.pk]
    assert orders.procedure_worklist(q="nobody-like-this") == []


def test_done_records_who_when_and_note(doctor, nurse, cashier) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    _pay(visit, cashier, line)
    before = timezone.now()
    done = orders.perform_procedure(line, nurse, note="  left deltoid  ")
    assert done.fulfilment_status == "performed"
    assert done.performed_by == nurse
    assert done.performed_at is not None
    assert done.performed_at >= before
    assert done.performed_note == "left deltoid"
    assert orders.line_state(done) == "performed"
    assert [ln.pk for ln in orders.procedures_done()] == [line.pk]
    assert orders.procedure_worklist() == []


def test_unpaid_procedure_cannot_be_done(doctor, nurse) -> None:
    """Invariant 1: no service without a settled line or a documented authorization."""
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(line, nurse)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"
    assert ServiceLine.objects.get(pk=line.pk).fulfilment_status == "pending"


def test_invoiced_but_unpaid_procedure_cannot_be_done(doctor, nurse, cashier) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    fin.invoice(visit, cashier, [line])
    assert ServiceLine.objects.get(pk=line.pk).billing_status == "invoiced"
    assert orders.procedure_worklist() == []
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(line, nurse)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"


def test_revoked_authorization_leaves_the_worklist(doctor, nurse, supervisor) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    auth = orders.authorize_perform_first([line], actor=supervisor, reason="EMERGENCY")
    assert [ln.pk for ln in orders.procedure_worklist()] == [line.pk]
    orders.revoke_authorization(auth, actor=supervisor, note="family will pay first")
    assert orders.procedure_worklist() == []
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(line, nurse)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"


def test_second_tap_and_other_kinds_are_refused(doctor, nurse, cashier) -> None:
    visit = fin.visit()
    procedure, lab = fin.order(visit, doctor, fin.priced("procedure"), fin.priced("lab"))
    _pay(visit, cashier, procedure, lab)
    orders.perform_procedure(procedure, nurse)
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(procedure, nurse)
    assert _code(exc) == "LINE_ALREADY_PERFORMED"
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(lab, nurse)
    assert _code(exc) == "LINE_NOT_PROCEDURE"
    assert ServiceLine.objects.get(pk=lab.pk).fulfilment_status == "pending"


def test_cancelled_procedure_cannot_be_done(doctor, nurse) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    orders.cancel_line(line, "PATIENT_REFUSED", doctor)
    with pytest.raises(DomainError) as exc:
        orders.perform_procedure(line, nurse)
    assert _code(exc) == "LINE_CANCELLED"


def test_done_list_is_today_newest_first(doctor, nurse, cashier) -> None:
    visit = fin.visit()
    first, second, old = fin.order(
        visit, doctor, fin.priced("procedure"), fin.priced("procedure"), fin.priced("procedure")
    )
    _pay(visit, cashier, first, second, old)
    orders.perform_procedure(first, nurse)
    orders.perform_procedure(second, nurse)
    orders.perform_procedure(old, nurse, at=timezone.now() - timedelta(days=1))
    assert [ln.pk for ln in orders.procedures_done()] == [second.pk, first.pk]
    yesterday = timezone.localdate() - timedelta(days=1)
    assert [ln.pk for ln in orders.procedures_done(on=yesterday)] == [old.pk]


@pytest.mark.django_db(transaction=True)
def test_two_nurses_tapping_at_once_perform_the_line_once() -> None:
    fin.seed()
    doctor, cashier = fin.staff("doctor"), fin.staff("cashier")
    nurses = [fin.staff("nurse") for _ in range(3)]
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    _pay(visit, cashier, line)
    results: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(nurses))

    def tap(nurse) -> None:
        try:
            barrier.wait(timeout=10)
            orders.perform_procedure(line, nurse)
            outcome = "ok"
        except DomainError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=tap, args=(n,)) for n in nurses]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == ["LINE_ALREADY_PERFORMED"] * 2 + ["ok"], results
    stored = ServiceLine.objects.get(pk=line.pk)
    assert stored.fulfilment_status == "performed"
