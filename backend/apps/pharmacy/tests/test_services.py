"""Pharmacy services: receipts, FEFO dispensing, adjustments, counts, transfers, queries.

Invariant 5 (stock decrements at dispense and never goes negative) is exercised here, including
under concurrent dispensing from separate database connections.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.catalog.tests import engine
from apps.core.tests import builders as b
from apps.orders.models import PerformAuthorization, ServiceLine
from apps.pharmacy import services as ps
from apps.pharmacy.models import (
    Batch,
    Dispense,
    DispenseLine,
    StockBalance,
    StockMove,
    Supplier,
    UnitConversion,
)
from domain import stock as ds
from domain.errors import DomainError
from domain.stock import Pick

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 7)


# --- fixtures and helpers -------------------------------------------------------------------


@pytest.fixture
def pharmacist(make_user):
    return make_user(roles=["pharmacist"])


@pytest.fixture
def manager(make_user):
    return make_user(roles=["manager"])


@pytest.fixture
def store():
    st = b.store("PHARM")
    st.allows_dispense = True
    st.save()
    return st


@pytest.fixture
def item():
    it = b.item(generic_name="Amoxicillin 500")
    UnitConversion.objects.create(
        item=it, unit_code="strip", name_ar="شريط", name_en="strip", factor=10
    )
    UnitConversion.objects.create(
        item=it,
        unit_code="box",
        name_ar="علبة",
        name_en="box",
        factor=30,
        is_dispensable=False,
        is_purchase_unit=True,
    )
    return it


def stock(it, st, qty: int, expiry: date, batch_no: str | None = None) -> Batch:
    batch = Batch.objects.create(
        item=it,
        batch_no=batch_no or f"B{b.n()}",
        expiry_date=expiry,
        unit_cost=Decimal("2.5000"),
    )
    if qty:
        b.stock_move(batch, st, str(qty))
    return batch


def paid_line(visit, it, qty: int, **extra) -> ServiceLine:
    """A drug line of ``qty`` units: settled (default) or invoiced through an approved
    invoice line (``b.billed_line``), or unbilled."""
    status = extra.pop("billing_status", "settled")
    if status == "unbilled":
        return b.service_line(visit, it.service, quantity=Decimal(qty), **extra)
    return b.billed_line(visit, it.service, billing_status=status, quantity=str(qty), **extra)


def balance(batch: Batch, st) -> int:
    row = StockBalance.objects.filter(batch=batch, store=st).first()
    return int(row.qty_base) if row else 0


def req(line: ServiceLine, qty, **kw) -> ps.DispenseRequest:
    return ps.DispenseRequest(service_line_id=line.pk, quantity=qty, **kw)


# --- units ----------------------------------------------------------------------------------


def test_item_factors_and_conversion(item) -> None:
    assert ps.item_factors(item) == {"tablet": 1, "strip": 10, "box": 30}
    assert ps.to_base_units(item, 2, "strip")[0] == 20
    assert ps.to_base_units(item, 3)[0] == 3
    with pytest.raises(DomainError) as exc:
        ps.to_base_units(item, 1, "bottle")
    assert exc.value.code == "UNIT_UNKNOWN"
    with pytest.raises(DomainError) as exc:
        ps.to_base_units(item, 1, "box", dispensing=True)
    assert exc.value.code == "UNIT_NOT_DISPENSABLE"
    for bad in (0, Decimal("1.5"), -2):
        with pytest.raises(DomainError) as exc:
            ps.to_base_units(item, bad)
        assert exc.value.code == "INVALID_QUANTITY"
    UnitConversion.objects.create(
        item=item, unit_code="half", name_ar="نصف", name_en="half", factor=Decimal("0.5")
    )
    with pytest.raises(DomainError) as exc:
        ps.item_factors(item)
    assert exc.value.code == "INVALID_CONVERSION"


# --- goods receipts -------------------------------------------------------------------------


@pytest.fixture
def supplier():
    return Supplier.objects.create(code="SUP1", name_ar="مورد", name_en="Supplier")


def test_goods_receipt_creates_batches_and_stock(pharmacist, supplier, store, item) -> None:
    grn = ps.create_receipt(
        supplier=supplier, store=store, actor=pharmacist, supplier_invoice_no="INV-9"
    )
    assert grn.number.startswith("GRN-")
    ln = ps.add_receipt_line(
        grn,
        item=item,
        batch_no="LOT1",
        expiry_date=date(2028, 1, 1),
        quantity=2,
        unit_code="box",
        unit_cost=Decimal("45.00"),
        actor=pharmacist,
        today=TODAY,
    )
    assert ln.qty_base == 60
    assert ln.unit_cost == Decimal("1.5000")  # per tablet
    assert ln.line_total == Decimal("90.00")
    ps.add_receipt_line(
        grn,
        item=item,
        batch_no="LOT2",
        expiry_date=date(2027, 6, 1),
        quantity=15,
        unit_cost=Decimal("1.20"),
        actor=pharmacist,
        today=TODAY,
    )
    posted = ps.post_receipt(grn, actor=pharmacist, today=TODAY)
    assert posted.status == "posted"
    assert posted.posted_by == pharmacist
    assert posted.total_cost == Decimal("108.00")
    lot1 = Batch.objects.get(item=item, batch_no="LOT1")
    assert lot1.supplier == supplier
    assert lot1.unit_cost == Decimal("1.5000")
    assert balance(lot1, store) == 60
    assert ps.on_hand(item, store) == 75
    moves = StockMove.objects.filter(source_type="receipt_line")
    assert sorted(m.qty_base for m in moves) == [15, 60]
    assert {m.kind for m in moves} == {"receipt"}
    with pytest.raises(DomainError) as exc:
        ps.post_receipt(grn, actor=pharmacist)
    assert exc.value.code == "DOCUMENT_FINAL"

    # The same batch received again later is the same Batch row.
    grn2 = ps.create_receipt(supplier=supplier, store=store, actor=pharmacist)
    ps.add_receipt_line(
        grn2,
        item=item,
        batch_no="LOT1",
        expiry_date=date(2028, 1, 1),
        quantity=10,
        unit_cost=Decimal("1.50"),
        actor=pharmacist,
        today=TODAY,
    )
    ps.post_receipt(grn2, actor=pharmacist, today=TODAY)
    assert balance(lot1, store) == 70
    assert Batch.objects.filter(item=item, batch_no="LOT1").count() == 1


def test_goods_receipt_validation(pharmacist, supplier, store, item) -> None:
    grn = ps.create_receipt(
        supplier=supplier, store=store, actor=pharmacist, supplier_invoice_no="X1"
    )
    with pytest.raises(DomainError) as exc:
        ps.create_receipt(
            supplier=supplier, store=store, actor=pharmacist, supplier_invoice_no="X1"
        )
    assert exc.value.code == "SUPPLIER_INVOICE_DUPLICATE"
    with pytest.raises(DomainError) as exc:
        ps.post_receipt(grn, actor=pharmacist)
    assert exc.value.code == "RECEIPT_EMPTY"
    common = {"item": item, "quantity": 1, "unit_cost": Decimal("1.00"), "actor": pharmacist}
    with pytest.raises(DomainError) as exc:
        ps.add_receipt_line(
            grn, batch_no="OLD", expiry_date=TODAY - timedelta(days=1), today=TODAY, **common
        )
    assert exc.value.code == "BATCH_EXPIRED"
    with pytest.raises(DomainError) as exc:
        ps.add_receipt_line(grn, batch_no=" ", expiry_date=date(2028, 1, 1), **common)
    assert exc.value.code == "BATCH_NO_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.add_receipt_line(
            grn,
            item=item,
            batch_no="L",
            expiry_date=date(2028, 1, 1),
            quantity=1,
            unit_cost=Decimal("-1"),
            actor=pharmacist,
        )
    assert exc.value.code == "INVALID_COST"
    cancelled = ps.cancel_receipt(grn, actor=pharmacist)
    assert cancelled.status == "cancelled"
    with pytest.raises(DomainError) as exc:
        ps.add_receipt_line(grn, batch_no="L", expiry_date=date(2028, 1, 1), **common)
    assert exc.value.code == "DOCUMENT_FINAL"


# --- dispensing: FEFO, partial, overrides ---------------------------------------------------


def test_fefo_dispense_skips_expired_and_empty_batches(pharmacist, store, item) -> None:
    late = stock(item, store, 5, date(2027, 1, 1))
    soon = stock(item, store, 5, date(2026, 12, 1))
    expired = stock(item, store, 100, TODAY - timedelta(days=1))
    empty = stock(item, store, 0, date(2026, 11, 1))
    other_store = b.store()
    stock(item, other_store, 50, date(2026, 10, 30))
    visit = b.visit()
    line = paid_line(visit, item, 20)

    assert ps.suggest_batches(item, store, 7, today=TODAY) == (Pick(soon.pk, 5), Pick(late.pk, 2))
    record = ps.dispense(
        visit=visit, store=store, actor=pharmacist, requests=[req(line, 7)], today=TODAY
    )
    assert record.number.startswith("DSP-")
    rows = list(DispenseLine.objects.filter(dispense=record).order_by("id"))
    assert [(r.batch_id, r.qty_base) for r in rows] == [(soon.pk, 5), (late.pk, 2)]
    assert not any(r.batch_override for r in rows)
    assert [r.stock_move.qty_base for r in rows] == [-5, -2]
    assert {r.stock_move.kind for r in rows} == {"dispense"}
    assert balance(soon, store) == 0
    assert balance(late, store) == 3
    assert balance(expired, store) == 100
    assert balance(empty, store) == 0
    # Partial dispense: the line stays open with the remainder (deferred), in progress.
    line.refresh_from_db()
    assert line.fulfilment_status == "in_progress"
    assert ps.dispensed_quantity(line) == 7
    # Expired stock is never dispensed, even when it is the only stock left.
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit, store=store, actor=pharmacist, requests=[req(line, 4)], today=TODAY
        )
    assert exc.value.code == "STOCK_INSUFFICIENT"


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    batches=st.lists(
        st.tuples(
            st.integers(min_value=-30, max_value=400), st.integers(min_value=0, max_value=40)
        ),
        min_size=1,
        max_size=6,
    ),
    wanted=st.integers(min_value=1, max_value=120),
)
def test_dispense_follows_fefo_and_never_goes_negative(pharmacist, batches, wanted) -> None:
    """Whatever the batches (expired, empty, any expiry), the stored picks are the domain's
    FEFO choice, on-hand drops by exactly what was given, and nothing goes below zero."""
    store_ = b.store()
    store_.allows_dispense = True
    store_.save()
    it = b.item()
    rows = [stock(it, store_, qty, TODAY + timedelta(days=days)) for days, qty in batches]
    before = {r.pk: balance(r, store_) for r in rows}
    visit = b.visit()
    line = paid_line(visit, it, 200)
    snapshot = [ds.BatchStock(r.pk, r.expiry_date, before[r.pk]) for r in rows]
    usable = sum(bs.on_hand for bs in ds.fefo_order(snapshot, TODAY))
    if wanted > usable:
        with pytest.raises(DomainError) as refused:
            ps.dispense(
                visit=visit,
                store=store_,
                actor=pharmacist,
                requests=[req(line, wanted)],
                today=TODAY,
            )
        assert refused.value.code == "STOCK_INSUFFICIENT"
        assert {r.pk: balance(r, store_) for r in rows} == before
        return
    expected = ds.select_batches(snapshot, wanted, TODAY)
    record = ps.dispense(
        visit=visit, store=store_, actor=pharmacist, requests=[req(line, wanted)], today=TODAY
    )
    got = tuple(
        Pick(dl.batch_id, int(dl.qty_base))
        for dl in DispenseLine.objects.filter(dispense=record).order_by("id")
    )
    assert got == expected
    for r in rows:
        taken = sum(p.quantity for p in expected if p.batch_id == r.pk)
        assert balance(r, store_) == before[r.pk] - taken >= 0
        if r.expiry_date < TODAY:
            assert taken == 0


def test_dispense_in_pack_units(pharmacist, store, item) -> None:
    batch = stock(item, store, 40, date(2027, 1, 1))
    visit = b.visit()
    line = paid_line(visit, item, 30)
    ps.dispense(
        visit=visit,
        store=store,
        actor=pharmacist,
        requests=[req(line, 2, unit_code="strip")],
        today=TODAY,
    )
    row = DispenseLine.objects.get(service_line=line)
    assert row.unit is not None
    assert row.unit.unit_code == "strip"
    assert row.quantity_units == 2
    assert row.qty_base == 20
    assert balance(batch, store) == 20
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit,
            store=store,
            actor=pharmacist,
            requests=[req(line, 1, unit_code="box")],
            today=TODAY,
        )
    assert exc.value.code == "UNIT_NOT_DISPENSABLE"


def test_split_across_batches_in_pack_units_records_base_units(pharmacist, store, item) -> None:
    first = stock(item, store, 15, date(2026, 12, 1))
    stock(item, store, 50, date(2027, 6, 1))
    visit = b.visit()
    line = paid_line(visit, item, 30)
    ps.dispense(
        visit=visit,
        store=store,
        actor=pharmacist,
        requests=[req(line, 2, unit_code="strip")],
        today=TODAY,
    )
    rows = list(DispenseLine.objects.filter(service_line=line).order_by("id"))
    assert [(r.batch_id == first.pk, r.qty_base, r.quantity_units) for r in rows] == [
        (True, 15, 15),
        (False, 5, 5),
    ]
    assert [r.unit for r in rows] == [None, None]


def test_batch_override_needs_reason_and_permission(pharmacist, store, item, make_user) -> None:
    soon = stock(item, store, 10, date(2026, 12, 1))
    late = stock(item, store, 10, date(2027, 6, 1))
    expired = stock(item, store, 10, TODAY - timedelta(days=3))
    visit = b.visit()
    line = paid_line(visit, item, 30)
    choice = [ps.BatchPick(late.pk, 3)]
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit,
            store=store,
            actor=pharmacist,
            requests=[req(line, 3, batches=choice)],
            today=TODAY,
        )
    assert exc.value.code == "REASON_REQUIRED"
    nurse = make_user(roles=["nurse"])
    with pytest.raises(PermissionDenied):
        ps.dispense(
            visit=visit,
            store=store,
            actor=nurse,
            requests=[req(line, 3, batches=choice, override_reason_code="BATCH_CHOICE")],
            today=TODAY,
        )
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit,
            store=store,
            actor=pharmacist,
            requests=[
                req(
                    line,
                    3,
                    batches=[ps.BatchPick(expired.pk, 3)],
                    override_reason_code="BATCH_CHOICE",
                )
            ],
            today=TODAY,
        )
    assert exc.value.code == "BATCH_EXPIRED"
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit,
            store=store,
            actor=pharmacist,
            requests=[
                req(
                    line, 3, batches=[ps.BatchPick(late.pk, 2)], override_reason_code="BATCH_CHOICE"
                )
            ],
            today=TODAY,
        )
    assert exc.value.code == "OVERRIDE_QUANTITY_MISMATCH"

    ps.dispense(
        visit=visit,
        store=store,
        actor=pharmacist,
        requests=[
            req(
                line,
                3,
                batches=choice,
                override_reason_code="BATCH_CHOICE",
                override_note="patient asked for this lot",
            )
        ],
        today=TODAY,
    )
    row = DispenseLine.objects.get(service_line=line)
    assert row.batch_override
    assert row.override_reason is not None
    assert row.override_reason.code == "BATCH_CHOICE"
    assert row.override_note == "patient asked for this lot"
    assert balance(late, store) == 7
    assert balance(soon, store) == 10
    # Picking exactly the FEFO suggestion is not an override.
    ps.dispense(
        visit=visit,
        store=store,
        actor=pharmacist,
        requests=[req(line, 2, batches=[ps.BatchPick(soon.pk, 2)])],
        today=TODAY,
    )
    assert not DispenseLine.objects.filter(service_line=line, batch=soon).get().batch_override


def test_only_paid_or_authorized_lines_are_dispensed(pharmacist, store, item) -> None:
    stock(item, store, 100, date(2027, 1, 1))
    visit = b.visit()
    unpaid = paid_line(visit, item, 5, billing_status="unbilled")
    invoiced = paid_line(visit, item, 5, billing_status="invoiced")
    for line in (unpaid, invoiced):
        with pytest.raises(DomainError) as exc:
            ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 1)])
        assert exc.value.code == "LINE_NOT_ELIGIBLE"
    auth = PerformAuthorization.objects.create(
        visit=visit,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=pharmacist,
        authorized_at=timezone.now(),
    )
    authorized = paid_line(visit, item, 5, billing_status="unbilled", authorization=auth)
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(authorized, 1)])
    PerformAuthorization.objects.filter(pk=auth.pk).update(
        revoked_at=timezone.now(), revoked_by=pharmacist
    )
    with pytest.raises(DomainError) as exc:
        ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(authorized, 1)])
    assert exc.value.code == "LINE_NOT_ELIGIBLE"
    cancelled = paid_line(
        visit,
        item,
        5,
        billing_status="unbilled",
        fulfilment_status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=pharmacist,
        cancel_reason=b.reason("line_cancel"),
    )
    with pytest.raises(DomainError) as exc:
        ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(cancelled, 1)])
    assert exc.value.code == "LINE_NOT_ELIGIBLE"


def test_dispense_refusals(pharmacist, store, item) -> None:
    stock(item, store, 100, date(2027, 1, 1))
    visit = b.visit()
    line = paid_line(visit, item, 10)
    lab_line = b.billed_line(visit, b.service("lab"))
    other_visit_line = paid_line(b.visit(), item, 10)
    unstocked = b.billed_line(visit, b.service("drug"))
    cases = [
        ([req(lab_line, 1)], "LINE_NOT_DISPENSABLE"),
        ([req(other_visit_line, 1)], "LINE_NOT_ON_VISIT"),
        ([req(unstocked, 1)], "ITEM_NOT_STOCKED"),
        ([req(line, 11)], "DISPENSE_EXCEEDS_LINE"),
        ([req(line, 1), req(line, 1)], "DUPLICATE_LINE"),
        ([], "DISPENSE_EMPTY"),
        ([req(line, 0)], "INVALID_QUANTITY"),
    ]
    for requests, code in cases:
        with pytest.raises(DomainError) as exc:
            ps.dispense(visit=visit, store=store, actor=pharmacist, requests=requests)
        assert exc.value.code == code, code
    closed = b.store()
    with pytest.raises(DomainError) as exc:
        ps.dispense(visit=visit, store=closed, actor=pharmacist, requests=[req(line, 1)])
    assert exc.value.code == "STORE_CANNOT_DISPENSE"
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 7)])
    with pytest.raises(DomainError) as exc:
        ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 4)])
    assert exc.value.code == "DISPENSE_EXCEEDS_LINE"
    assert exc.value.details["remaining"] == 3


def test_failed_dispense_writes_nothing(pharmacist, store, item) -> None:
    batch = stock(item, store, 6, date(2027, 1, 1))
    other = b.item()
    stock(other, store, 1, date(2027, 1, 1))
    visit = b.visit()
    first = paid_line(visit, item, 10)
    second = paid_line(visit, other, 10)
    with pytest.raises(DomainError) as exc:
        ps.dispense(
            visit=visit, store=store, actor=pharmacist, requests=[req(first, 5), req(second, 2)]
        )
    assert exc.value.code == "STOCK_INSUFFICIENT"
    assert balance(batch, store) == 6
    assert not Dispense.objects.exists()
    assert not StockMove.objects.filter(kind="dispense").exists()


def test_two_lines_of_one_item_share_the_stock(pharmacist, store, item) -> None:
    stock(item, store, 10, date(2027, 1, 1))
    visit = b.visit()
    a, c = paid_line(visit, item, 8), paid_line(visit, item, 8)
    with pytest.raises(DomainError) as exc:
        ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(a, 6), req(c, 6)])
    assert exc.value.code == "STOCK_INSUFFICIENT"
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(a, 6), req(c, 4)])
    assert ps.on_hand(item, store) == 0


def test_dispense_worklist(pharmacist, store, item) -> None:
    stock(item, store, 100, date(2027, 1, 1))
    visit = b.visit()
    paid = paid_line(visit, item, 10)
    paid_line(visit, item, 10, billing_status="unbilled")
    b.billed_line(visit, b.service("lab"))
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(paid, 4)])
    rows = list(ps.dispense_worklist(visit=visit))
    assert [r.pk for r in rows] == [paid.pk]
    assert rows[0].remaining == 6  # type: ignore[attr-defined]


def test_full_dispense_performs_the_line(pharmacist, store, item) -> None:
    stock(item, store, 50, date(2027, 1, 1))
    visit = b.visit()
    line = paid_line(visit, item, 10)
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 4)], today=TODAY)
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 6)], today=TODAY)
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.performed_by == pharmacist
    assert ps.on_hand(item, store) == 40
    assert not list(ps.dispense_worklist(visit=visit))


def test_partial_dispense_closed_with_the_remainder_credited(
    make_user, pharmacist, store, item
) -> None:
    from apps.billing.models import CreditNoteLine

    stock(item, store, 4, date(2027, 1, 1))
    line = engine.settled_line(item.service, 10, pharmacist)
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        approver=make_user(roles=["cashier_supervisor"]),
        requests=[req(line, 4, complete=True)],
        today=TODAY,
    )
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.performed_quantity == 4
    assert line.cancel_reason is not None
    assert line.cancel_reason.code == "OUT_OF_STOCK"
    credit = CreditNoteLine.objects.get(invoice_line__service_line=line)
    assert credit.quantity == 6
    assert credit.credit_note.status == "approved"
    assert ps.on_hand(item, store) == 0


def test_dispense_of_an_engine_settled_line_performs_it(pharmacist, store, item) -> None:
    stock(item, store, 30, date(2027, 1, 1))
    line = engine.settled_line(item.service, 10, pharmacist)
    ps.dispense(
        visit=line.visit, store=store, actor=pharmacist, requests=[req(line, 10)], today=TODAY
    )
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert ps.on_hand(item, store) == 20


def test_out_of_stock_remainder_of_a_paid_line_is_refundable(make_user, pharmacist, store, item):
    from apps.payments import services as payments
    from apps.payments.models import Refund

    cashier = make_user(roles=["cashier"])
    stock(item, store, 4, date(2027, 1, 1))
    line = engine.cash_paid_line(item.service, 10, cashier, unit_price="10.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        approver=make_user(roles=["cashier_supervisor"]),
        requests=[req(line, 4, complete=True)],
        today=TODAY,
    )
    patient = line.visit.patient
    assert payments.credit_balance(patient) == Decimal("60.00")
    assert Refund.objects.get(patient=patient).amount == Decimal("60.00")


# --- adjustments ----------------------------------------------------------------------------


def test_adjustment_needs_supervisor_approval(pharmacist, manager, store, item) -> None:
    batch = stock(item, store, 10, date(2027, 1, 1))
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store, reason_code="OTHER", lines=[(batch.pk, -2, "")], actor=pharmacist
        )
    assert exc.value.code == "REASON_NOTE_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store, reason_code="NOPE", lines=[(batch.pk, -2, "")], actor=pharmacist
        )
    assert exc.value.code == "REASON_UNKNOWN"
    adj = ps.request_adjustment(
        store=store, reason_code="DAMAGED", lines=[(batch.pk, -3, "broken")], actor=pharmacist
    )
    assert balance(batch, store) == 10  # nothing moves before approval
    with pytest.raises(PermissionDenied):
        ps.approve_adjustment(adj, actor=pharmacist)
    approved = ps.approve_adjustment(adj, actor=manager, note="checked")
    assert approved.status == "approved"
    assert approved.decided_by == manager
    assert balance(batch, store) == 7
    move = StockMove.objects.get(source_type="adjustment", source_id=adj.pk)
    assert (move.kind, move.qty_base) == ("adjustment", -3)
    with pytest.raises(DomainError) as exc:
        ps.approve_adjustment(adj, actor=manager)
    assert exc.value.code == "DOCUMENT_FINAL"


def test_adjustment_never_below_zero_and_no_self_approval(
    pharmacist, manager, store, item, make_user
) -> None:
    batch = stock(item, store, 2, date(2027, 1, 1))
    adj = ps.request_adjustment(
        store=store, reason_code="LOST", lines=[(batch.pk, -5, "")], actor=pharmacist
    )
    with pytest.raises(DomainError) as exc:
        ps.approve_adjustment(adj, actor=manager)
    assert exc.value.code == "STOCK_INSUFFICIENT"
    assert balance(batch, store) == 2
    own = ps.request_adjustment(
        store=store, reason_code="OPENING_BALANCE", lines=[(batch.pk, 8, "")], actor=manager
    )
    with pytest.raises(DomainError) as exc:
        ps.approve_adjustment(own, actor=manager)
    assert exc.value.code == "SELF_APPROVAL"
    ps.approve_adjustment(own, actor=make_user(roles=["admin"]))
    assert balance(batch, store) == 10
    with pytest.raises(DomainError) as exc:
        ps.reject_adjustment(adj, actor=manager, note=" ")
    assert exc.value.code == "REASON_REQUIRED"
    rejected = ps.reject_adjustment(adj, actor=manager, note="count it again")
    assert rejected.status == "rejected"
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store,
            reason_code="DAMAGED",
            lines=[(batch.pk, 1, ""), (batch.pk, 2, "")],
            actor=pharmacist,
        )
    assert exc.value.code == "DUPLICATE_BATCH"
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store, reason_code="DAMAGED", lines=[(batch.pk, 0, "")], actor=pharmacist
        )
    assert exc.value.code == "MOVE_SIGN_INVALID"


# --- counts ---------------------------------------------------------------------------------


def test_count_session_posts_variances(pharmacist, manager, store, item) -> None:
    a = stock(item, store, 10, date(2027, 1, 1))
    c = stock(item, store, 4, date(2027, 2, 1))
    stock(item, store, 0, date(2027, 3, 1))  # no stock: not in the snapshot
    count = ps.start_count(store, actor=pharmacist)
    assert sorted((ln.batch_id, int(ln.book_qty)) for ln in count.lines.all()) == [
        (a.pk, 10),
        (c.pk, 4),
    ]
    with pytest.raises(DomainError) as exc:
        ps.start_count(store, actor=pharmacist)
    assert exc.value.code == "COUNT_ALREADY_OPEN"
    ps.record_count(count, batch=a, counted_qty=8, actor=pharmacist)
    with pytest.raises(DomainError) as exc:
        ps.post_count(count, actor=manager)
    assert exc.value.code == "COUNT_INCOMPLETE"
    ps.record_count(count, batch=c, counted_qty=5, actor=pharmacist)
    found = Batch.objects.create(
        item=item, batch_no="FOUND", expiry_date=date(2027, 4, 1), unit_cost=Decimal("3.0000")
    )
    ps.record_count(count, batch=found, counted_qty=2, actor=pharmacist)
    report = {v.line.batch_id: (v.variance, v.value) for v in ps.count_variances(count)}
    assert report == {
        a.pk: (-2, Decimal("-5.00")),
        c.pk: (1, Decimal("2.50")),
        found.pk: (2, Decimal("6.00")),
    }
    with pytest.raises(PermissionDenied):
        ps.post_count(count, actor=pharmacist)
    posted = ps.post_count(count, actor=manager)
    assert posted.status == "posted"
    assert (balance(a, store), balance(c, store), balance(found, store)) == (8, 5, 2)
    kinds = set(StockMove.objects.filter(source_type="count").values_list("kind", flat=True))
    assert kinds == {"count_correction"}
    with pytest.raises(DomainError) as exc:
        ps.record_count(count, batch=a, counted_qty=1, actor=pharmacist)
    assert exc.value.code == "DOCUMENT_FINAL"
    again = ps.start_count(store, actor=pharmacist, items=[item])
    assert ps.cancel_count(again, actor=pharmacist).status == "cancelled"


def test_count_refuses_stock_that_moved_after_counting(pharmacist, manager, store, item) -> None:
    batch = stock(item, store, 10, date(2027, 1, 1))
    count = ps.start_count(store, actor=pharmacist)
    # A dispense before the batch is counted: the book follows it (no false variance).
    visit = b.visit()
    ps.dispense(
        visit=visit, store=store, actor=pharmacist, requests=[req(paid_line(visit, item, 5), 2)]
    )
    line = ps.record_count(count, batch=batch, counted_qty=8, actor=pharmacist)
    assert line.book_qty == 8
    # A dispense after counting: posting is refused until the batch is counted again.
    ps.dispense(
        visit=visit, store=store, actor=pharmacist, requests=[req(paid_line(visit, item, 5), 1)]
    )
    with pytest.raises(DomainError) as exc:
        ps.post_count(count, actor=manager)
    assert exc.value.code == "COUNT_STOCK_MOVED"
    assert exc.value.details["batches"] == [batch.pk]
    ps.record_count(count, batch=batch, counted_qty=6, actor=pharmacist)
    ps.post_count(count, actor=manager)
    assert balance(batch, store) == 6


# --- transfers ------------------------------------------------------------------------------


def test_transfer_between_stores(pharmacist, store, item) -> None:
    main = b.store("MAIN")
    batch = stock(item, main, 20, date(2027, 1, 1))
    with pytest.raises(DomainError) as exc:
        ps.create_transfer(from_store=main, to_store=main, lines=[(batch.pk, 1)], actor=pharmacist)
    assert exc.value.code == "TRANSFER_SAME_STORE"
    too_much = ps.create_transfer(
        from_store=main, to_store=store, lines=[(batch.pk, 25)], actor=pharmacist
    )
    with pytest.raises(DomainError) as exc:
        ps.send_transfer(too_much, actor=pharmacist)
    assert exc.value.code == "STOCK_INSUFFICIENT"
    ps.cancel_transfer(too_much, actor=pharmacist)
    t = ps.create_transfer(
        from_store=main, to_store=store, lines=[(batch.pk, 12)], actor=pharmacist
    )
    with pytest.raises(DomainError) as exc:
        ps.receive_transfer(t, actor=pharmacist)
    assert exc.value.code == "TRANSFER_NOT_SENT"
    ps.send_transfer(t, actor=pharmacist)
    assert balance(batch, main) == 8
    assert balance(batch, store) == 0  # in transit
    received = ps.receive_transfer(t, actor=pharmacist)
    assert received.status == "received"
    assert balance(batch, store) == 12
    assert (
        sum(StockMove.objects.filter(source_type="transfer").values_list("qty_base", flat=True))
        == 0
    )
    with pytest.raises(DomainError) as exc:
        ps.cancel_transfer(t, actor=pharmacist)
    assert exc.value.code == "DOCUMENT_FINAL"


# --- item master ----------------------------------------------------------------------------


def test_item_master(pharmacist) -> None:
    with pytest.raises(DomainError) as exc:
        ps.create_item(
            service=b.service("lab"),
            generic_name="X",
            base_unit_code="tablet",
            base_unit_name_ar="حبة",
            base_unit_name_en="tablet",
            actor=pharmacist,
        )
    assert exc.value.code == "SERVICE_NOT_STOCKABLE"
    svc = b.service("drug")
    it = ps.create_item(
        service=svc,
        generic_name=" Metformin ",
        base_unit_code="tablet",
        base_unit_name_ar="حبة",
        base_unit_name_en="tablet",
        actor=pharmacist,
        strength="500 mg",
        min_stock=Decimal(100),
    )
    assert (it.generic_name, it.strength) == ("Metformin", "500 mg")
    with pytest.raises(DomainError) as exc:
        ps.create_item(
            service=svc,
            generic_name="Again",
            base_unit_code="tablet",
            base_unit_name_ar="حبة",
            base_unit_name_en="tablet",
            actor=pharmacist,
        )
    assert exc.value.code == "ITEM_EXISTS"
    ps.add_unit(it, unit_code="strip", name_ar="شريط", name_en="strip", factor=10, actor=pharmacist)
    ps.add_unit(it, unit_code="box", name_ar="علبة", name_en="box", factor=100, actor=pharmacist)
    assert ps.item_factors(it) == {"tablet": 1, "strip": 10, "box": 100}
    for code, factor, err in [
        ("tablet", 5, "INVALID_CONVERSION"),
        ("strip", 5, "INVALID_CONVERSION"),
        ("pack", 1, "INVALID_QUANTITY"),
    ]:
        with pytest.raises(DomainError) as exc:
            ps.add_unit(
                it, unit_code=code, name_ar="x", name_en="x", factor=factor, actor=pharmacist
            )
        assert exc.value.code == err


def test_low_stock_notifies_pharmacists(pharmacist, store, make_user) -> None:
    from apps.core.models import Notification

    other = make_user(roles=["pharmacist"])
    it = b.item(min_stock=Decimal(5))
    stock(it, store, 8, date(2027, 1, 1))
    visit = b.visit()
    line = paid_line(visit, it, 10)
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 2)])
    assert not Notification.objects.filter(kind="stock_low").exists()  # 6 > 5
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 1)])
    notified = set(Notification.objects.filter(kind="stock_low").values_list("user_id", flat=True))
    assert notified == {pharmacist.pk, other.pk}
    assert (
        Notification.objects.filter(kind="stock_low").values_list("payload", flat=True)[0][
            "on_hand"
        ]
        == 5
    )
    ps.dispense(visit=visit, store=store, actor=pharmacist, requests=[req(line, 1)])
    assert Notification.objects.filter(kind="stock_low").count() == 2  # once per crossing


# --- queries --------------------------------------------------------------------------------


def test_expiry_and_low_stock_reports(store, item) -> None:
    today = timezone.localdate()
    soon = stock(item, store, 5, today + timedelta(days=20))
    mid = stock(item, store, 5, today + timedelta(days=50))
    stock(item, store, 5, today + timedelta(days=200))
    gone = stock(item, store, 3, today - timedelta(days=2))
    stock(item, store, 0, today + timedelta(days=10))
    assert [e.batch for e in ps.expiring_batches(days=30, store=store)] == [gone, soon]
    sixty = ps.expiring_batches(days=60)
    assert [e.batch for e in sixty] == [gone, soon, mid]
    assert sixty[1].days_left == 20
    assert sixty[0].days_left == -2

    item.min_stock = Decimal(20)
    item.save()
    plenty = b.item(min_stock=Decimal(5), reorder_qty=Decimal(50))
    stock(plenty, store, 30, today + timedelta(days=300))
    scarce = b.item(min_stock=Decimal(10), reorder_qty=Decimal(100))
    low = {row.item.pk: row for row in ps.low_stock(store=store)}
    assert set(low) == {item.pk, scarce.pk}
    assert (low[item.pk].on_hand, low[item.pk].suggested_order) == (18, 22)
    assert (low[scarce.pk].on_hand, low[scarce.pk].suggested_order) == (0, 100)
    assert ps.on_hand(item) == 18


# --- concurrency (invariant 5 under load) ---------------------------------------------------


def _run_threads(work, args_list):
    barrier = threading.Barrier(len(args_list))
    results: list[str] = []
    lock = threading.Lock()

    def runner(args):
        try:
            barrier.wait(timeout=10)
            work(*args)
            outcome = "ok"
        except DomainError as exc:
            outcome = exc.code
        except Exception as exc:
            outcome = f"{type(exc).__name__}: {exc}"
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=runner, args=(a,)) for a in args_list]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


@pytest.mark.django_db(transaction=True)
def test_concurrent_dispense_never_goes_negative(make_user) -> None:
    pharmacist = make_user(roles=["pharmacist"])
    st = b.store("CONC")
    st.allows_dispense = True
    st.save()
    it = b.item()
    batch = stock(it, st, 10, date(2027, 1, 1))
    lines = [paid_line(b.visit(), it, 20) for _ in range(6)]

    def work(line):
        ps.dispense(
            visit=line.visit, store=st, actor=pharmacist, requests=[req(line, 4)], today=TODAY
        )

    results = _run_threads(work, [(ln,) for ln in lines])
    assert sorted(results) == ["STOCK_INSUFFICIENT"] * 4 + ["ok"] * 2, results
    assert balance(batch, st) == 2
    moves = StockMove.objects.filter(kind="dispense", batch=batch)
    assert sum(m.qty_base for m in moves) == -8
    assert DispenseLine.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_dispense_of_one_line_never_exceeds_it(make_user) -> None:
    pharmacist = make_user(roles=["pharmacist"])
    st = b.store("CONC2")
    st.allows_dispense = True
    st.save()
    it = b.item()
    stock(it, st, 100, date(2027, 1, 1))
    line = paid_line(b.visit(), it, 10)

    def work():
        ps.dispense(
            visit=line.visit, store=st, actor=pharmacist, requests=[req(line, 6)], today=TODAY
        )

    results = _run_threads(work, [(), (), ()])
    assert sorted(results) == ["DISPENSE_EXCEEDS_LINE"] * 2 + ["ok"], results
    assert ps.dispensed_quantity(line) == 6
    assert ps.on_hand(it, st) == 94


def test_database_refuses_negative_stock_even_without_services(store, item) -> None:
    batch = stock(item, store, 3, date(2027, 1, 1))
    b.db_rejects(
        lambda: b.stock_move(batch, store, "-4", kind="dispense"),
        "pharmacy_balance_never_negative",
    )
    assert balance(batch, store) == 3
