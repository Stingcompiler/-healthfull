"""Work lists (FEATURES 4.3), the exception reports (FEATURES 4.5) and a withdrawal that
meets an invoice approved concurrently (FEATURES 4.2)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import CreditNote
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


def _age(line: ServiceLine, field: str, days: int) -> None:
    ServiceLine.objects.filter(pk=line.pk).update(**{field: timezone.now() - timedelta(days=days)})


def test_worklist_lines_hold_only_paid_or_authorized_open_lines(
    doctor, cashier, supervisor
) -> None:
    lab_dept, other_dept = b.department(), b.department()
    visit = fin.visit()
    unpaid, paid, authorized, done, elsewhere = fin.order(
        visit,
        doctor,
        fin.priced("lab", department=lab_dept),
        fin.priced("lab", department=lab_dept),
        fin.priced("lab", department=lab_dept),
        fin.priced("lab", department=lab_dept),
        fin.priced("lab", department=other_dept),
    )
    _pay(visit, cashier, paid, done, elsewhere)
    orders.authorize_perform_first([authorized], actor=supervisor, reason="EMERGENCY")
    orders.perform_line(done, doctor)

    listed = orders.worklist_lines(["lab"], department=lab_dept.pk)
    assert [ln.pk for ln in listed] == [paid.pk, authorized.pk]
    assert unpaid.pk not in {ln.pk for ln in orders.worklist_lines(["lab"])}
    assert {ln.pk for ln in orders.worklist_lines(["lab"])} == {
        paid.pk,
        authorized.pk,
        elsewhere.pk,
    }
    assert orders.worklist_lines(["procedure"]) == []
    for bad in ([], ["lab", "magic"]):
        with pytest.raises(DomainError) as exc:
            orders.worklist_lines(bad)
        assert exc.value.code == "INVALID_KIND"


def test_requested_not_invoiced_report_with_age(doctor, supervisor) -> None:
    visit = fin.visit()
    old, fresh, authorized, withdrawn = fin.order(
        visit, doctor, fin.priced("lab"), fin.priced("lab"), fin.priced("lab"), fin.priced("lab")
    )
    _age(old, "ordered_at", 5)
    orders.authorize_perform_first([authorized], actor=supervisor, reason="EMERGENCY")
    orders.cancel_line(withdrawn, "ORDER_ERROR", doctor)

    rows = orders.report_requested_not_invoiced()
    assert [(r.line.pk, r.age_days) for r in rows] == [(old.pk, 5), (fresh.pk, 0)]
    assert [r.line.pk for r in orders.report_requested_not_invoiced(min_age_days=3)] == [old.pk]
    assert len(orders.report_requested_not_invoiced(limit=1)) == 1


def test_paid_not_performed_report_ages_from_settlement(doctor, cashier) -> None:
    visit = fin.visit()
    waiting, started, done, unpaid = fin.order(
        visit, doctor, fin.priced("lab"), fin.priced("drug"), fin.priced("lab"), fin.priced("lab")
    )
    _pay(visit, cashier, waiting, started, done)
    orders.start_line(started, doctor)
    orders.perform_line(done, doctor)
    _age(waiting, "settled_at", 4)

    rows = orders.report_paid_not_performed()
    assert [(r.line.pk, r.age_days) for r in rows] == [(waiting.pk, 4), (started.pk, 0)]
    assert unpaid.pk not in {r.line.pk for r in rows}
    assert [r.line.pk for r in orders.report_paid_not_performed(min_age_days=2)] == [waiting.pk]


def test_performed_by_authorization_report(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    first, second, pending, paid = fin.order(
        visit,
        doctor,
        fin.priced("procedure"),
        fin.priced("procedure"),
        fin.priced("procedure"),
        fin.priced("procedure"),
    )
    auth = orders.authorize_perform_first(
        [first, second, pending], actor=supervisor, reason="EMERGENCY", note="bleeding"
    )
    _pay(visit, cashier, paid)
    orders.perform_line(paid, doctor)
    orders.perform_line(first, doctor)
    orders.perform_line(second, doctor)
    _age(first, "performed_at", 3)

    rows = orders.report_performed_by_authorization()
    assert [(r.line.pk, r.age_days) for r in rows] == [(second.pk, 0), (first.pk, 3)]
    assert fin.some(rows[0].line.authorization).authorized_by == supervisor
    assert fin.some(rows[0].line.authorization).pk == auth.pk
    today = timezone.localdate()
    assert [
        r.line.pk for r in orders.report_performed_by_authorization(date_to=today - timedelta(1))
    ] == [first.pk]
    assert [r.line.pk for r in orders.report_performed_by_authorization(date_from=today)] == [
        second.pk
    ]


def test_withdrawal_rechecks_billing_under_the_lock(doctor, cashier) -> None:
    """An invoice approved after the router loaded the line: refused, never credited."""
    admin = fin.staff("admin")
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab"))
    stale = ServiceLine.objects.get(pk=line.pk)
    fin.invoice(visit, cashier, [line])
    assert stale.billing_status == "unbilled"
    with pytest.raises(DomainError) as exc:
        orders.withdraw_order(stale, reason="ORDER_ERROR", note="", actor=admin)
    assert exc.value.code == "CREDIT_NOTE_REQUIRED"
    assert not CreditNote.objects.exists()
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("invoiced", "pending")


def test_withdrawal_refuses_a_line_already_under_way(doctor, supervisor) -> None:
    """Review: an unbilled line under a perform-first authorization that was started is no
    longer the doctor's to withdraw (it matches ``can_withdraw``); a pending one still is."""
    visit = fin.visit()
    started, waiting = fin.order(visit, doctor, fin.priced("lab"), fin.priced("lab"))
    orders.authorize_perform_first([started, waiting], actor=supervisor, reason="EMERGENCY")
    orders.start_line(started, fin.staff("lab_tech"))
    stale = ServiceLine.objects.get(pk=started.pk)
    with pytest.raises(DomainError) as exc:
        orders.withdraw_order(stale, reason="ORDER_ERROR", note="", actor=doctor)
    assert exc.value.code == "LINE_IN_PROGRESS"
    started.refresh_from_db()
    assert (started.fulfilment_status, started.cancelled_at) == ("in_progress", None)
    assert started.performed_by_id is None

    view = orders.withdraw_order(waiting, reason="ORDER_ERROR", note="", actor=doctor)
    assert view.status == "cancelled"


def test_withdrawal_is_a_clinical_act(doctor, cashier) -> None:
    """Review: the withdrawal answers with the doctor's line view (prescription, results,
    allergy override reasons), so it needs ``clinical.view`` besides ``orders.cancel_line``."""
    from api.errors import PermissionRequired

    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab"))
    for role in ("cashier", "cashier_supervisor", "pharmacist", "lab_supervisor", "manager"):
        with pytest.raises(PermissionRequired):
            orders.withdraw_order(line, reason="ORDER_ERROR", note="", actor=fin.staff(role))
    line.refresh_from_db()
    assert line.fulfilment_status == "pending"
