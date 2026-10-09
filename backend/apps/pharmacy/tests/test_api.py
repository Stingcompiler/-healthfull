"""``/api/pharmacy`` contract: every endpoint's happy path, its domain error codes, and the
permission each one requires (generated over the OpenAPI schema for every probe role).

The stock and money rules behind the endpoints are tested in ``test_services.py`` and
``test_module_services.py``; this file proves the routes reach them with the right shapes.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.billing.models import CreditNoteLine, Invoice
from apps.catalog.tests import engine
from apps.core.models import User
from apps.core.permissions import effective_permissions
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients.tests.test_contract import assert_role_less_user_is_refused, module_operations
from apps.payments.tests import api_kit as kit
from apps.payments.tests.test_permission_matrix import _request, _required_permissions, _schema
from apps.pharmacy.models import (
    Batch,
    Item,
    StockBalance,
    StockMove,
    Store,
    Supplier,
    UnitConversion,
)
from conftest import TEST_PASSWORD, ApiClient

pytestmark = pytest.mark.django_db

PREFIX = "/api/pharmacy"

#: The module's operations; a removed or renamed route fails here.
OPERATIONS = {
    ("get", "/api/pharmacy/ping"): "pharmacy_get_ping",
    ("get", "/api/pharmacy/options"): "pharmacy_get_options",
    ("get", "/api/pharmacy/suppliers"): "pharmacy_list_suppliers",
    ("post", "/api/pharmacy/suppliers"): "pharmacy_create_supplier",
    ("get", "/api/pharmacy/stores/{store_id}/batches"): "pharmacy_list_store_batches",
    ("get", "/api/pharmacy/items"): "pharmacy_list_items",
    ("post", "/api/pharmacy/items"): "pharmacy_create_item",
    ("get", "/api/pharmacy/items/scan"): "pharmacy_scan_barcode",
    ("get", "/api/pharmacy/items/services"): "pharmacy_list_stock_services",
    ("get", "/api/pharmacy/items/{item_id}"): "pharmacy_get_item",
    ("patch", "/api/pharmacy/items/{item_id}"): "pharmacy_update_item",
    ("post", "/api/pharmacy/items/{item_id}/units"): "pharmacy_add_unit",
    ("patch", "/api/pharmacy/items/{item_id}/units/{unit_id}"): "pharmacy_update_unit",
    ("get", "/api/pharmacy/items/{item_id}/stock-card"): "pharmacy_get_stock_card",
    ("get", "/api/pharmacy/queue"): "pharmacy_list_queue",
    ("get", "/api/pharmacy/queue/visits/{visit_id}"): "pharmacy_get_dispense_visit",
    ("post", "/api/pharmacy/dispenses"): "pharmacy_create_dispense",
    ("get", "/api/pharmacy/dispenses/{dispense_id}"): "pharmacy_get_dispense",
    ("get", "/api/pharmacy/receipts"): "pharmacy_list_receipts",
    ("post", "/api/pharmacy/receipts"): "pharmacy_create_receipt",
    ("get", "/api/pharmacy/receipts/{receipt_id}"): "pharmacy_get_receipt",
    ("post", "/api/pharmacy/receipts/{receipt_id}/post"): "pharmacy_post_receipt",
    ("post", "/api/pharmacy/receipts/{receipt_id}/cancel"): "pharmacy_cancel_receipt",
    ("get", "/api/pharmacy/adjustments"): "pharmacy_list_adjustments",
    ("post", "/api/pharmacy/adjustments"): "pharmacy_request_adjustment",
    ("get", "/api/pharmacy/adjustments/{adjustment_id}"): "pharmacy_get_adjustment",
    ("post", "/api/pharmacy/adjustments/{adjustment_id}/approve"): "pharmacy_approve_adjustment",
    ("post", "/api/pharmacy/adjustments/{adjustment_id}/reject"): "pharmacy_reject_adjustment",
    ("get", "/api/pharmacy/counts"): "pharmacy_list_counts",
    ("post", "/api/pharmacy/counts"): "pharmacy_start_count",
    ("get", "/api/pharmacy/counts/{count_id}"): "pharmacy_get_count",
    ("post", "/api/pharmacy/counts/{count_id}/record"): "pharmacy_record_count",
    ("post", "/api/pharmacy/counts/{count_id}/post"): "pharmacy_post_count",
    ("post", "/api/pharmacy/counts/{count_id}/cancel"): "pharmacy_cancel_count",
    ("get", "/api/pharmacy/transfers"): "pharmacy_list_transfers",
    ("post", "/api/pharmacy/transfers"): "pharmacy_create_transfer",
    ("get", "/api/pharmacy/transfers/{transfer_id}"): "pharmacy_get_transfer",
    ("post", "/api/pharmacy/transfers/{transfer_id}/send"): "pharmacy_send_transfer",
    ("post", "/api/pharmacy/transfers/{transfer_id}/receive"): "pharmacy_receive_transfer",
    ("post", "/api/pharmacy/transfers/{transfer_id}/cancel"): "pharmacy_cancel_transfer",
    ("get", "/api/pharmacy/reports/expiry"): "pharmacy_get_expiry_report",
    ("get", "/api/pharmacy/reports/low-stock"): "pharmacy_get_low_stock",
    ("get", "/api/pharmacy/sale/customers"): "pharmacy_list_sale_customers",
    ("get", "/api/pharmacy/sale/services"): "pharmacy_list_sale_services",
    ("post", "/api/pharmacy/sales"): "pharmacy_create_sale",
}

#: Roles probed against every operation: none of them may use an operation whose code they
#: lack. Doctors, nurses, receptionists and lab staff hold no pharmacy code at all; cashiers
#: only the walk-in sale; managers approve but never dispense.
PROBE_ROLES = ("doctor", "nurse", "receptionist", "lab_tech", "cashier", "manager", "pharmacist")


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.content
    return response.json()


def error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return dict(body)


# --- contract -------------------------------------------------------------------------------


def test_operations_are_pinned() -> None:
    assert module_operations(PREFIX) == OPERATIONS


def test_every_operation_refuses_a_user_without_the_permission(
    make_user: Any, api_client: ApiClient
) -> None:
    make_user("nobody")
    assert api_client.login("nobody").status_code == 200
    assert_role_less_user_is_refused(api_client, OPERATIONS, open_ops={"pharmacy_get_ping"})


def test_every_operation_refuses_each_role_without_its_code(make_user: Any) -> None:
    schema = _schema()
    required = _required_permissions()
    ops = [
        (path, method, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if path.startswith(f"{PREFIX}/") and not path.endswith("/ping")
    ]
    missing = [op["operationId"] for _, _, op in ops if op["operationId"] not in required]
    assert missing == []
    probes = {role: kit.actor(make_user, f"probe_{role}", role) for role in PROBE_ROLES}
    held = {
        role: effective_permissions(User.objects.get(pk=p.user.pk)) for role, p in probes.items()
    }
    refused: set[tuple[str, str]] = set()
    for path, method, op in ops:
        code = required[op["operationId"]]
        assert code.startswith(("pharmacy.", "billing.pharmacy_sale")), (op["operationId"], code)
        url, body = _request(schema, path, op)
        for role, probe in probes.items():
            if code in held[role]:
                continue
            response = probe.api.request(method.upper(), url, body)
            assert response.status_code == 403, (op["operationId"], role, response.content)
            assert response.json()["details"]["permission"] == code
            refused.add((op["operationId"], role))
    every = {op["operationId"] for _, _, op in ops}
    # Doctors, nurses and receptionists never reach any pharmacy operation.
    for role in ("doctor", "nurse", "receptionist"):
        assert {op_id for op_id, r in refused if r == role} == every, role
    # A manager approves adjustments and posts counts but never dispenses.
    assert ("pharmacy_create_dispense", "manager") in refused
    assert ("pharmacy_approve_adjustment", "pharmacist") in refused
    assert ("pharmacy_post_count", "pharmacist") in refused


# --- set-up ---------------------------------------------------------------------------------


class Ph:
    """A pharmacy with a dispensing store, the main store and an amoxicillin item."""

    def __init__(self, make_user: Any) -> None:
        self.pharmacist = kit.actor(make_user, "pharm", "pharmacist")
        self.pharmacist2 = kit.actor(make_user, "pharm2", "pharmacist")
        self.manager = kit.actor(make_user, "mgr", "manager")
        self.sup = kit.actor(make_user, "sup", "cashier_supervisor")
        self.doctor = kit.actor(make_user, "doc", "doctor")
        self.store = b.store("PHA")
        self.store.allows_dispense = True
        self.store.save()
        self.main = b.store("MAIN")
        self.supplier = Supplier.objects.create(code="SUP", name_ar="مورد", name_en="Supplier")
        self.item = b.item(generic_name="Amoxicillin", strength="500 mg", min_stock=Decimal(20))
        UnitConversion.objects.create(
            item=self.item, unit_code="strip", name_ar="شريط", name_en="strip", factor=10
        )

    @property
    def api(self) -> ApiClient:
        return self.pharmacist.api

    def batch(self, qty: int, days: int, store: Store | None = None, no: str = "") -> Batch:
        batch = Batch.objects.create(
            item=self.item,
            batch_no=no or f"B{b.n()}",
            expiry_date=timezone.localdate() + timedelta(days=days),
            unit_cost=Decimal("2.5000"),
        )
        if qty:
            b.stock_move(batch, store or self.store, str(qty))
        return batch

    def paid_line(self, qty: int) -> ServiceLine:
        return engine.settled_line(self.item.service, qty, self.pharmacist.user)


@pytest.fixture
def ph(make_user: Any) -> Ph:
    return Ph(make_user)


def _balance(batch: Batch, store: Store) -> int:
    row = StockBalance.objects.filter(batch=batch, store=store).first()
    return int(row.qty_base) if row else 0


# --- reference and items --------------------------------------------------------------------


def test_options_list_stores_reasons_and_policy(ph: Ph) -> None:
    body = ok(ph.api.get("/api/pharmacy/options"))
    assert [s["code"] for s in body["stores"]] == ["MAIN", "PHA"]
    assert body["default_store_id"] == ph.store.pk
    assert "BATCH_CHOICE" in {r["code"] for r in body["reasons_override"]}
    assert "DAMAGED" in {r["code"] for r in body["reasons_stock_adjust"]}
    assert "OUT_OF_STOCK" in {r["code"] for r in body["reasons_line_cancel"]}
    assert body["partial_dispense_remainder"] == "defer"
    assert body["suppliers"][0]["code"] == "SUP"


def test_item_master_create_edit_units_scan_and_search(ph: Ph) -> None:
    svc = b.service(kind="drug", code="DRG-NEW")
    services = ok(ph.api.get("/api/pharmacy/items/services"))
    assert "DRG-NEW" in {s["code"] for s in services}
    created = ok(
        ph.api.post(
            "/api/pharmacy/items",
            {
                "service_id": svc.pk,
                "generic_name": "Cetirizine",
                "form": "tablet",
                "strength": "10 mg",
                "base_unit_code": "tablet",
                "base_unit_name_ar": "حبة",
                "base_unit_name_en": "tablet",
                "barcode": "625100",
                "min_stock": 30,
            },
        ),
        201,
    )
    assert created["service"]["code"] == "DRG-NEW"
    assert (created["on_hand"], created["low"]) == (0, True)
    item_id = created["id"]
    error(
        ph.api.post(
            "/api/pharmacy/items",
            {
                "service_id": svc.pk,
                "generic_name": "Again",
                "base_unit_code": "tablet",
                "base_unit_name_ar": "حبة",
                "base_unit_name_en": "tablet",
            },
        ),
        409,
        "ITEM_EXISTS",
    )
    edited = ok(
        ph.api.patch(f"/api/pharmacy/items/{item_id}", {"brand_name": "Zyrtec", "reorder_qty": 300})
    )
    assert (edited["brand_name"], edited["reorder_qty"]) == ("Zyrtec", 300)
    with_unit = ok(
        ph.api.post(
            f"/api/pharmacy/items/{item_id}/units",
            {
                "unit_code": "box",
                "name_ar": "علبة",
                "name_en": "box",
                "factor": 20,
                "barcode": "BX",
            },
        ),
        201,
    )
    (unit,) = with_unit["units"]
    assert (unit["factor"], unit["barcode"]) == (20, "BX")
    error(
        ph.api.post(
            f"/api/pharmacy/items/{ph.item.pk}/units",
            {
                "unit_code": "box",
                "name_ar": "علبة",
                "name_en": "box",
                "factor": 30,
                "barcode": "BX",
            },
        ),
        409,
        "BARCODE_TAKEN",
    )
    renamed = ok(
        ph.api.patch(f"/api/pharmacy/items/{item_id}/units/{unit['id']}", {"name_en": "Box of 20"})
    )
    assert renamed["units"][0]["name_en"] == "Box of 20"
    scan = ok(ph.api.get("/api/pharmacy/items/scan?code=BX"))
    assert (scan["item"]["id"], scan["unit_code"]) == (item_id, "box")
    error(ph.api.get("/api/pharmacy/items/scan?code=NOPE"), 409, "BARCODE_UNKNOWN")
    page = ok(ph.api.get("/api/pharmacy/items?q=625100"))
    assert [i["id"] for i in page["items"]] == [item_id]
    low = ok(ph.api.get("/api/pharmacy/items?low=true"))
    assert item_id in {i["id"] for i in low["items"]}
    # The unit of another item is not found under this one.
    error(
        ph.api.patch(f"/api/pharmacy/items/{ph.item.pk}/units/{unit['id']}", {"name_en": "x"}),
        404,
        "NOT_FOUND",
    )


def test_item_search_never_multiplies_on_hand_by_pack_units(ph: Ph) -> None:
    """Review: a search that may match a pack unit's barcode joins the units; the total
    on-hand must still be the batches' sum, not one sum per unit."""
    UnitConversion.objects.create(
        item=ph.item, unit_code="box", name_ar="علبة", name_en="box", factor=30, barcode="BOX-A"
    )
    ph.batch(40, 200)
    ph.batch(10, 300)
    for term in ("Amoxicillin", "BOX-A"):
        page = ok(ph.api.get(f"/api/pharmacy/items?q={term}"))
        (row,) = page["items"]
        assert row["on_hand"] == 50, term
    assert ok(ph.api.get("/api/pharmacy/items"))["items"][0]["on_hand"] == 50


def test_suppliers_list_and_create(ph: Ph) -> None:
    created = ok(
        ph.api.post("/api/pharmacy/suppliers", {"code": "acme", "name_en": "Acme"}),
        201,
    )
    assert created["code"] == "ACME"
    error(
        ph.api.post("/api/pharmacy/suppliers", {"code": "ACME", "name_en": "Again"}),
        409,
        "SUPPLIER_EXISTS",
    )
    assert {s["code"] for s in ok(ph.api.get("/api/pharmacy/suppliers"))} == {"ACME", "SUP"}


# --- goods receipt and dispensing -----------------------------------------------------------


def _receive_two_batches(ph: Ph) -> tuple[Batch, Batch]:
    today = timezone.localdate()
    draft = ok(
        ph.api.post(
            "/api/pharmacy/receipts",
            {
                "supplier_id": ph.supplier.pk,
                "store_id": ph.store.pk,
                "supplier_invoice_no": "INV-77",
                "lines": [
                    {
                        "item_id": ph.item.pk,
                        "batch_no": "LATE",
                        "expiry_date": str(today + timedelta(days=400)),
                        "quantity": 3,
                        "unit_code": "strip",
                        "unit_cost": "25",
                    },
                    {
                        "item_id": ph.item.pk,
                        "batch_no": "EARLY",
                        "expiry_date": str(today + timedelta(days=60)),
                        "quantity": 20,
                        "unit_cost": "2.5",
                    },
                ],
            },
        ),
        201,
    )
    assert draft["status"] == "draft"
    assert draft["total_cost"] == "125.00"
    assert [ln["qty_base"] for ln in draft["lines"]] == [30, 20]
    assert draft["lines"][0]["unit_cost"] == "2.5000"
    assert not StockMove.objects.filter(item=ph.item).exists()  # nothing until posted
    posted = ok(ph.api.post(f"/api/pharmacy/receipts/{draft['id']}/post"))
    assert posted["status"] == "posted"
    assert posted["posted_by"]["username"] == "pharm"
    error(ph.api.post(f"/api/pharmacy/receipts/{draft['id']}/post"), 409, "DOCUMENT_FINAL")
    listed = ok(ph.api.get("/api/pharmacy/receipts?status=posted"))
    assert [r["number"] for r in listed["items"]] == [posted["number"]]
    return Batch.objects.get(batch_no="EARLY"), Batch.objects.get(batch_no="LATE")


def test_receipt_refuses_expired_goods_and_a_duplicate_supplier_invoice(ph: Ph) -> None:
    body = {
        "supplier_id": ph.supplier.pk,
        "store_id": ph.store.pk,
        "supplier_invoice_no": "X-1",
        "lines": [
            {
                "item_id": ph.item.pk,
                "batch_no": "OLD",
                "expiry_date": str(timezone.localdate() - timedelta(days=1)),
                "quantity": 5,
                "unit_cost": "1",
            }
        ],
    }
    error(ph.api.post("/api/pharmacy/receipts", body), 409, "BATCH_EXPIRED")
    assert not Invoice.objects.exists()
    body["lines"][0]["expiry_date"] = str(timezone.localdate() + timedelta(days=90))
    draft = ok(ph.api.post("/api/pharmacy/receipts", body), 201)
    error(ph.api.post("/api/pharmacy/receipts", body), 409, "SUPPLIER_INVOICE_DUPLICATE")
    cancelled = ok(ph.api.post(f"/api/pharmacy/receipts/{draft['id']}/cancel"))
    assert cancelled["status"] == "cancelled"


def test_dispense_suggests_and_takes_the_earliest_expiry(ph: Ph) -> None:
    early, late = _receive_two_batches(ph)
    line = ph.paid_line(10)
    queue = ok(ph.api.get("/api/pharmacy/queue"))
    (visit,) = [v for v in queue if v["visit_id"] == line.visit_id]
    (row,) = visit["lines"]
    assert (row["remaining"], row["authorized"], row["item_id"]) == (10, False, ph.item.pk)
    options = ok(ph.api.get(f"/api/pharmacy/queue/visits/{line.visit_id}?store_id={ph.store.pk}"))
    (opt,) = options["lines"]
    assert [bt["batch_no"] for bt in opt["batches"]] == ["EARLY", "LATE"]
    assert opt["fefo"] == [{"batch_id": early.pk, "quantity": 10}]
    assert opt["available"] == 50
    assert [u["unit_code"] for u in opt["units"]] == ["strip"]
    result = ok(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {
                "visit_id": line.visit_id,
                "store_id": ph.store.pk,
                "lines": [{"service_line_id": line.pk, "quantity": 1, "unit_code": "strip"}],
            },
        ),
        201,
    )
    (given,) = result["lines"]
    assert (given["batch_no"], given["qty_base"], given["unit_code"]) == ("EARLY", 10, "strip")
    assert given["batch_override"] is False
    assert (_balance(early, ph.store), _balance(late, ph.store)) == (10, 30)
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.visit_id not in {v["visit_id"] for v in ok(ph.api.get("/api/pharmacy/queue"))}
    assert ok(ph.api.get(f"/api/pharmacy/dispenses/{result['id']}"))["number"] == result["number"]


def test_another_batch_needs_a_reason(ph: Ph) -> None:
    early, late = _receive_two_batches(ph)
    line = ph.paid_line(5)
    body: dict[str, Any] = {
        "visit_id": line.visit_id,
        "store_id": ph.store.pk,
        "lines": [
            {
                "service_line_id": line.pk,
                "quantity": 5,
                "batches": [{"batch_id": late.pk, "quantity": 5}],
            }
        ],
    }
    error(ph.api.post("/api/pharmacy/dispenses", body), 409, "REASON_REQUIRED")
    assert _balance(late, ph.store) == 30
    body["lines"][0]["override_reason"] = "BATCH_CHOICE"
    body["lines"][0]["override_note"] = "patient asked for the longer expiry"
    result = ok(ph.api.post("/api/pharmacy/dispenses", body), 201)
    (given,) = result["lines"]
    assert (given["batch_no"], given["batch_override"], given["override_reason"]) == (
        "LATE",
        True,
        "BATCH_CHOICE",
    )
    assert (_balance(early, ph.store), _balance(late, ph.store)) == (20, 25)


def test_partial_dispense_defers_or_refunds_the_rest(ph: Ph) -> None:
    ph.batch(4, 200)
    deferred = ph.paid_line(10)
    result = ok(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {
                "visit_id": deferred.visit_id,
                "store_id": ph.store.pk,
                "lines": [{"service_line_id": deferred.pk, "quantity": 3, "remainder": "defer"}],
            },
        ),
        201,
    )
    assert result["lines"][0]["qty_base"] == 3
    deferred.refresh_from_db()
    assert deferred.fulfilment_status == "in_progress"
    (visit,) = [
        v for v in ok(ph.api.get("/api/pharmacy/queue")) if v["visit_id"] == deferred.visit_id
    ]
    assert (visit["lines"][0]["dispensed"], visit["lines"][0]["remaining"]) == (3, 7)
    assert visit["lines"][0]["started"] is True

    refunded = ph.paid_line(6)
    body = {
        "visit_id": refunded.visit_id,
        "store_id": ph.store.pk,
        "lines": [{"service_line_id": refunded.pk, "quantity": 1, "remainder": "refund"}],
    }
    # The pharmacist may not approve the credit note of the remainder alone.
    error(ph.api.post("/api/pharmacy/dispenses", body), 403, "PERMISSION_DENIED")
    error(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {**body, "approver": {"username": "sup", "password": "wrong-password"}},
        ),
        409,
        "APPROVER_INVALID",
    )
    ok(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {**body, "approver": {"username": "sup", "password": TEST_PASSWORD}},
        ),
        201,
    )
    refunded.refresh_from_db()
    assert (refunded.fulfilment_status, refunded.performed_quantity) == ("performed", 1)
    credit = CreditNoteLine.objects.get(invoice_line__service_line=refunded)
    assert credit.quantity == 5
    assert credit.credit_note.approved_by_id == ph.sup.user.pk


def test_unpaid_lines_are_not_in_the_queue_nor_dispensable(ph: Ph) -> None:
    ph.batch(50, 200)
    visit = b.visit()
    (line,) = orders.create_service_lines(
        visit, [{"service": ph.item.service, "quantity": 5}], ph.doctor.user
    )
    assert visit.pk not in {v["visit_id"] for v in ok(ph.api.get("/api/pharmacy/queue"))}
    assert ok(ph.api.get(f"/api/pharmacy/queue/visits/{visit.pk}"))["lines"] == []
    error(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {
                "visit_id": visit.pk,
                "store_id": ph.store.pk,
                "lines": [{"service_line_id": line.pk, "quantity": 5}],
            },
        ),
        409,
        "LINE_NOT_ELIGIBLE",
    )
    assert not StockMove.objects.filter(kind="dispense").exists()


def test_queue_search_by_visit_file_and_invoice_number(ph: Ph) -> None:
    ph.batch(50, 200)
    line = ph.paid_line(2)
    other = ph.paid_line(2)
    invoice = Invoice.objects.get(visit=line.visit)
    for term in (line.visit.number, line.visit.patient.file_no, invoice.number):
        found = ok(ph.api.get(f"/api/pharmacy/queue?q={term}"))
        assert [v["visit_id"] for v in found] == [line.visit_id], term
    assert other.visit_id not in {
        v["visit_id"] for v in ok(ph.api.get(f"/api/pharmacy/queue?q={line.visit.number}"))
    }


def test_more_than_on_hand_is_refused_and_stock_never_goes_negative(ph: Ph) -> None:
    batch = ph.batch(3, 200)
    line = ph.paid_line(5)
    body = error(
        ph.api.post(
            "/api/pharmacy/dispenses",
            {
                "visit_id": line.visit_id,
                "store_id": ph.store.pk,
                "lines": [{"service_line_id": line.pk, "quantity": 5}],
            },
        ),
        409,
        "STOCK_INSUFFICIENT",
    )
    assert body["details"]["available"] == 3
    assert _balance(batch, ph.store) == 3
    error(
        ph.api.post(
            "/api/pharmacy/adjustments",
            {
                "store_id": ph.store.pk,
                "reason_code": "DAMAGED",
                "lines": [{"batch_id": batch.pk, "qty_base": -4}],
            },
        ),
        409,
        "STOCK_INSUFFICIENT",
    )


# --- adjustments, counts, transfers ---------------------------------------------------------


def test_adjustment_requested_then_approved_by_another_person(ph: Ph) -> None:
    batch = ph.batch(10, 200)
    adj = ok(
        ph.api.post(
            "/api/pharmacy/adjustments",
            {
                "store_id": ph.store.pk,
                "reason_code": "DAMAGED",
                "note": "broken strip",
                "lines": [{"batch_id": batch.pk, "qty_base": -2, "note": "dropped"}],
            },
        ),
        201,
    )
    assert (adj["status"], adj["reason"]["code"]) == ("draft", "DAMAGED")
    assert _balance(batch, ph.store) == 10  # nothing moves before approval
    queue = ok(ph.manager.api.get("/api/pharmacy/adjustments?status=draft"))
    assert [a["id"] for a in queue["items"]] == [adj["id"]]
    error(
        ph.manager.api.post(f"/api/pharmacy/adjustments/{adj['id']}/reject", {"note": " "}),
        409,
        "REASON_REQUIRED",
    )
    approved = ok(
        ph.manager.api.post(f"/api/pharmacy/adjustments/{adj['id']}/approve", {"note": "seen"})
    )
    assert (approved["status"], approved["decided_by"]["username"]) == ("approved", "mgr")
    assert _balance(batch, ph.store) == 8
    error(
        ph.manager.api.post(f"/api/pharmacy/adjustments/{adj['id']}/approve", {"note": ""}),
        409,
        "DOCUMENT_FINAL",
    )
    # "Other" needs a note (invariant 4).
    error(
        ph.api.post(
            "/api/pharmacy/adjustments",
            {
                "store_id": ph.store.pk,
                "reason_code": "OTHER",
                "lines": [{"batch_id": batch.pk, "qty_base": 5}],
            },
        ),
        409,
        "REASON_NOTE_REQUIRED",
    )


def test_count_variance_posts_a_count_correction(ph: Ph) -> None:
    first = ph.batch(10, 200)
    second = ph.batch(5, 300)
    count = ok(ph.api.post("/api/pharmacy/counts", {"store_id": ph.store.pk}), 201)
    assert (count["status"], count["total"], count["counted"]) == ("open", 2, 0)
    error(ph.api.post("/api/pharmacy/counts", {"store_id": ph.store.pk}), 409, "COUNT_ALREADY_OPEN")
    ok(
        ph.api.post(
            f"/api/pharmacy/counts/{count['id']}/record", {"batch_id": first.pk, "counted_qty": 7}
        )
    )
    error(ph.manager.api.post(f"/api/pharmacy/counts/{count['id']}/post"), 409, "COUNT_INCOMPLETE")
    counted = ok(
        ph.api.post(
            f"/api/pharmacy/counts/{count['id']}/record", {"batch_id": second.pk, "counted_qty": 5}
        )
    )
    variances = {ln["batch_id"]: ln["variance"] for ln in counted["lines"]}
    assert variances == {first.pk: -3, second.pk: 0}
    assert counted["variance_value"] == "-7.50"
    posted = ok(ph.manager.api.post(f"/api/pharmacy/counts/{count['id']}/post"))
    assert posted["status"] == "posted"
    assert _balance(first, ph.store) == 7
    (move,) = StockMove.objects.filter(kind="count_correction")
    assert (move.batch_id, int(move.qty_base)) == (first.pk, -3)


def test_transfer_send_receive_short_with_an_approver_and_cancel(ph: Ph) -> None:
    batch = ph.batch(20, 200, store=ph.main)
    error(
        ph.api.post(
            "/api/pharmacy/transfers",
            {
                "from_store_id": ph.main.pk,
                "to_store_id": ph.store.pk,
                "lines": [{"batch_id": batch.pk, "qty_base": 21}],
            },
        ),
        409,
        "STOCK_INSUFFICIENT",
    )
    transfer = ok(
        ph.api.post(
            "/api/pharmacy/transfers",
            {
                "from_store_id": ph.main.pk,
                "to_store_id": ph.store.pk,
                "lines": [{"batch_id": batch.pk, "qty_base": 12}],
            },
        ),
        201,
    )
    sent = ok(ph.api.post(f"/api/pharmacy/transfers/{transfer['id']}/send"))
    assert sent["status"] == "sent"
    assert _balance(batch, ph.main) == 8
    (line,) = sent["lines"]
    short = {"lines": [{"line_id": line["id"], "qty_base": 10}], "shortage_reason": "LOST"}
    # The pharmacist does not approve a shortage; the manager does at the counter.
    error(
        ph.api.post(f"/api/pharmacy/transfers/{transfer['id']}/receive", short),
        403,
        "PERMISSION_DENIED",
    )
    received = ok(
        ph.api.post(
            f"/api/pharmacy/transfers/{transfer['id']}/receive",
            {**short, "approver": {"username": "mgr", "password": TEST_PASSWORD}},
        )
    )
    assert received["status"] == "received"
    assert received["shortage_approved_by"]["username"] == "mgr"
    assert _balance(batch, ph.store) == 10
    other = ok(
        ph.api.post(
            "/api/pharmacy/transfers",
            {
                "from_store_id": ph.main.pk,
                "to_store_id": ph.store.pk,
                "lines": [{"batch_id": batch.pk, "qty_base": 8}],
            },
        ),
        201,
    )
    ok(ph.api.post(f"/api/pharmacy/transfers/{other['id']}/send"))
    error(
        ph.api.post(f"/api/pharmacy/transfers/{other['id']}/cancel", {"note": ""}),
        409,
        "REASON_REQUIRED",
    )
    cancelled = ok(
        ph.api.post(f"/api/pharmacy/transfers/{other['id']}/cancel", {"note": "wrong store"})
    )
    assert cancelled["status"] == "cancelled"
    assert _balance(batch, ph.main) == 8
    listed = ok(ph.api.get("/api/pharmacy/transfers?status=received"))
    assert [t["id"] for t in listed["items"]] == [transfer["id"]]


# --- reports, stock card, batches -----------------------------------------------------------


def test_expiry_low_stock_stock_card_and_store_batches(ph: Ph) -> None:
    soon = ph.batch(5, 20, no="SOON")
    later = ph.batch(6, 75, no="LATER")
    ph.batch(4, 200, no="FAR")
    ex30 = ok(ph.api.get("/api/pharmacy/reports/expiry?days=30"))
    assert [r["batch_no"] for r in ex30] == ["SOON"]
    assert (ex30[0]["days_left"], ex30[0]["value"]) == (20, "12.50")
    ex90 = ok(ph.api.get(f"/api/pharmacy/reports/expiry?days=90&store_id={ph.store.pk}"))
    assert [r["batch_no"] for r in ex90] == ["SOON", "LATER"]
    assert ph.api.get("/api/pharmacy/reports/expiry?days=0").status_code == 422
    low = ok(ph.api.get("/api/pharmacy/reports/low-stock"))
    (row,) = [r for r in low if r["item_id"] == ph.item.pk]
    assert (row["on_hand"], row["min_stock"], row["suggested_order"]) == (15, 20, 25)
    card = ok(ph.api.get(f"/api/pharmacy/items/{ph.item.pk}/stock-card?store_id={ph.store.pk}"))
    assert [r["balance"] for r in card["rows"]] == [15, 11, 5]  # newest first
    assert card["rows"][-1]["batch_no"] == "SOON"
    batches = ok(ph.api.get(f"/api/pharmacy/stores/{ph.store.pk}/batches?q=Amox"))
    assert [bt["batch_id"] for bt in batches] == [soon.pk, later.pk, batches[2]["batch_id"]]
    assert batches[0]["item_name"] == "Amoxicillin 500 mg"
    detail = ok(ph.api.get(f"/api/pharmacy/items/{ph.item.pk}"))
    assert [bt["batch_no"] for bt in detail["batches"]] == ["SOON", "LATER", "FAR"]


# --- walk-in sale ---------------------------------------------------------------------------


def test_walk_in_sale_creates_a_draft_invoice_for_the_cashier(ph: Ph, make_user: Any) -> None:
    from apps.catalog.models import PriceItem

    PriceItem.objects.get_or_create(
        version=engine.price_version(),
        service=ph.item.service,
        defaults={"unit_price": Decimal("300.00")},
    )
    ph.batch(40, 200)
    services = ok(ph.api.get("/api/pharmacy/sale/services?q=Amox"))
    (svc,) = services
    assert (svc["unit_price"], svc["on_hand"], svc["item_id"]) == ("300.00", 40, ph.item.pk)
    error(
        ph.api.post(
            "/api/pharmacy/sales", {"items": [{"service_id": ph.item.service_id, "quantity": 2}]}
        ),
        409,
        "CUSTOMER_REQUIRED",
    )
    invoice = ok(
        ph.api.post(
            "/api/pharmacy/sales",
            {
                "customer": {"full_name": "Hassan Ali", "sex": "male", "phone": "0911222333"},
                "items": [{"service_id": ph.item.service_id, "quantity": 2}],
            },
        ),
        201,
    )
    assert (invoice["status"], invoice["patient_total"]) == ("draft", "600.00")
    assert invoice["patient"]["full_name_en"] == "Hassan Ali"
    line = ServiceLine.objects.get(visit_id=invoice["visit_id"])
    assert (line.order_source, line.billing_status) == ("pharmacy_sale", "unbilled")
    # Not paid yet: nothing to dispense (invariant 1).
    assert invoice["visit_id"] not in {v["visit_id"] for v in ok(ph.api.get("/api/pharmacy/queue"))}
    customers = ok(ph.api.get("/api/pharmacy/sale/customers?q=Hassan"))
    assert customers[0]["file_no"] == invoice["patient"]["file_no"]
    again = ok(
        ph.api.post(
            "/api/pharmacy/sales",
            {
                "patient_id": customers[0]["id"],
                "items": [{"service_id": ph.item.service_id, "quantity": 1}],
            },
        ),
        201,
    )
    assert again["patient"]["id"] == customers[0]["id"]
    procedure = b.service(kind="procedure")
    error(
        ph.api.post(
            "/api/pharmacy/sales",
            {
                "patient_id": customers[0]["id"],
                "items": [{"service_id": procedure.pk, "quantity": 1}],
            },
        ),
        409,
        "SERVICE_NOT_SALEABLE",
    )
    # A cashier may sell too (FEATURES 5.12), a doctor may not.
    cashier = kit.actor(make_user, "cash", "cashier")
    assert cashier.api.get("/api/pharmacy/sale/services").status_code == 200
    error(ph.doctor.api.get("/api/pharmacy/sale/services"), 403, "PERMISSION_DENIED")


def test_item_is_never_written_by_a_doctor(ph: Ph) -> None:
    error(
        ph.doctor.api.patch(f"/api/pharmacy/items/{ph.item.pk}", {"min_stock": 1}),
        403,
        "PERMISSION_DENIED",
    )
    assert Item.objects.get(pk=ph.item.pk).min_stock == Decimal(20)
