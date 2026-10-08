"""``/api/billing`` contract: lookup, drafts, coverage split, discounts, approval, credit notes.

Each endpoint: the happy path, permission denied (doctors hold no billing code), and a domain
error code. The money rules themselves are tested in ``test_services.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.billing.models import Invoice
from apps.orders.models import ServiceLine
from apps.payments.tests import api_kit as kit
from apps.payments.tests.api_kit import Desk, error, ok

pytestmark = pytest.mark.django_db


@pytest.fixture
def d(make_user: Any) -> Desk:
    return kit.desk(make_user)


def _draft(d: Desk, iv: kit.InsuredVisit) -> dict[str, Any]:
    return ok(d.cashier.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}), 201)


def test_lookup_finds_by_file_number_phone_name_and_visit_number(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    for term in (iv.patient.file_no, "0912345678", "amna", iv.visit.number):
        body = ok(d.cashier.api.get(f"/api/billing/lookup?q={term}"))
        (item,) = [i for i in body["items"] if i["patient"]["id"] == iv.patient.pk]
        (visit,) = item["visits"]
        assert visit["number"] == iv.visit.number
        assert visit["unbilled_count"] == 2
        assert visit["outstanding"] == "0.00"
        assert item["balance"]["credit"] == "0.00"


def test_doctors_never_reach_billing(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    for path in (
        f"/api/billing/lookup?q={iv.patient.file_no}",
        f"/api/billing/visits/{iv.visit.pk}",
        "/api/billing/reasons?category=discount",
    ):
        error(d.doctor.api.get(path), 403, "PERMISSION_DENIED")
    error(
        d.doctor.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}),
        403,
        "PERMISSION_DENIED",
    )


def test_visit_billing_lists_unbilled_lines_and_payers(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    body = ok(d.cashier.api.get(f"/api/billing/visits/{iv.visit.pk}"))
    assert [ln["id"] for ln in body["unbilled"]] == [iv.insured.pk, iv.cash_line.pk]
    assert {ln["state"] for ln in body["unbilled"]} == {"requested"}
    assert body["unbilled"][0]["payer"]["code"] == iv.payer.code
    assert body["drafts"] == []
    assert body["invoices"] == []
    unbilled = ok(d.cashier.api.get(f"/api/billing/visits/{iv.visit.pk}/unbilled-lines"))
    assert [ln["id"] for ln in unbilled] == [iv.insured.pk, iv.cash_line.pk]


def test_draft_splits_each_line_between_payer_and_patient(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _draft(d, iv)
    assert inv["status"] == "draft"
    assert inv["number"] is None
    first, second = inv["lines"]
    assert (first["gross"], first["payer_share"], first["patient_share"]) == (
        "10000.00",
        "7000.00",
        "3000.00",
    )
    assert first["payer"]["code"] == iv.payer.code
    assert (second["gross"], second["payer_share"], second["patient_share"]) == (
        "2000.00",
        "1400.00",
        "600.00",
    )
    assert (inv["payer_total"], inv["patient_total"]) == ("8400.00", "3600.00")
    # A line on a draft is not offered for a second draft.
    error(
        d.cashier.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}),
        409,
        "LINE_ON_DRAFT_INVOICE",
    )
    body = ok(d.cashier.api.get(f"/api/billing/visits/{iv.visit.pk}"))
    assert {ln["draft_invoice_id"] for ln in body["unbilled"]} == {inv["id"]}


def test_line_payer_change_reprices_for_cash(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    body = ok(
        d.cashier.api.post(
            f"/api/billing/lines/{iv.cash_line.pk}/payer",
            {"payer_id": None, "note": "patient pays this one"},
        )
    )
    line = next(ln for ln in body["unbilled"] if ln["id"] == iv.cash_line.pk)
    assert line["payer"] is None
    error(
        d.cashier.api.post(
            f"/api/billing/lines/{iv.cash_line.pk}/payer", {"payer_id": None, "note": " "}
        ),
        409,
        "REASON_REQUIRED",
    )


def test_discount_above_the_cashier_limit_needs_a_supervisor_at_the_desk(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _draft(d, iv)
    line_id = inv["lines"][0]["id"]
    url = f"/api/billing/invoices/{inv['id']}/lines/{line_id}/discount"
    # The cashier's limit is 0%.
    error(
        d.cashier.api.post(url, {"reason": "HARDSHIP", "amount": "300"}),
        409,
        "DISCOUNT_LIMIT_EXCEEDED",
    )
    error(d.cashier.api.post(url, {"amount": "300", "reason": ""}), 422, "VALIDATION_ERROR")
    error(
        d.cashier.api.post(
            url,
            {
                "reason": "HARDSHIP",
                "amount": "300",
                "approver": {"username": "sup", "password": "not-the-password"},
            },
        ),
        409,
        "APPROVER_INVALID",
    )
    # The supervisor's limit is 25% of the 3,000 patient share.
    body = ok(
        d.cashier.api.post(
            url,
            {
                "reason": "HARDSHIP",
                "note": "regular patient",
                "amount": "300",
                "approver": {"username": "sup", "password": kit.TEST_PASSWORD},
            },
        )
    )
    line = body["lines"][0]
    assert (line["discount"], line["patient_share"], line["payer_share"]) == (
        "300.00",
        "2700.00",
        "7000.00",
    )
    assert line["discount_approved_by"]["username"] == "sup"
    assert line["discount_reason"]["code"] == "HARDSHIP"
    error(
        d.cashier.api.post(
            url,
            {
                "reason": "HARDSHIP",
                "amount": "1000",
                "approver": {"username": "sup", "password": kit.TEST_PASSWORD},
            },
        ),
        409,
        "DISCOUNT_LIMIT_EXCEEDED",
    )


def test_invoice_discount_by_percent_within_the_supervisors_own_limit(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = ok(d.sup.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}), 201)
    body = ok(
        d.sup.api.post(
            f"/api/billing/invoices/{inv['id']}/discount",
            {"reason": "STAFF", "percent": "10"},
        )
    )
    assert body["discount_total"] == "360.00"
    assert body["patient_total"] == "3240.00"
    error(
        d.doctor.api.post(
            f"/api/billing/invoices/{inv['id']}/discount", {"reason": "STAFF", "percent": "10"}
        ),
        403,
        "PERMISSION_DENIED",
    )


def test_remove_cancel_and_void_draft_lines(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _draft(d, iv)
    first, second = inv["lines"]
    body = ok(
        d.cashier.api.request("DELETE", f"/api/billing/invoices/{inv['id']}/lines/{second['id']}")
    )
    assert [ln["id"] for ln in body["lines"]] == [first["id"]]
    assert ServiceLine.objects.get(pk=iv.cash_line.pk).billing_status == "unbilled"

    body = ok(
        d.cashier.api.post(
            f"/api/billing/invoices/{inv['id']}/lines/{first['id']}/cancel",
            {"reason": "PATIENT_REFUSED"},
        )
    )
    assert body["lines"] == []
    assert ServiceLine.objects.get(pk=iv.insured.pk).fulfilment_status == "cancelled"

    error(
        d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/void", {"note": ""}),
        422,
        "VALIDATION_ERROR",
    )
    body = ok(d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/void", {"note": "empty"}))
    assert body["status"] == "void"


def test_approve_freezes_numbers_and_refuses_a_second_approval(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _draft(d, iv)
    body = ok(d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/approve"))
    assert body["status"] == "approved"
    assert body["number"].startswith("INV-")
    assert body["outstanding"] == "3600.00"
    assert body["paid"] == "0.00"
    assert {ln["state"] for ln in body["lines"]} == {"invoiced"}
    assert all(ln["outstanding"] is not None for ln in body["lines"])
    error(
        d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/approve"), 409, "INVOICE_NOT_DRAFT"
    )
    error(
        d.cashier.api.post(
            f"/api/billing/invoices/{inv['id']}/lines/{body['lines'][0]['id']}/discount",
            {"reason": "STAFF", "amount": "1"},
        ),
        409,
        "INVOICE_FROZEN",
    )
    printed = ok(d.cashier.api.get(f"/api/billing/invoices/{inv['id']}/print"))
    assert printed["invoice"]["number"] == body["number"]
    assert set(printed["center"]) >= {"name_ar", "name_en", "address", "phone"}


def test_a_line_of_another_invoice_is_not_found(d: Desk) -> None:
    a = kit.insured_visit(d.doctor.user)
    b = kit.insured_visit(d.doctor.user)
    inv_a, inv_b = _draft(d, a), _draft(d, b)
    error(
        d.cashier.api.request(
            "DELETE", f"/api/billing/invoices/{inv_a['id']}/lines/{inv_b['lines'][0]['id']}"
        ),
        404,
        "NOT_FOUND",
    )


def test_reasons_by_list(d: Desk) -> None:
    codes = [r["code"] for r in ok(d.cashier.api.get("/api/billing/reasons?category=variance"))]
    assert "COUNTING_ERROR" in codes
    error(d.cashier.api.get("/api/billing/reasons?category=stock_adjust"), 422, "VALIDATION_ERROR")


def _approved_and_paid(d: Desk, iv: kit.InsuredVisit) -> dict[str, Any]:
    inv = _draft(d, iv)
    inv = ok(d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/approve"))
    ok(d.cashier.api.post("/api/payments/shifts", {"opening_float": "0"}), 201)
    ok(
        d.cashier.api.post(
            "/api/payments/payments",
            {
                "patient_id": iv.patient.pk,
                "method": "cash",
                "amount": inv["outstanding"],
                "allocations": [{"invoice_id": inv["id"], "amount": inv["outstanding"]}],
            },
        ),
        201,
    )
    return inv


def test_credit_note_by_cashier_approved_by_supervisor_opens_a_refund(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved_and_paid(d, iv)
    line = inv["lines"][1]
    url = f"/api/billing/invoices/{inv['id']}/credit-notes"
    error(
        d.cashier.api.post(
            url,
            {
                "lines": [{"invoice_line_id": line["id"], "quantity": 2}],
                "reason": "SERVICE_CANCELLED",
            },
        ),
        409,
        "CREDIT_EXCEEDS_LINE",
    )
    cn = ok(
        d.cashier.api.post(
            url,
            {"lines": [{"invoice_line_id": line["id"], "quantity": 1}], "reason": "PRICE_ERROR"},
        ),
        201,
    )
    assert cn["status"] == "draft"
    assert cn["patient_total"] == "600.00"
    queue = ok(d.sup.api.get("/api/billing/credit-notes?status=draft"))
    assert [x["id"] for x in queue["items"]] == [cn["id"]]
    error(
        d.cashier.api.post(f"/api/billing/credit-notes/{cn['id']}/approve", {}),
        403,
        "PERMISSION_DENIED",
    )
    outcome = ok(d.sup.api.post(f"/api/billing/credit-notes/{cn['id']}/approve", {}))
    assert outcome["credit_note"]["status"] == "approved"
    assert outcome["credit_note"]["number"].startswith("CN-")
    assert outcome["deallocated"] == "600.00"
    assert outcome["refund"]["status"] == "requested"
    assert outcome["refund"]["amount"] == "600.00"
    assert outcome["credit_note"]["released"] == "600.00"
    detail = ok(d.cashier.api.get(f"/api/billing/invoices/{inv['id']}"))
    assert detail["outstanding"] == "0.00"
    assert detail["lines"][1]["state"] == "cancelled"
    assert detail["lines"][1]["credited_quantity"] == 1
    assert Invoice.objects.get(pk=inv["id"]).patient_total.__str__() == "3600.00"
