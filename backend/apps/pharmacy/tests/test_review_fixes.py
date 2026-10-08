"""Regression tests for the Phase 1 review: credited units, partial dispense, returns,
transfers and the dispensing backstops (invariants 1 and 5).

Each test reproduces a reviewer's failing scenario through the real services.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import CreditNoteLine, InvoiceLine
from apps.catalog.tests import engine
from apps.core.models import PartialDispenseRemainder, Policy
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.payments import services as pay
from apps.payments.models import Refund
from apps.pharmacy import services as ps
from apps.pharmacy.models import Batch, DispenseLine, StockBalance, StockMove
from domain.errors import DomainError

pytestmark = pytest.mark.django_db
D = Decimal
TODAY = date(2026, 10, 7)


@pytest.fixture
def cashier(make_user):
    return make_user(roles=["cashier"])


@pytest.fixture
def supervisor(make_user):
    return make_user(roles=["cashier_supervisor"])


@pytest.fixture
def pharmacist(make_user):
    return make_user(roles=["pharmacist"])


@pytest.fixture
def store():
    st = b.store("PHRV")
    st.allows_dispense = True
    st.save()
    return st


def _stocked(st, qty: int = 100, name: str = "Amoxicillin 500"):
    it = b.item(generic_name=name)
    batch = Batch.objects.create(
        item=it, batch_no=f"B{b.n()}", expiry_date=date(2030, 1, 1), unit_cost=D("2.5000")
    )
    b.stock_move(batch, st, str(qty))
    return it, batch


def _on_hand(batch, st) -> int:
    return int(StockBalance.objects.get(batch=batch, store=st).qty_base)


def _credit(line, units: int, actor, approver, **kw):
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    cn = billing.create_credit_note(il.invoice, [(il, units)], actor=actor, reason="PRICE_ERROR")
    return billing.approve_credit_note(cn, actor=approver, **kw)


# --- credited units are never given -----------------------------------------------------


def test_credited_units_cannot_be_dispensed(cashier, supervisor, pharmacist, store) -> None:
    """Review (accounting, concurrency): 2 of 10 tablets credited and refunded, then all 10
    were dispensed. Only the 8 still billed may leave the store."""
    it, batch = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    out = _credit(line, 2, cashier, supervisor, open_refund=True, refund_requested_by=cashier)
    assert out.deallocated == D("20.00")
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("settled", "pending")
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=line.visit,
            store=store,
            actor=pharmacist,
            requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=10)],
        )
    assert exc.value.code == "DISPENSE_EXCEEDS_LINE"
    assert exc.value.details["remaining"] == 8
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=8)],
    )
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.performed_quantity == D(8)
    assert ps.dispensed_quantity(line) == 8
    assert _on_hand(batch, store) == 92


def test_dispense_worklist_counts_credited_units(cashier, supervisor, pharmacist, store) -> None:
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    _credit(line, 3, cashier, supervisor)
    (row,) = [r for r in ps.dispense_worklist(visit=line.visit) if r.pk == line.pk]
    assert row.remaining == 7  # type: ignore[attr-defined]


def test_remainder_credit_skips_units_already_credited(
    cashier, supervisor, pharmacist, store
) -> None:
    """Review (accounting): 2 units credited, 6 dispensed with complete=True credited 6 more
    (8 of 10 credited, 6 given). Billed units less credited units must equal the given."""
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    _credit(line, 2, cashier, supervisor)
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        approver=supervisor,
        requests=[
            ps.DispenseRequest(
                service_line_id=line.pk,
                quantity=6,
                complete=True,
                complete_reason_code="OUT_OF_STOCK",
            )
        ],
    )
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    credited = sum(
        CreditNoteLine.objects.filter(invoice_line=il, frozen=True).values_list(
            "quantity", flat=True
        ),
        D(0),
    )
    assert il.quantity - credited == ps.dispensed_quantity(line) == 6
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.cancelled_at is not None  # the remainder's cancellation is documented


def test_closing_a_billed_remainder_needs_a_credit_note_approver(
    cashier, pharmacist, store
) -> None:
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    with pytest.raises(PermissionRequired):
        ps.dispense(
            visit=line.visit,
            store=store,
            actor=pharmacist,
            requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=4, complete=True)],
        )
    assert ps.dispensed_quantity(line) == 0  # nothing left the store


# --- cancelling a partly dispensed line ---------------------------------------------------


def test_cancel_partly_dispensed_paid_line_credits_only_what_was_not_given(
    cashier, supervisor, pharmacist, store
) -> None:
    """Review (invariants, concurrency, completeness): 6 of 10 paid tablets dispensed, then
    cancel_line credited and refunded all 10 (100.00). Only the 4 not given are refunded."""
    it, batch = _stocked(store, qty=6)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=6)],
        today=TODAY,
    )
    line.refresh_from_db()
    assert line.fulfilment_status == "in_progress"  # the first part started the work
    orders.cancel_line(
        line, "PATIENT_REFUSED", cashier, note="not coming back", approver=supervisor
    )
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.performed_quantity == D(6)
    assert line.billing_status == "settled"  # the 6 given stay billed and paid
    refund = Refund.objects.get(patient=line.visit.patient)
    assert refund.amount == D("40.00")
    assert pay.credit_balance(line.visit.patient) == D("40.00")
    assert _on_hand(batch, store) == 0


def test_cancel_partly_dispensed_authorized_line_bills_the_given_units(
    supervisor, pharmacist, store, make_user
) -> None:
    """Review (concurrency): a perform-first line partly dispensed and then cancelled ended
    cancelled and unbilled with dispensed stock. The given units must stay billable."""
    it, _ = _stocked(store)
    boss = make_user(roles=["cashier_supervisor"])
    v = b.visit()
    engine.price_version().items.get_or_create(service=it.service, defaults={"unit_price": D(10)})
    (line,) = orders.create_service_lines(v, [{"service": it.service, "quantity": 10}], boss)
    orders.authorize_perform_first([line], actor=boss, reason="EMERGENCY", kind="emergency")
    ps.dispense(
        visit=v,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=5)],
    )
    orders.cancel_line(line, "PATIENT_REFUSED", boss, note="left")
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("unbilled", "performed")
    assert line.performed_quantity == D(5)
    draft = billing.create_draft_invoice(v, boss)
    assert draft.lines.get().quantity == D(5)


def test_visit_with_dispensed_units_is_not_cancelled(cashier, supervisor, pharmacist, store):
    from apps.visits import services as vs

    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=3)],
    )
    with pytest.raises(DomainError) as exc:
        vs.cancel_visit(line.visit, actor=supervisor, reason_code="PATIENT_LEFT")
    assert exc.value.code == "VISIT_HAS_PERFORMED_WORK"


def test_credit_note_cannot_take_back_units_already_given(
    cashier, supervisor, pharmacist, store
) -> None:
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=7)],
    )
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    with pytest.raises(DomainError) as exc:
        billing.create_credit_note(il.invoice, [(il, 4)], actor=cashier, reason="PRICE_ERROR")
    assert exc.value.code == "CREDIT_EXCEEDS_UNGIVEN"
    billing.approve_credit_note(
        billing.create_credit_note(il.invoice, [(il, 3)], actor=cashier, reason="PRICE_ERROR"),
        actor=supervisor,
    )


def test_partial_dispense_blocks_revoking_the_authorization(pharmacist, store, make_user):
    it, _ = _stocked(store)
    boss = make_user(roles=["cashier_supervisor"])
    v = b.visit()
    (line,) = orders.create_service_lines(v, [{"service": it.service, "quantity": 10}], boss)
    auth = orders.authorize_perform_first([line], actor=boss, reason="EMERGENCY", kind="emergency")
    ps.dispense(
        visit=v,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=2)],
    )
    with pytest.raises(DomainError) as exc:
        orders.revoke_authorization(auth, actor=boss, note="changed mind")
    assert exc.value.code == "AUTHORIZATION_IN_USE"


def test_partial_dispense_policy_refund_closes_the_line(
    cashier, supervisor, pharmacist, store
) -> None:
    Policy.objects.update(partial_dispense_remainder=PartialDispenseRemainder.REFUND)
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        approver=supervisor,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=4, complete=None)],
    )
    line.refresh_from_db()
    assert (line.fulfilment_status, line.performed_quantity) == ("performed", D(4))


# --- database backstops -------------------------------------------------------------------


def test_db_refuses_dispense_lines_for_an_unpaid_line(store) -> None:
    """Review (invariants): a Dispense, a dispense move and a DispenseLine were accepted for an
    unbilled, unauthorized line."""
    it, batch = _stocked(store, qty=10)
    line = b.service_line(svc=it.service)
    d = ps.Dispense.objects.create(
        number=f"DSP-{b.n()}", visit=line.visit, store=store, dispensed_by=b.user()
    )
    mv = b.stock_move(batch, store, "-10", kind="dispense")
    b.db_rejects(
        lambda: DispenseLine.objects.create(
            dispense=d,
            service_line=line,
            item=it,
            batch=batch,
            quantity_units=D(10),
            qty_base=D(10),
            stock_move=mv,
        ),
        "LINE_NOT_ELIGIBLE",
    )


def test_db_refuses_dispensing_credited_units(cashier, supervisor, store) -> None:
    it, batch = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    _credit(line, 4, cashier, supervisor)
    d = ps.Dispense.objects.create(
        number=f"DSP-{b.n()}", visit=line.visit, store=store, dispensed_by=b.user()
    )
    mv = b.stock_move(batch, store, "-7", kind="dispense")
    b.db_rejects(
        lambda: DispenseLine.objects.create(
            dispense=d,
            service_line=line,
            item=it,
            batch=batch,
            quantity_units=D(7),
            qty_base=D(7),
            stock_move=mv,
        ),
        "DISPENSE_EXCEEDS_LINE",
    )


def test_db_refuses_cancelling_a_line_with_dispensed_units(pharmacist, store, make_user):
    it, _ = _stocked(store)
    boss = make_user(roles=["cashier_supervisor"])
    v = b.visit()
    (line,) = orders.create_service_lines(v, [{"service": it.service, "quantity": 10}], boss)
    orders.authorize_perform_first([line], actor=boss, reason="EMERGENCY", kind="emergency")
    ps.dispense(
        visit=v,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=2)],
    )
    b.sql_rejects(
        "UPDATE orders_serviceline SET fulfilment_status = 'cancelled', cancelled_at = now(), "
        "cancelled_by_id = %s, cancel_reason_id = %s WHERE id = %s",
        [boss.pk, b.reason("line_cancel").pk, line.pk],
        "LINE_PARTLY_DISPENSED",
    )


def test_db_keeps_a_billed_lines_order_fixed(cashier, pharmacist, store) -> None:
    """Review (invariants): a paid 1-unit line was raised to 40 units and 40 dispensed."""
    it, _ = _stocked(store, qty=50)
    line = engine.cash_paid_line(it.service, 1, cashier, unit_price="10.00")
    b.db_rejects(
        lambda: orders.ServiceLine.objects.filter(pk=line.pk).update(quantity=D(40)),
        "LINE_BILLED_READONLY",
    )


# --- returns and transfers ----------------------------------------------------------------


def test_returned_units_go_back_on_the_shelf(cashier, supervisor, pharmacist, store) -> None:
    it, batch = _stocked(store, qty=10)
    line = engine.cash_paid_line(it.service, 5, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=5)],
    )
    assert _on_hand(batch, store) == 5
    out = _credit(line, 2, cashier, supervisor)
    dl_row = DispenseLine.objects.get(service_line=line)
    ret = ps.return_dispense(
        dl_row,
        quantity=2,
        actor=pharmacist,
        reason_code="OTHER",
        note="patient returned sealed strips",
        credit_note=out.credit_note,
    )
    assert ret.stock_move.kind == "return"
    assert _on_hand(batch, store) == 7
    assert ps.returned_quantity(line) == 2
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(dl_row, quantity=4, actor=pharmacist, reason_code="OTHER", note="more")
    assert exc.value.code == "RETURN_EXCEEDS_DISPENSED"


def test_sent_transfer_can_be_cancelled_and_received_short(pharmacist, make_user) -> None:
    manager = make_user(roles=["manager"])
    main, ward = b.store("MAINX"), b.store("WARDX")
    _it, batch = _stocked(main, qty=20)
    t = ps.create_transfer(from_store=main, to_store=ward, lines=[(batch.pk, 10)], actor=pharmacist)
    ps.send_transfer(t, actor=pharmacist)
    assert _on_hand(batch, main) == 10
    with pytest.raises(DomainError) as exc:
        ps.cancel_transfer(t, actor=pharmacist)
    assert exc.value.code == "REASON_REQUIRED"
    ps.cancel_transfer(t, actor=pharmacist, note="sent to the wrong store")
    assert _on_hand(batch, main) == 20

    t2 = ps.create_transfer(
        from_store=main, to_store=ward, lines=[(batch.pk, 10)], actor=pharmacist
    )
    ps.send_transfer(t2, actor=pharmacist)
    line_id = t2.lines.get().pk
    with pytest.raises(DomainError) as exc:
        ps.receive_transfer(t2, actor=pharmacist, received={line_id: 7})
    assert exc.value.code == "REASON_REQUIRED"
    with pytest.raises(PermissionRequired):
        ps.receive_transfer(
            t2, actor=pharmacist, received={line_id: 7}, shortage_reason_code="LOST"
        )
    done = ps.receive_transfer(
        t2,
        actor=pharmacist,
        received={line_id: 7},
        shortage_reason_code="LOST",
        shortage_note="box dropped",
        approver=manager,
    )
    assert done.shortage_approved_by == manager
    assert _on_hand(batch, ward) == 7
    assert StockMove.objects.filter(kind="transfer_in", store=ward).count() == 1


def test_low_stock_uses_the_domain_reorder_rule(store) -> None:
    it, _ = _stocked(store, qty=3)
    it.min_stock = D(10)
    it.save()
    (row,) = [r for r in ps.low_stock(store=store) if r.item.pk == it.pk]
    assert row.suggested_order == 17


def test_crediting_the_undispensed_rest_performs_the_line(
    cashier, supervisor, pharmacist, store
) -> None:
    it, _ = _stocked(store)
    line = engine.cash_paid_line(it.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=4)],
    )
    _credit(line, 6, cashier, supervisor)
    line.refresh_from_db()
    assert (line.fulfilment_status, line.performed_quantity) == ("performed", D(4))
    assert not [r for r in ps.dispense_worklist(visit=line.visit) if r.pk == line.pk]
