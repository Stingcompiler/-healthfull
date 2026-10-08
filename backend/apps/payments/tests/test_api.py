"""``/api/payments`` contract: shifts, payments, transfers, refunds, handovers, review.

Each endpoint: the happy path and a domain error code. Permission denied for every endpoint
and every role without its code is generated in ``test_permission_matrix.py``. The money rules
themselves are tested in ``test_services.py`` and the domain property tests.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import pytest

from apps.orders.models import ServiceLine
from apps.payments.models import Payment
from apps.payments.tests import api_kit as kit
from apps.payments.tests.api_kit import Desk, error, ok

pytestmark = pytest.mark.django_db


@pytest.fixture
def d(make_user: Any) -> Desk:
    return kit.desk(make_user)


def _approved(d: Desk, iv: kit.InsuredVisit) -> dict[str, Any]:
    inv = ok(d.cashier.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}), 201)
    return ok(d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/approve"))


def _open(actor: kit.Actor, opening_float: str = "0") -> dict[str, Any]:
    return ok(actor.api.post("/api/payments/shifts", {"opening_float": opening_float}), 201)


def _pay(actor: kit.Actor, patient_id: int, inv: dict[str, Any], **extra: Any) -> Any:
    body = {
        "patient_id": patient_id,
        "method": "cash",
        "amount": inv["outstanding"],
        "allocations": [{"invoice_id": inv["id"], "amount": inv["outstanding"]}],
        **extra,
    }
    return actor.api.post("/api/payments/payments", body)


# --- shifts ----------------------------------------------------------------------------------


def test_open_shift_and_current_report(d: Desk) -> None:
    assert ok(d.cashier.api.get("/api/payments/shifts/current"))["report"] is None
    report = _open(d.cashier, "5000")
    assert report["shift"]["status"] == "open"
    assert report["expected_cash"] == "5000.00"
    assert report["frozen"] is False
    current = ok(d.cashier.api.get("/api/payments/shifts/current"))
    assert current["report"]["shift"]["id"] == report["shift"]["id"]
    error(
        d.cashier.api.post("/api/payments/shifts", {"opening_float": "0"}),
        409,
        "SHIFT_ALREADY_OPEN",
    )
    error(
        d.doctor.api.post("/api/payments/shifts", {"opening_float": "0"}),
        403,
        "PERMISSION_DENIED",
    )
    error(d.doctor.api.get("/api/payments/shifts/current"), 403, "PERMISSION_DENIED")


def test_cash_payment_settles_the_lines_and_change_stays_out(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    error(_pay(d.cashier, iv.patient.pk, inv), 409, "SHIFT_NOT_OPEN")
    _open(d.cashier)
    payment = ok(_pay(d.cashier, iv.patient.pk, inv), 201)
    assert payment["verification"] == "confirmed"
    assert payment["amount"] == "3600.00"
    assert payment["unallocated"] == "0.00"
    assert [a["invoice_id"] for a in payment["allocations"]] == [inv["id"]]
    assert {ln.billing_status for ln in ServiceLine.objects.filter(visit=iv.visit)} == {"settled"}
    receipt = ok(d.cashier.api.get(f"/api/payments/payments/{payment['id']}/receipt"))
    assert receipt["verify_code"].startswith(payment["number"] + "|3600.00|")
    assert receipt["invoices"][0]["number"] == inv["number"]
    assert len(receipt["invoices"][0]["lines"]) == 2
    error(d.doctor.api.get(f"/api/payments/payments/{payment['id']}"), 403, "PERMISSION_DENIED")


def test_overpayment_without_allocation_becomes_credit_then_allocates(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    _open(d.cashier)
    payment = ok(
        d.cashier.api.post(
            "/api/payments/payments",
            {"patient_id": iv.patient.pk, "method": "cash", "amount": "5000"},
        ),
        201,
    )
    assert payment["unallocated"] == "5000.00"
    error(
        d.cashier.api.post(f"/api/payments/payments/{payment['id']}/allocate", {}),
        409,
        "ALLOCATION_REQUIRED",
    )
    body = ok(
        d.cashier.api.post(f"/api/payments/payments/{payment['id']}/allocate", {"auto": True})
    )
    assert body["unallocated"] == "1400.00"
    detail = ok(d.cashier.api.get(f"/api/billing/invoices/{inv['id']}"))
    assert detail["outstanding"] == "0.00"
    balance = ok(d.cashier.api.get(f"/api/billing/visits/{iv.visit.pk}"))["balance"]
    assert balance["credit"] == "1400.00"


def test_transfer_needs_bank_and_reference_and_duplicates_need_a_supervisor(d: Desk) -> None:
    a = kit.insured_visit(d.doctor.user)
    b = kit.insured_visit(d.doctor.user)
    inv_a, inv_b = _approved(d, a), _approved(d, b)
    _open(d.cashier)
    error(
        _pay(d.cashier, a.patient.pk, inv_a, method="bank_transfer", reference="TX-1"),
        409,
        "BANK_REQUIRED",
    )
    first = ok(
        _pay(d.cashier, a.patient.pk, inv_a, method="bank_transfer", bank="BOK", reference="TX 1"),
        201,
    )
    assert first["verification"] == "pending"
    # The line settles (service proceeds) though the money is pending.
    assert ServiceLine.objects.get(pk=a.insured.pk).billing_status == "settled"

    dup = {"method": "bank_transfer", "bank": "BOK", "reference": "tx-1"}
    error(_pay(d.cashier, b.patient.pk, inv_b, **dup), 409, "DUPLICATE_REFERENCE")
    # A reason alone is not enough: the cashier does not hold payments.override_duplicate.
    error(
        _pay(d.cashier, b.patient.pk, inv_b, **dup, override={"reason": "DUPLICATE_VERIFIED"}),
        409,
        "OVERRIDE_NOT_PERMITTED",
    )
    wrong = {"username": "sup", "password": "nope"}
    error(
        _pay(
            d.cashier,
            b.patient.pk,
            inv_b,
            **dup,
            override={"reason": "DUPLICATE_VERIFIED", "approver": wrong},
        ),
        409,
        "APPROVER_INVALID",
    )
    sup = {"username": "sup", "password": kit.TEST_PASSWORD}
    second = ok(
        _pay(
            d.cashier,
            b.patient.pk,
            inv_b,
            **dup,
            override={"reason": "DUPLICATE_VERIFIED", "note": "two payments", "approver": sup},
        ),
        201,
    )
    assert second["duplicate_override"] is True
    assert second["duplicate_of_number"] == first["number"]
    assert second["override_by"]["username"] == "sup"
    assert second["override_reason"]["code"] == "DUPLICATE_VERIFIED"


def _pending_transfer(d: Desk, reference: str) -> tuple[kit.InsuredVisit, dict[str, Any]]:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    payment = ok(
        _pay(
            d.cashier, iv.patient.pk, inv, method="bank_transfer", bank="BOK", reference=reference
        ),
        201,
    )
    return iv, payment


def test_a_printed_receipt_is_checked_by_its_qr_or_number(d: Desk) -> None:
    """FEATURES 6.9, 15.1: the receipt QR is looked up; a rejected transfer never stands."""
    _open(d.cashier)
    iv, transfer = _pending_transfer(d, "Q-1")
    code = ok(d.cashier.api.get(f"/api/payments/payments/{transfer['id']}/receipt"))["verify_code"]

    def check(who: kit.Actor, text: str) -> Any:
        return who.api.get(f"/api/payments/receipts/check?{urlencode({'code': text})}")

    body = ok(check(d.cashier, code))
    assert (body["standing"], body["payment"]["id"]) == ("pending", transfer["id"])
    assert body["code_amount"] == "3600.00"
    assert ok(check(d.cashier, transfer["number"].lower()))["standing"] == "pending"
    number, _, day = code.split("|")
    assert ok(check(d.cashier, f"{number}|9999.00|{day}"))["standing"] == "mismatch"

    _open(d.sup)
    ok(
        d.sup.api.post(
            f"/api/payments/payments/{transfer['id']}/reject", {"reason": "NOT_RECEIVED"}
        )
    )
    assert ok(check(d.sup, code))["standing"] == "rejected"

    cash_inv = _approved(d, kit.insured_visit(d.doctor.user))
    cash = ok(_pay(d.cashier, cash_inv["patient"]["id"], cash_inv), 201)
    cash_code = ok(d.cashier.api.get(f"/api/payments/payments/{cash['id']}/receipt"))["verify_code"]
    assert ok(check(d.accountant, cash_code))["standing"] == "valid"
    error(check(d.cashier, "PAY-NOPE"), 404, "NOT_FOUND")
    error(check(d.doctor, cash_code), 403, "PERMISSION_DENIED")
    assert iv.patient.pk == body["payment"]["patient"]["id"]


def test_pending_queue_confirm_and_reject_after_close(d: Desk) -> None:
    _open(d.cashier)
    iv1, p1 = _pending_transfer(d, "A-100")
    iv2, p2 = _pending_transfer(d, "A-200")
    error(d.cashier.api.get("/api/payments/transfers"), 403, "PERMISSION_DENIED")
    queue = ok(d.sup.api.get("/api/payments/transfers"))
    assert [x["payment"]["id"] for x in queue["items"]] == [p1["id"], p2["id"]]
    assert queue["items"][0]["cashier"]["username"] == "cash"

    report = ok(d.cashier.api.get("/api/payments/shifts/current"))["report"]
    assert report["collection"]["bank_pending"] == "7200.00"
    assert report["collection"]["confirmed_total"] == "0.00"
    shift_id = report["shift"]["id"]
    closed = ok(d.cashier.api.post(f"/api/payments/shifts/{shift_id}/close", {"counted": "0"}))
    assert closed["frozen"] is True
    assert {p["number"] for p in closed["pending"]} == {p1["number"], p2["number"]}

    error(
        d.sup.api.post(f"/api/payments/payments/{p1['id']}/confirm", {"note": ""}),
        422,
        "VALIDATION_ERROR",
    )
    confirmed = ok(
        d.sup.api.post(f"/api/payments/payments/{p1['id']}/confirm", {"note": "bank app"})
    )
    assert confirmed["verification"] == "confirmed"
    assert confirmed["verified_by"]["username"] == "sup"

    # The original shift is closed: the rejection needs the supervisor's own open shift.
    error(
        d.sup.api.post(f"/api/payments/payments/{p2['id']}/reject", {"reason": "NOT_RECEIVED"}),
        409,
        "SHIFT_NOT_OPEN",
    )
    sup_shift = _open(d.sup)
    rejection = ok(
        d.sup.api.post(f"/api/payments/payments/{p2['id']}/reject", {"reason": "NOT_RECEIVED"})
    )
    assert rejection["payment"]["verification"] == "rejected"
    assert rejection["reversal"]["amount"] == "-3600.00"
    assert rejection["reversal"]["shift_id"] == sup_shift["shift"]["id"]
    assert rejection["reversal"]["reversal_of_number"] == p2["number"]
    assert ServiceLine.objects.get(pk=iv2.insured.pk).billing_status == "invoiced"
    assert ServiceLine.objects.get(pk=iv1.insured.pk).billing_status == "settled"
    # The closed shift's report did not change; the reversal shows where it was booked.
    again = ok(d.cashier.api.get(f"/api/payments/shifts/{shift_id}"))
    assert again["collection"] == closed["collection"]
    assert again["pending"] == closed["pending"]
    sup_report = ok(d.sup.api.get(f"/api/payments/shifts/{sup_shift['shift']['id']}"))
    assert sup_report["late_reversals"] == "3600.00"
    assert ok(d.sup.api.get("/api/payments/transfers"))["items"] == []
    error(
        d.sup.api.post(f"/api/payments/payments/{p2['id']}/reject", {"reason": "NOT_RECEIVED"}),
        409,
        "PAYMENT_NOT_REJECTABLE",
    )


def test_close_with_variance_needs_a_reason_and_manager_signs_off(d: Desk) -> None:
    shift = _open(d.cashier, "1000")["shift"]
    url = f"/api/payments/shifts/{shift['id']}/close"
    error(d.cashier.api.post(url, {"counted": "900"}), 409, "VARIANCE_EXPLANATION_REQUIRED")
    closed = ok(
        d.cashier.api.post(url, {"counted": "900", "reason": "COUNTING_ERROR", "note": "coins"})
    )
    assert (closed["variance"], closed["shift"]["variance_reason"]["code"]) == (
        "-100.00",
        "COUNTING_ERROR",
    )
    error(d.cashier.api.post(url, {"counted": "900"}), 409, "SHIFT_CLOSED")

    error(d.cashier.api.get("/api/payments/shifts?status=closed"), 403, "PERMISSION_DENIED")
    error(d.cashier2.api.get(f"/api/payments/shifts/{shift['id']}"), 403, "PERMISSION_DENIED")
    queue = ok(d.manager.api.get("/api/payments/shifts?status=closed&reviewed=false"))
    assert [x["shift"]["id"] for x in queue["items"]] == [shift["id"]]
    error(
        d.cashier.api.post(f"/api/payments/shifts/{shift['id']}/review", {}),
        403,
        "PERMISSION_DENIED",
    )
    reviewed = ok(
        d.manager.api.post(
            f"/api/payments/shifts/{shift['id']}/review", {"outcome": "approved", "note": "ok"}
        )
    )
    assert reviewed["shift"]["review"]["reviewed_by"]["username"] == "mgr"
    assert ok(d.manager.api.get("/api/payments/shifts?status=closed&reviewed=false"))["items"] == []


def test_handover_to_the_next_shift_must_be_received_before_it_closes(d: Desk) -> None:
    first = _open(d.cashier, "2000")["shift"]
    second = _open(d.cashier2)["shift"]
    targets = ok(d.cashier.api.get("/api/payments/shifts/handover-targets"))
    assert [t["id"] for t in targets] == [second["id"]]
    error(
        d.cashier.api.post(
            f"/api/payments/shifts/{first['id']}/handovers",
            {"amount": "5000", "destination": "safe"},
        ),
        409,
        "CASH_INSUFFICIENT",
    )
    handover = ok(
        d.cashier.api.post(
            f"/api/payments/shifts/{first['id']}/handovers",
            {"amount": "1500", "destination": "next_shift", "to_shift_id": second["id"]},
        ),
        201,
    )
    incoming = ok(d.cashier2.api.get("/api/payments/shifts/current"))["incoming_handovers"]
    assert [h["id"] for h in incoming] == [handover["id"]]
    error(
        d.cashier2.api.post(f"/api/payments/shifts/{second['id']}/close", {"counted": "0"}),
        409,
        "HANDOVER_PENDING",
    )
    received = ok(d.cashier2.api.post(f"/api/payments/handovers/{handover['id']}/receive"))
    assert received["received_by"]["username"] == "cash2"
    report = ok(d.cashier2.api.get("/api/payments/shifts/current"))["report"]
    assert report["expected_cash"] == "1500.00"
    assert ok(d.cashier.api.get("/api/payments/shifts/current"))["report"]["expected_cash"] == (
        "500.00"
    )


def test_cash_to_a_supervisor_or_the_safe_waits_in_their_queue(d: Desk) -> None:
    shift = _open(d.cashier, "2000")["shift"]
    url = f"/api/payments/shifts/{shift['id']}/handovers"
    receivers = ok(d.cashier.api.get("/api/payments/handover-receivers"))
    names = {r["username"] for r in receivers}
    assert {"sup", "acc", "mgr"} <= names
    assert not names & {"cash", "cash2", "doc"}
    error(
        d.cashier.api.post(url, {"amount": "100", "destination": "supervisor"}),
        409,
        "HANDOVER_TARGET_REQUIRED",
    )
    error(
        d.cashier.api.post(
            url,
            {"amount": "100", "destination": "supervisor", "to_user_id": d.cashier2.user.pk},
        ),
        409,
        "HANDOVER_RECEIVER_INVALID",
    )
    to_sup = ok(
        d.cashier.api.post(
            url, {"amount": "300", "destination": "supervisor", "to_user_id": d.sup.user.pk}
        ),
        201,
    )
    assert to_sup["to_user"]["username"] == "sup"
    to_safe = ok(d.cashier.api.post(url, {"amount": "200", "destination": "safe"}), 201)

    def incoming(who: kit.Actor) -> list[int]:
        body = ok(who.api.get("/api/payments/shifts/current"))
        return [h["id"] for h in body["incoming_handovers"]]

    assert incoming(d.sup) == [to_sup["id"], to_safe["id"]]
    assert incoming(d.accountant) == [to_safe["id"]]
    assert incoming(d.cashier) == []
    assert incoming(d.cashier2) == []
    for handover in (to_sup, to_safe):
        receive = f"/api/payments/handovers/{handover['id']}/receive"
        error(d.cashier.api.post(receive), 409, "HANDOVER_SELF_RECEIPT")
        error(d.cashier2.api.post(receive), 409, "HANDOVER_NOT_YOURS")
    received = ok(d.sup.api.post(f"/api/payments/handovers/{to_sup['id']}/receive"))
    assert received["received_by"]["username"] == "sup"
    ok(d.accountant.api.post(f"/api/payments/handovers/{to_safe['id']}/receive"))
    assert incoming(d.sup) == []
    error(d.doctor.api.get("/api/payments/handover-receivers"), 403, "PERMISSION_DENIED")


def _refundable(d: Desk) -> tuple[kit.InsuredVisit, dict[str, Any]]:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    _open(d.cashier, "1000")
    ok(_pay(d.cashier, iv.patient.pk, inv), 201)
    cn = ok(
        d.cashier.api.post(
            f"/api/billing/invoices/{inv['id']}/credit-notes",
            {
                "lines": [{"invoice_line_id": inv["lines"][1]["id"], "quantity": 1}],
                "reason": "SERVICE_CANCELLED",
            },
        ),
        201,
    )
    outcome = ok(
        d.sup.api.post(f"/api/billing/credit-notes/{cn['id']}/approve", {"open_refund": False})
    )
    assert outcome["refund"] is None
    return iv, outcome["credit_note"]


def test_refund_request_approval_by_another_person_and_cash_payment(d: Desk) -> None:
    iv, cn = _refundable(d)
    assert cn["refundable"] == "600.00"
    error(
        d.cashier.api.post(
            "/api/payments/refunds",
            {"credit_note_id": cn["id"], "amount": "700", "reason": "SERVICE_CANCELLED"},
        ),
        409,
        "REFUND_EXCEEDS_SOURCE",
    )
    refund = ok(
        d.cashier.api.post(
            "/api/payments/refunds",
            {"credit_note_id": cn["id"], "amount": "600", "reason": "SERVICE_CANCELLED"},
        ),
        201,
    )
    assert refund["status"] == "requested"
    error(
        d.cashier.api.post(f"/api/payments/refunds/{refund['id']}/approve", {}),
        403,
        "PERMISSION_DENIED",
    )
    queue = ok(d.sup.api.get("/api/payments/refunds?status=requested"))
    assert [r["id"] for r in queue["items"]] == [refund["id"]]
    approved = ok(d.sup.api.post(f"/api/payments/refunds/{refund['id']}/approve", {}))
    assert approved["status"] == "approved"
    paid = ok(d.cashier.api.post(f"/api/payments/refunds/{refund['id']}/pay"))
    assert paid["status"] == "paid"
    assert paid["paid_by"]["username"] == "cash"
    report = ok(d.cashier.api.get("/api/payments/shifts/current"))["report"]
    assert report["refunds_paid"] == "600.00"
    assert report["expected_cash"] == "4000.00"
    error(
        d.cashier.api.post(f"/api/payments/refunds/{refund['id']}/pay"), 409, "REFUND_NOT_APPROVED"
    )
    assert Payment.objects.filter(patient=iv.patient).count() == 1


def test_supervisor_cannot_approve_a_refund_they_requested(d: Desk) -> None:
    _, cn = _refundable(d)
    refund = ok(
        d.sup.api.post(
            "/api/payments/refunds",
            {"credit_note_id": cn["id"], "amount": "600", "reason": "SERVICE_CANCELLED"},
        ),
        201,
    )
    error(
        d.sup.api.post(f"/api/payments/refunds/{refund['id']}/approve", {}),
        409,
        "SELF_APPROVAL_NOT_ALLOWED",
    )
    rejected = ok(
        d.accountant.api.post(f"/api/payments/refunds/{refund['id']}/reject", {"note": "no"})
    )
    assert rejected["status"] == "rejected"


def test_reference_lists(d: Desk) -> None:
    codes = [b["code"] for b in ok(d.cashier.api.get("/api/payments/banks"))]
    assert "BOK" in codes
    ok(d.cashier.api.get("/api/payments/tills"))
    error(d.doctor.api.get("/api/payments/banks"), 403, "PERMISSION_DENIED")
