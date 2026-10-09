"""Regression tests of the cashier review findings, through the API (ADR 0008).

* A credit note is approved by someone other than the person who drafted it.
* A transfer is confirmed by someone other than the person who took it.
* A rejection after close needs the rejecting user's own open shift, for the supervisor and
  the accountant alike; the queue says so per row.
* The shift report lists the cashier's line cancellations and voided drafts.
* Money inputs refuse a third decimal instead of rounding it away.
* The lookup and the handover receivers do not issue a query per row.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

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


def _transfer(d: Desk, who: kit.Actor, reference: str) -> tuple[kit.InsuredVisit, dict[str, Any]]:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    body = {
        "patient_id": iv.patient.pk,
        "method": "bank_transfer",
        "bank": "BOK",
        "reference": reference,
        "amount": inv["outstanding"],
        "allocations": [{"invoice_id": inv["id"], "amount": inv["outstanding"]}],
    }
    return iv, ok(who.api.post("/api/payments/payments", body), 201)


def _queue(who: kit.Actor) -> dict[int, dict[str, Any]]:
    items = ok(who.api.get("/api/payments/transfers"))["items"]
    return {x["payment"]["id"]: x for x in items}


# --- credit notes: a second person approves (FEATURES 5.11) ----------------------------------


def test_the_drafter_of_a_credit_note_never_approves_it(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    inv = _approved(d, iv)
    cn = ok(
        d.sup.api.post(
            f"/api/billing/invoices/{inv['id']}/credit-notes",
            {
                "lines": [{"invoice_line_id": inv["lines"][1]["id"], "quantity": 1}],
                "reason": "PRICE_ERROR",
            },
        ),
        201,
    )
    url = f"/api/billing/credit-notes/{cn['id']}/approve"
    error(d.sup.api.post(url, {"open_refund": False}), 409, "CREDIT_NOTE_SELF_APPROVAL")
    error(d.sup.api.post(url, {"rebill": True}), 409, "CREDIT_NOTE_SELF_APPROVAL")
    detail = ok(d.sup.api.get(f"/api/billing/credit-notes/{cn['id']}"))
    assert (detail["status"], detail["approved_by"]) == ("draft", None)
    outcome = ok(d.accountant.api.post(url, {"open_refund": False}))
    assert outcome["credit_note"]["status"] == "approved"
    assert outcome["credit_note"]["created_by"]["username"] == "sup"
    assert outcome["credit_note"]["approved_by"]["username"] == "acc"


# --- transfers: a second person confirms (FEATURES 6.3) --------------------------------------


def test_a_supervisor_never_confirms_a_transfer_they_took(d: Desk) -> None:
    _open(d.sup)
    _, own = _transfer(d, d.sup, "SELF-1")
    assert _queue(d.sup)[own["id"]]["self_recorded"] is True
    assert _queue(d.accountant)[own["id"]]["self_recorded"] is False
    error(
        d.sup.api.post(f"/api/payments/payments/{own['id']}/confirm", {"note": "I saw it"}),
        409,
        "SELF_CONFIRMATION_NOT_ALLOWED",
    )
    confirmed = ok(
        d.accountant.api.post(f"/api/payments/payments/{own['id']}/confirm", {"note": "statement"})
    )
    assert (confirmed["verification"], confirmed["verified_by"]["username"]) == (
        "confirmed",
        "acc",
    )


# --- rejection after close needs the rejecting user's open shift (FEATURES 6.8) --------------


def test_accountant_rejects_while_the_shift_is_open_but_not_after_close(d: Desk) -> None:
    shift = _open(d.cashier)["shift"]
    _, early = _transfer(d, d.cashier, "ACC-1")
    _, late = _transfer(d, d.cashier, "ACC-2")
    row = _queue(d.accountant)[early["id"]]
    assert (row["reject_needs_open_shift"], row["self_recorded"]) == (False, False)
    rejected = ok(
        d.accountant.api.post(
            f"/api/payments/payments/{early['id']}/reject", {"reason": "NOT_RECEIVED"}
        )
    )
    # The original shift is open: the effect stays there, no reversal row is needed.
    assert (rejected["payment"]["verification"], rejected["reversal"]) == ("rejected", None)

    ok(d.cashier.api.post(f"/api/payments/shifts/{shift['id']}/close", {"counted": "0"}))
    assert _queue(d.accountant)[late["id"]]["reject_needs_open_shift"] is True
    assert _queue(d.sup)[late["id"]]["reject_needs_open_shift"] is True
    error(
        d.accountant.api.post(
            f"/api/payments/payments/{late['id']}/reject", {"reason": "NOT_RECEIVED"}
        ),
        409,
        "SHIFT_NOT_OPEN",
    )
    # Accountants hold no till; the screen sends them to a supervisor with an open shift.
    error(
        d.accountant.api.post("/api/payments/shifts", {"opening_float": "0"}),
        403,
        "PERMISSION_DENIED",
    )
    sup_shift = _open(d.sup)["shift"]
    assert _queue(d.sup)[late["id"]]["reject_needs_open_shift"] is False
    assert _queue(d.accountant)[late["id"]]["reject_needs_open_shift"] is True
    done = ok(
        d.sup.api.post(f"/api/payments/payments/{late['id']}/reject", {"reason": "NOT_RECEIVED"})
    )
    assert done["reversal"]["shift_id"] == sup_shift["id"]


# --- the shift report lists desk cancellations (FEATURES 7.3, FLOW 9) ------------------------


def test_shift_report_lists_line_cancellations_and_voided_drafts(d: Desk) -> None:
    shift = _open(d.cashier)["shift"]
    iv = kit.insured_visit(d.doctor.user)
    draft = ok(d.cashier.api.post("/api/billing/invoices", {"visit_id": iv.visit.pk}), 201)
    ok(
        d.cashier.api.post(
            f"/api/billing/invoices/{draft['id']}/lines/{draft['lines'][0]['id']}/cancel",
            {"reason": "PATIENT_REFUSED"},
        )
    )
    ok(d.cashier.api.post(f"/api/billing/invoices/{draft['id']}/void", {"note": "wrong visit"}))
    # Someone else's cancellation is not this cashier's.
    other = kit.insured_visit(d.doctor.user)
    other_draft = ok(d.sup.api.post("/api/billing/invoices", {"visit_id": other.visit.pk}), 201)
    ok(
        d.sup.api.post(
            f"/api/billing/invoices/{other_draft['id']}/lines/{other_draft['lines'][0]['id']}"
            "/cancel",
            {"reason": "PATIENT_REFUSED"},
        )
    )

    report = ok(d.cashier.api.get(f"/api/payments/shifts/{shift['id']}"))
    assert [(r["code"], r["count"]) for r in report["line_cancellations"]] == [
        ("PATIENT_REFUSED", 1)
    ]
    assert report["line_cancellations"][0]["reason"]["code"] == "PATIENT_REFUSED"
    assert [(v["invoice_id"], v["note"]) for v in report["voided_drafts"]] == [
        (draft["id"], "wrong visit")
    ]
    closed = ok(d.cashier.api.post(f"/api/payments/shifts/{shift['id']}/close", {"counted": "0"}))
    assert closed["frozen"] is True
    assert closed["line_cancellations"] == report["line_cancellations"]
    assert closed["voided_drafts"] == report["voided_drafts"]


# --- money inputs keep two decimals (ARCHITECTURE 4.3) ----------------------------------------


def test_a_third_decimal_is_refused_not_rounded(d: Desk) -> None:
    error(
        d.cashier.api.post("/api/payments/shifts", {"opening_float": "100.005"}),
        422,
        "VALIDATION_ERROR",
    )
    error(
        d.cashier.api.post("/api/payments/shifts", {"opening_float": "١٠٠٫٠٠٥"}),
        422,
        "VALIDATION_ERROR",
    )
    error(
        d.cashier.api.post("/api/payments/shifts", {"opening_float": "1,5"}),
        409,
        "INVALID_AMOUNT",
    )
    report = _open(d.cashier, "١٠٠٫٥")
    assert report["shift"]["opening_float"] == "100.50"


# --- read models do not scale their queries with rows ----------------------------------------


def _queries(fn: Any) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def test_lookup_queries_do_not_grow_with_invoices(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    _approved(d, iv)
    url = f"/api/billing/lookup?q={iv.patient.file_no}"
    one = _queries(lambda: ok(d.cashier.api.get(url)))
    from apps.payments.tests import fin

    for _ in range(3):
        visit = fin.visit(iv.patient, payer_obj=iv.payer)
        fin.order(visit, d.doctor.user, fin.priced("lab", "1000.00"))
        inv = ok(d.cashier.api.post("/api/billing/invoices", {"visit_id": visit.pk}), 201)
        ok(d.cashier.api.post(f"/api/billing/invoices/{inv['id']}/approve"))
    body = ok(d.cashier.api.get(url))
    assert len(body["items"][0]["visits"]) >= 4
    assert _queries(lambda: ok(d.cashier.api.get(url))) <= one + 4


def test_handover_receivers_query_count_does_not_grow_with_staff(d: Desk, make_user: Any) -> None:
    url = "/api/payments/handover-receivers"
    before = _queries(lambda: ok(d.cashier.api.get(url)))
    for n in range(6):
        make_user(f"nurse{n}", roles=["nurse"])
    names = [u["username"] for u in ok(d.cashier.api.get(url))]
    assert "nurse0" not in names
    assert {"sup", "acc", "mgr"} <= set(names)
    assert _queries(lambda: ok(d.cashier.api.get(url))) <= before + 1
