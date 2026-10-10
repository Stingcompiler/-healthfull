"""Dispense returns (FEATURES 8.4, ADR 0018): units go back into the batch and store they left
through the stock engine, a reason is required, a billed line needs a second person, and the
money stays with the cashier's credit note. Services and the ``/api/pharmacy`` endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import InvoiceLine
from apps.catalog.tests import engine
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.pharmacy import services as ps
from apps.pharmacy.models import Batch, DispenseLine, DispenseReturn, StockBalance, StockMove
from conftest import TEST_PASSWORD, ApiClient
from domain.errors import DomainError

pytestmark = pytest.mark.django_db
D = Decimal


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
    st = b.store(f"PR{b.n()}")
    st.allows_dispense = True
    st.save()
    return st


def _stocked(st, qty: int = 20):
    it = b.item(generic_name=f"Paracetamol {b.n()}")
    batch = Batch.objects.create(
        item=it, batch_no=f"B{b.n()}", expiry_date=date(2030, 1, 1), unit_cost=D("1.0000")
    )
    b.stock_move(batch, st, str(qty))
    return it, batch


def _on_hand(batch, st) -> int:
    return int(StockBalance.objects.get(batch=batch, store=st).qty_base)


def _dispensed_paid(cashier, pharmacist, store, qty: int = 6):
    it, batch = _stocked(store)
    line = engine.cash_paid_line(it.service, qty, cashier, unit_price="50.00")
    ps.dispense(
        visit=line.visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=qty)],
    )
    return line, batch, DispenseLine.objects.get(service_line=line)


def _dispensed_authorized(cashier, pharmacist, store, qty: int = 4):
    """A line given under a perform-first authorization, never billed."""
    it, batch = _stocked(store)
    engine.price_version()
    visit = b.visit()
    [line] = orders.create_service_lines(visit, [{"service": it.service, "quantity": qty}], cashier)
    admin = b.user(is_superuser=True)
    orders.authorize_perform_first([line], actor=admin, reason="EMERGENCY")
    ps.dispense(
        visit=visit,
        store=store,
        actor=pharmacist,
        requests=[ps.DispenseRequest(service_line_id=line.pk, quantity=qty)],
    )
    return line, batch, DispenseLine.objects.get(service_line=line)


# --- services -------------------------------------------------------------------------------


def test_paid_units_come_back_into_their_batch_on_a_second_persons_approval(
    cashier, supervisor, pharmacist, store
) -> None:
    line, batch, dl = _dispensed_paid(cashier, pharmacist, store)
    assert _on_hand(batch, store) == 14
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(dl, quantity=2, actor=pharmacist, reason_code="PATIENT_RETURNED")
    assert exc.value.code == "SECOND_APPROVER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(
            dl, quantity=2, actor=pharmacist, reason_code="PATIENT_RETURNED", approver=pharmacist
        )
    assert exc.value.code == "SECOND_APPROVER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(
            dl, quantity=2, actor=pharmacist, reason_code="PATIENT_RETURNED", approver=cashier
        )
    assert exc.value.code == "APPROVER_NOT_PERMITTED"
    assert _on_hand(batch, store) == 14  # nothing moved
    ret = ps.return_dispense(
        dl,
        quantity=2,
        actor=pharmacist,
        reason_code="PATIENT_RETURNED",
        note="sealed strips",
        approver=supervisor,
    )
    assert ret.approved_by == supervisor
    assert ret.returned_by == pharmacist
    assert ret.reason_code.code == "PATIENT_RETURNED"
    move = StockMove.objects.get(pk=ret.stock_move_id)
    assert (move.kind, move.batch_id, move.store_id, int(move.qty_base)) == (
        "return",
        batch.pk,
        store.pk,
        2,
    )
    assert _on_hand(batch, store) == 16
    # The return never moves money: the line stays paid until the cashier credits it.
    line.refresh_from_db()
    assert line.billing_status == "settled"


def test_unbilled_units_come_back_on_the_actors_reason(cashier, pharmacist, store) -> None:
    line, batch, dl = _dispensed_authorized(cashier, pharmacist, store)
    assert line.billing_status == "unbilled"
    ret = ps.return_dispense(dl, quantity=1, actor=pharmacist, reason_code="DISPENSED_IN_ERROR")
    assert ret.approved_by is None
    assert _on_hand(batch, store) == 17


def test_reason_quantity_and_permission(cashier, supervisor, pharmacist, store) -> None:
    _line, _batch, dl = _dispensed_paid(cashier, pharmacist, store, qty=3)
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(dl, quantity=1, actor=pharmacist, reason_code="", approver=supervisor)
    assert exc.value.code == "REASON_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(
            dl, quantity=1, actor=pharmacist, reason_code="OTHER", approver=supervisor
        )
    assert exc.value.code == "REASON_NOTE_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.return_dispense(
            dl, quantity=4, actor=pharmacist, reason_code="PATIENT_RETURNED", approver=supervisor
        )
    assert exc.value.code == "RETURN_EXCEEDS_DISPENSED"
    with pytest.raises(PermissionRequired):
        ps.return_dispense(
            dl, quantity=1, actor=cashier, reason_code="PATIENT_RETURNED", approver=supervisor
        )
    assert not DispenseReturn.objects.exists()


def test_return_links_the_cashiers_credit_note(cashier, supervisor, pharmacist, store) -> None:
    line, _batch, dl = _dispensed_paid(cashier, pharmacist, store, qty=4)
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    note = billing.create_credit_note(il.invoice, [(il, 2)], actor=cashier, reason="PRICE_ERROR")
    out = billing.approve_credit_note(note, actor=supervisor)
    ret = ps.return_dispense(
        dl,
        quantity=2,
        actor=pharmacist,
        reason_code="PATIENT_RETURNED",
        credit_note=out.credit_note,
        approver=supervisor,
    )
    assert ret.credit_note == out.credit_note


def test_db_refuses_a_self_approved_return(cashier, supervisor, pharmacist, store) -> None:
    _line, _batch, dl = _dispensed_paid(cashier, pharmacist, store, qty=2)
    ret = ps.return_dispense(
        dl, quantity=1, actor=pharmacist, reason_code="PATIENT_RETURNED", approver=supervisor
    )
    # Append-only, and the check repeats the second-person rule.
    b.db_rejects(lambda: DispenseReturn.objects.filter(pk=ret.pk).update(note="x"))
    b.sql_rejects(
        "INSERT INTO pharmacy_dispensereturn (number, dispense_line_id, qty_base, "
        "reason_code_id, note, returned_by_id, approved_by_id, returned_at, stock_move_id) "
        "SELECT 'RTN-X', dispense_line_id, 1, reason_code_id, '', returned_by_id, "
        "returned_by_id, now(), stock_move_id FROM pharmacy_dispensereturn WHERE id = %s",
        [ret.pk],
        "pharmacy_dispensereturn_second_approver",
    )


# --- API ------------------------------------------------------------------------------------


def _client(user: Any) -> ApiClient:
    api = ApiClient()
    assert api.login(user.username).status_code == 200
    return api


def test_returns_screen_and_return_endpoint(cashier, supervisor, pharmacist, store) -> None:
    line, batch, dl = _dispensed_paid(cashier, pharmacist, store, qty=5)
    api = _client(pharmacist)
    page = api.get(f"/api/pharmacy/returns?q={line.visit.patient.file_no}").json()
    assert page["count"] == 1
    row = page["items"][0]["lines"][0]
    assert row["id"] == dl.pk
    assert (row["qty_base"], row["returned"], row["returnable"]) == (5, 0, 5)
    assert row["needs_approver"] is True
    assert row["billing_status"] == "settled"
    path = f"/api/pharmacy/dispense-lines/{dl.pk}/returns"
    r = api.post(path, {"quantity": 2, "reason_code": "PATIENT_RETURNED"})
    assert (r.status_code, r.json()["code"]) == (409, "SECOND_APPROVER_REQUIRED")
    r = api.post(
        path,
        {
            "quantity": 2,
            "reason_code": "PATIENT_RETURNED",
            "approver": {"username": supervisor.username, "password": "wrong"},
        },
    )
    assert (r.status_code, r.json()["code"]) == (409, "APPROVER_INVALID")
    r = api.post(
        path,
        {
            "quantity": 2,
            "reason_code": "PATIENT_RETURNED",
            "note": "unopened",
            "approver": {"username": supervisor.username, "password": TEST_PASSWORD},
        },
    )
    assert r.status_code == 200, r.json()
    out = r.json()["lines"][0]
    assert (out["returned"], out["returnable"]) == (2, 3)
    assert out["returns"][0]["approved_by"]["id"] == supervisor.pk
    assert out["returns"][0]["reason"]["code"] == "PATIENT_RETURNED"
    assert _on_hand(batch, store) == 17
    r = api.post(
        path,
        {
            "quantity": 4,
            "reason_code": "PATIENT_RETURNED",
            "approver": {"username": supervisor.username, "password": TEST_PASSWORD},
        },
    )
    assert (r.status_code, r.json()["code"]) == (409, "RETURN_EXCEEDS_DISPENSED")


def test_recent_dispenses_list_without_a_search(cashier, pharmacist, store) -> None:
    _line, _batch, dl = _dispensed_authorized(cashier, pharmacist, store)
    page = _client(pharmacist).get("/api/pharmacy/returns").json()
    lines = [ln for item in page["items"] for ln in item["lines"]]
    mine = next(ln for ln in lines if ln["id"] == dl.pk)
    assert mine["needs_approver"] is False


@pytest.mark.parametrize(
    "role", ["cashier", "cashier_supervisor", "nurse", "doctor", "receptionist", "manager"]
)
def test_roles_without_dispense_get_403(make_user, cashier, pharmacist, store, role) -> None:
    _line, batch, dl = _dispensed_authorized(cashier, pharmacist, store)
    api = _client(make_user(roles=[role]))
    assert api.get("/api/pharmacy/returns").status_code == 403
    r = api.post(
        f"/api/pharmacy/dispense-lines/{dl.pk}/returns",
        {"quantity": 1, "reason_code": "PATIENT_RETURNED"},
    )
    assert (r.status_code, r.json()["code"]) == (403, "PERMISSION_DENIED")
    assert _on_hand(batch, store) == 16
