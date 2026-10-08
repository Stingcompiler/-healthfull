"""Invoices, coverage, discounts, credit notes and pharmacy sales (ARCHITECTURE 4.5)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import CreditNote, Invoice, InvoiceLine
from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.models import JournalEntry
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients.models import PatientCoverage
from apps.payments import services as pay
from apps.payments.models import Allocation
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


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


def _line(inv: Invoice, service_line: ServiceLine) -> InvoiceLine:
    return inv.lines.get(service_line=service_line)


def _pay_all(inv: Invoice, cashier) -> None:
    shift = pay.current_shift(cashier) or pay.open_shift(cashier, D("0.00"))
    pay.record_payment(
        shift,
        inv.patient,
        "cash",
        billing.invoice_position(inv).outstanding,
        actor=cashier,
        allocations=[(inv, billing.invoice_position(inv).outstanding)],
    )


# --- drafts and pricing ----------------------------------------------------------------------


def test_draft_lists_unbilled_lines_priced_today(doctor, cashier) -> None:
    visit = fin.visit()
    a, c = fin.order(visit, doctor, fin.priced("lab", "120.00"), (fin.priced("drug", "2.50"), 4))
    (cancelled,) = fin.order(visit, doctor, fin.priced())
    orders.cancel_line(cancelled, "PATIENT_REFUSED", doctor)
    assert list(billing.unbilled_lines(visit)) == [a, c]
    draft = billing.create_draft_invoice(visit, cashier)
    assert (draft.status, draft.number, draft.created_by) == ("draft", None, cashier)
    lines = list(draft.lines.order_by("line_no"))
    assert [
        (ln.line_no, ln.service_line, ln.quantity, ln.unit_price, ln.gross) for ln in lines
    ] == [
        (1, a, D("1"), D("120.00"), D("120.00")),
        (2, c, D("4"), D("2.50"), D("10.00")),
    ]
    assert not any(ln.frozen for ln in lines)
    assert (draft.gross_total, draft.patient_total) == (D("130.00"), D("130.00"))
    a.refresh_from_db()
    assert a.billing_status == "unbilled"  # a draft changes no line
    assert not JournalEntry.objects.exists()


def test_draft_refusals(doctor, cashier) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced())
    billing.create_draft_invoice(visit, cashier)
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(visit, cashier, line_ids=[line.pk])
    assert _code(exc) == "LINE_ON_DRAFT_INVOICE"
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(fin.visit(), cashier)
    assert _code(exc) == "INVOICE_EMPTY"
    cancelled_visit = fin.visit(
        status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=cashier,
        cancel_reason=b.reason("visit_cancel"),
    )
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(cancelled_visit, cashier)
    assert _code(exc) == "VISIT_CANCELLED"
    unpriced_visit = fin.visit()
    fin.order(unpriced_visit, doctor, b.service())
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(unpriced_visit, cashier)
    assert _code(exc) == "PRICE_NOT_FOUND"
    (cancelled,) = fin.order(unpriced_visit, doctor, fin.priced())
    orders.cancel_line(cancelled, "ORDER_ERROR", doctor)
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(unpriced_visit, cashier, line_ids=[cancelled.pk])
    assert _code(exc) == "LINE_CANCELLED"


def test_payer_without_effective_price_list(doctor, cashier) -> None:
    contract = fin.PriceList.objects.create(
        code="ACME", name_ar="أكمي", name_en="Acme", kind="payer"
    )
    insurer = fin.payer(percent="80", price_list=contract)
    visit = fin.visit(payer_obj=insurer)
    fin.order(visit, doctor, fin.priced())
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(visit, cashier)
    assert _code(exc) == "NO_EFFECTIVE_PRICE_LIST"


def test_remove_line_and_void_draft(doctor, cashier) -> None:
    visit = fin.visit()
    a, c = fin.order(visit, doctor, fin.priced("lab", "10.00"), fin.priced("lab", "20.00"))
    draft = billing.create_draft_invoice(visit, cashier)
    billing.remove_draft_line(_line(draft, a), actor=cashier)
    draft.refresh_from_db()
    assert draft.patient_total == D("20.00")
    with pytest.raises(DomainError) as exc:
        billing.void_draft(draft, actor=cashier, note=" ")
    assert _code(exc) == "REASON_REQUIRED"
    voided = billing.void_draft(draft, actor=cashier, note="wrong visit")
    assert (voided.status, voided.voided_by, voided.void_note) == ("void", cashier, "wrong visit")
    with pytest.raises(DomainError) as exc:
        billing.void_draft(draft, actor=cashier, note="again")
    assert _code(exc) == "INVOICE_NOT_DRAFT"
    # The lines are free again for a new invoice.
    again = billing.create_draft_invoice(visit, cashier)
    assert set(again.lines.values_list("service_line", flat=True)) == {a.pk, c.pk}


# --- coverage --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "payer_share"),
    [
        ({"percent": "70"}, "7000.00"),
        ({"copay": "1500.00"}, "8500.00"),
        ({"ceiling": "6000.00"}, "6000.00"),
        ({"ceiling": "9000.00", "payer_percent": "80"}, "8000.00"),
    ],
)
def test_coverage_rules_split_the_line(doctor, cashier, rule, payer_share) -> None:
    insurer = fin.payer(**rule)
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "10000.00"))
    inv = fin.invoice(visit, cashier)
    il = _line(inv, line)
    assert il.payer == insurer
    assert il.payer_share == D(payer_share)
    assert il.patient_share == D("10000.00") - D(payer_share)
    assert il.coverage_rule is not None


def test_exclusion_override_and_payer_price_list(doctor, cashier) -> None:
    contract = fin.PriceList.objects.create(
        code="ACME", name_ar="أكمي", name_en="Acme", kind="payer"
    )
    insurer = fin.payer(percent="80", price_list=contract)
    cbc, xray = fin.priced("lab", "100.00"), fin.priced("procedure", "300.00")
    fin.set_price(cbc, "90.00", price_list=contract)  # contract price
    fin.set_price(xray, "250.00", price_list=contract)
    fin.exclude(insurer, xray)
    patient = fin.patient()
    cover = PatientCoverage.objects.create(
        patient=patient, payer=insurer, patient_percent_override=D("10")
    )
    visit = fin.visit(patient, coverage=cover)
    a, x = fin.order(visit, doctor, cbc, xray)
    inv = fin.invoice(visit, cashier)
    la, lx = _line(inv, a), _line(inv, x)
    assert (la.unit_price, la.payer_share, la.patient_share) == (D("90.00"), D("81.00"), D("9.00"))
    assert fin.some(la.price_list_version).price_list == contract
    assert (lx.excluded, lx.payer_share, lx.patient_share) == (True, D("0.00"), D("250.00"))


def test_different_payers_across_lines(doctor, cashier) -> None:
    first, second = fin.payer(percent="50"), fin.payer(percent="100")
    visit = fin.visit(payer_obj=first)
    a, c, cash = fin.order(
        visit,
        doctor,
        fin.priced("lab", "100.00"),
        fin.priced("lab", "60.00"),
        fin.priced("lab", "40.00"),
    )
    ServiceLine.objects.filter(pk=c.pk).update(payer=second)
    ServiceLine.objects.filter(pk=cash.pk).update(payer=None)
    inv = fin.invoice(visit, cashier)
    assert [(_line(inv, x).payer_id, _line(inv, x).payer_share) for x in (a, c, cash)] == [
        (first.pk, D("50.00")),
        (second.pk, D("60.00")),
        (None, D("0.00")),
    ]
    assert ledger.account_balance("AR_PAYER", payer=first) == D("50.00")
    assert ledger.account_balance("AR_PAYER", payer=second) == D("60.00")
    assert ledger.account_balance("AR_PATIENT", patient=visit.patient) == D("90.00")
    # A fully covered line settles at approval and goes straight to the work list.
    c.refresh_from_db()
    assert c.billing_status == "settled"
    assert c.settled_at is not None
    assert list(orders.worklist("lab")) == [c]


def test_preapproval_is_required_at_approval_only(doctor, cashier) -> None:
    insurer = fin.payer(percent="90", preapproval=True)
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("procedure", "1000.00"))
    draft = billing.create_draft_invoice(visit, cashier)
    with pytest.raises(DomainError) as exc:
        billing.approve_invoice(draft, actor=cashier)
    assert _code(exc) == "PREAPPROVAL_REQUIRED"
    billing.set_preapproval_ref(_line(draft, line), " PA-2026-7 ", actor=cashier)
    inv = billing.approve_invoice(draft, actor=cashier)
    assert _line(inv, line).pre_approval_ref == "PA-2026-7"


# --- approval --------------------------------------------------------------------------------


def test_approval_freezes_numbers_posts_and_moves_lines(doctor, cashier) -> None:
    lab_dept = b.department()
    insurer = fin.payer(percent="70", service_kind="lab")
    visit = fin.visit(payer_obj=insurer)
    lab, drug = fin.order(
        visit,
        doctor,
        fin.priced("lab", "1000.00", department=lab_dept),
        fin.priced("drug", "50.00"),
    )
    inv = fin.invoice(visit, cashier)
    assert inv.status == "approved"
    assert str(inv.number).startswith(f"INV-{timezone.localdate().year}-")
    assert (inv.approved_by, inv.priced_on) == (cashier, timezone.localdate())
    assert (inv.gross_total, inv.payer_total, inv.patient_total) == (
        D("1050.00"),
        D("700.00"),
        D("350.00"),
    )
    assert all(ln.frozen and ln.price_list_version_id for ln in inv.lines.all())
    for line in (lab, drug):
        line.refresh_from_db()
        assert (line.billing_status, line.invoiced_at is not None) == ("invoiced", True)
    (entry,) = JournalEntry.objects.filter(source_type="invoice", source_id=inv.pk)
    assert entry.posted_by == cashier
    assert ledger.account_balance("REVENUE", department=lab_dept, service_kind="lab") == D(
        "1000.00"
    )
    assert ledger.account_balance("REVENUE", service_kind="drug") == D("50.00")
    assert ledger.account_balance("AR_PAYER", payer=insurer, invoice=inv) == D("700.00")
    assert ledger.account_balance("AR_PATIENT", patient=visit.patient, invoice=inv) == D("350.00")
    fin.assert_books_balance()
    with pytest.raises(DomainError) as exc:
        billing.approve_invoice(inv, actor=cashier)
    assert _code(exc) == "INVOICE_NOT_DRAFT"
    # Approved invoices are immutable: services refuse, and so does the database.
    with pytest.raises(DomainError) as exc:
        billing.apply_discount(_line(inv, drug), actor=cashier, reason="STAFF", amount=D("1.00"))
    assert _code(exc) == "INVOICE_FROZEN"
    with pytest.raises(DatabaseError, match="INVOICE_FROZEN"), transaction.atomic():
        InvoiceLine.objects.filter(invoice=inv).update(unit_price=D("1.00"))


def test_price_is_frozen_from_the_version_effective_on_approval_day(doctor, cashier) -> None:
    """Invariant 6: a draft made before a price change is approved at the new price."""
    svc = fin.priced("lab", "100.00")
    today = timezone.localdate()
    fin.set_price(svc, "999.00", on=today + timedelta(days=1))  # not effective yet
    visit = fin.visit()
    fin.order(visit, doctor, svc)
    draft = billing.create_draft_invoice(visit, cashier, on=today - timedelta(days=1))
    fin.set_price(svc, "130.00", on=today)  # effective from today
    assert draft.lines.get().unit_price == D("100.00")
    inv = billing.approve_invoice(draft, actor=cashier)
    line = inv.lines.get()
    version = fin.some(line.price_list_version)
    assert (line.unit_price, version.effective_from) == (D("130.00"), today)


def test_zero_patient_share_settles_at_approval(doctor, cashier) -> None:
    visit = fin.visit()
    (free,) = fin.order(visit, doctor, fin.priced("lab", "0.00"))
    fin.invoice(visit, cashier)
    free.refresh_from_db()
    assert free.billing_status == "settled"


# --- discounts -------------------------------------------------------------------------------


def test_discount_within_the_approvers_limit(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab", "200.00"))
    draft = billing.create_draft_invoice(visit, cashier)
    il = _line(draft, line)
    # Cashier limit is 0% by default.
    with pytest.raises(DomainError) as exc:
        billing.apply_discount(il, actor=cashier, reason="HARDSHIP", amount=D("10.00"))
    assert _code(exc) == "DISCOUNT_LIMIT_EXCEEDED"
    # A supervisor (25%) approves the cashier's discount.
    il = billing.apply_discount(
        il, actor=cashier, approver=supervisor, reason="HARDSHIP", percent=25, note="poor"
    )
    assert (il.discount, il.patient_share, il.discount_approved_by) == (
        D("50.00"),
        D("150.00"),
        supervisor,
    )
    assert (fin.code(il.discount_reason), il.discount_note) == ("HARDSHIP", "poor")
    with pytest.raises(DomainError) as exc:
        billing.apply_discount(il, actor=supervisor, reason="HARDSHIP", amount=D("50.01"))
    assert _code(exc) == "DISCOUNT_LIMIT_EXCEEDED"
    with pytest.raises(PermissionRequired):
        billing.apply_discount(
            il, actor=supervisor, approver=cashier, reason="STAFF", amount=D("1")
        )
    manager = fin.staff("manager")  # 100%
    il = billing.apply_discount(il, actor=manager, reason="MANAGEMENT", percent=100, note="board")
    assert il.patient_share == D("0.00")
    inv = billing.approve_invoice(draft, actor=cashier)
    assert inv.discount_total == D("200.00")
    assert ledger.account_balance("DISCOUNT") == D("200.00")
    line.refresh_from_db()
    assert line.billing_status == "settled"
    fin.assert_books_balance()


def test_discount_refusals_and_removal(doctor, supervisor) -> None:
    insurer = fin.payer(percent="80")
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "100.00"))
    draft = billing.create_draft_invoice(visit, supervisor)
    il = _line(draft, line)
    cases = [
        ({"reason": "STAFF"}, "DISCOUNT_AMOUNT_OR_PERCENT"),
        ({"reason": "STAFF", "amount": D("1"), "percent": 1}, "DISCOUNT_AMOUNT_OR_PERCENT"),
        ({"reason": "", "amount": D("1.00")}, "REASON_REQUIRED"),
        ({"reason": "OTHER", "amount": D("1.00")}, "REASON_NOTE_REQUIRED"),
        ({"reason": "STAFF", "amount": D("20.01")}, "DISCOUNT_EXCEEDS_PATIENT_SHARE"),
        ({"reason": "STAFF", "percent": 101}, "INVALID_PERCENT"),
    ]
    for kwargs, code in cases:
        with pytest.raises(DomainError) as exc:
            billing.apply_discount(il, actor=supervisor, **kwargs)  # type: ignore[arg-type]
        assert _code(exc) == code, kwargs
    il = billing.apply_discount(il, actor=supervisor, reason="STAFF", amount=D("5.00"))
    assert (il.discount, il.patient_share, il.payer_share) == (D("5.00"), D("15.00"), D("80.00"))
    il = billing.apply_discount(il, actor=supervisor, reason=None, amount=D("0"))
    assert (il.discount, il.discount_reason, il.discount_approved_by) == (D("0.00"), None, None)


def test_invoice_discount_is_spread_over_lines(doctor, supervisor) -> None:
    visit = fin.visit()
    fin.order(visit, doctor, fin.priced("lab", "100.00"), fin.priced("lab", "200.00"))
    draft = billing.create_draft_invoice(visit, supervisor)
    billing.apply_invoice_discount(draft, actor=supervisor, reason="STAFF", amount=D("30.00"))
    draft.refresh_from_db()
    assert draft.discount_total == D("30.00")
    assert sorted(draft.lines.values_list("discount", flat=True)) == [D("10.00"), D("20.00")]
    with pytest.raises(DomainError) as exc:
        billing.apply_invoice_discount(draft, actor=supervisor, reason="STAFF", percent=26)
    assert _code(exc) == "DISCOUNT_LIMIT_EXCEEDED"
    billing.apply_invoice_discount(draft, actor=supervisor, reason=None, amount=D("0"))
    draft.refresh_from_db()
    assert draft.discount_total == D("0.00")


def test_follow_up_consultation_gets_the_center_discount(doctor, cashier) -> None:
    Policy.objects.update(follow_up_discount_percent=D("50"))
    patient = fin.patient()
    first = fin.visit(patient)
    follow = fin.visit(patient, follow_up_of=first, visit_type="follow_up")
    (fee,) = fin.order(
        follow, doctor, fin.priced("consultation", "300.00"), order_source="consultation_fee"
    )
    inv = fin.invoice(follow, cashier)
    il = _line(inv, fee)
    assert (il.discount, il.patient_share, fin.code(il.discount_reason)) == (
        D("150.00"),
        D("150.00"),
        "FOLLOW_UP",
    )
    assert il.discount_approved_by == cashier


# --- credit notes ----------------------------------------------------------------------------


def test_partial_credit_note_mirrors_and_rounds_exactly(doctor, cashier, supervisor) -> None:
    insurer = fin.payer(percent="33.33")
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, (fin.priced("drug", "10.00"), 3))
    inv = fin.invoice(visit, cashier)
    il = _line(inv, line)
    notes = []
    for _ in range(3):
        cn = billing.create_credit_note(inv, [(il, 1)], actor=supervisor, reason="PRICE_ERROR")
        assert cn.status == "draft"
        notes.append(billing.approve_credit_note(cn, actor=supervisor).credit_note)
    assert sum(n.gross_total for n in notes) == il.gross
    assert sum(n.payer_total for n in notes) == il.payer_share
    assert sum(n.patient_total for n in notes) == il.patient_share
    assert all(str(n.number).startswith("CN-") for n in notes)
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("credited", "cancelled")
    assert fin.code(line.cancel_reason) == "OTHER"
    assert ledger.account_balance("REVENUE") == D("0.00")
    assert ledger.account_balance("AR_PAYER", payer=insurer) == D("0.00")
    fin.assert_books_balance()
    with pytest.raises(DomainError) as exc:
        billing.create_credit_note(inv, [(il, 1)], actor=supervisor, reason="PRICE_ERROR")
    assert _code(exc) == "CREDIT_EXCEEDS_LINE"


def test_credit_note_refusals(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    a, c = fin.order(visit, doctor, fin.priced(), fin.priced())
    draft = billing.create_draft_invoice(visit, cashier, line_ids=[a.pk])
    with pytest.raises(DomainError) as exc:
        billing.create_credit_note(
            draft, [(draft.lines.get(), 1)], actor=supervisor, reason="PRICE_ERROR"
        )
    assert _code(exc) == "INVOICE_NOT_APPROVED"
    inv = billing.approve_invoice(draft, actor=cashier)
    other = fin.invoice(visit, cashier, [c])
    il = _line(inv, a)
    cases = [
        ([], "PRICE_ERROR", "INVOICE_EMPTY"),
        ([(il, 1), (il.pk, 1)], "PRICE_ERROR", "DUPLICATE_LINE"),
        ([(_line(other, c), 1)], "PRICE_ERROR", "UNKNOWN_INVOICE_LINE"),
        ([(il, 2)], "PRICE_ERROR", "CREDIT_EXCEEDS_LINE"),
        ([(il, 0)], "PRICE_ERROR", "INVALID_QUANTITY"),
        ([(il, 1)], "SERVICE_FINISHED", "REASON_UNKNOWN"),
    ]
    for lines, reason, code in cases:
        with pytest.raises(DomainError) as exc:
            billing.create_credit_note(inv, lines, actor=supervisor, reason=reason)  # type: ignore[arg-type]
        assert _code(exc) == code, code
    first = billing.create_credit_note(inv, [(il, 1)], actor=supervisor, reason="PRICE_ERROR")
    second = billing.create_credit_note(inv, [(il, 1)], actor=supervisor, reason="PRICE_ERROR")
    billing.approve_credit_note(first, actor=supervisor)
    with pytest.raises(DomainError) as exc:
        billing.approve_credit_note(second, actor=supervisor)
    assert _code(exc) == "CREDIT_EXCEEDS_LINE"
    with pytest.raises(DomainError) as exc:
        billing.approve_credit_note(first, actor=supervisor)
    assert _code(exc) == "INVOICE_NOT_DRAFT"


def _answered_claim(insurer, accepted: Decimal, *, reason: str = ""):
    """Claim the payer's accrued shares of today and record the payer's answer."""
    from apps.claims import services as claims

    accountant = fin.staff("accountant")
    today = timezone.localdate()
    claim = claims.build_claim(
        payer=insurer, period_start=today, period_end=today, actor=accountant
    )
    claims.submit_claim(claim, actor=accountant)
    cl = claim.lines.get()
    claims.record_responses(
        claim, [claims.ClaimResponse(cl.pk, accepted, reason=reason)], actor=accountant
    )
    cl.refresh_from_db()
    return accountant, cl


def test_claimed_payer_share_cannot_be_credited(doctor, cashier, supervisor) -> None:
    """Once the payer answered and paid its share, the line is corrected through the claim
    (an unanswered claim line is withdrawn by the credit instead, see test_review_fixes)."""
    from apps.claims import services as claims

    insurer = fin.payer(percent="60")
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "100.00"))
    inv = fin.invoice(visit, cashier)
    il = _line(inv, line)
    accountant, _ = _answered_claim(insurer, D("60.00"))
    claims.record_payer_payment(
        payer=insurer,
        amount=D("60.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="PAYER-1",
    )
    with pytest.raises(DomainError) as exc:
        billing.create_credit_note(inv, [(il, 1)], actor=supervisor, reason="COVERAGE_ERROR")
    assert _code(exc) == "CLAIM_LINE_LOCKED"
    with pytest.raises(DomainError) as exc:
        orders.cancel_line(line, "ORDER_ERROR", supervisor)
    assert _code(exc) == "CLAIM_LINE_LOCKED"


def test_rebilled_payer_rejection_adds_to_patient_due(doctor, cashier, supervisor) -> None:
    from apps.claims import services as claims

    insurer = fin.payer(percent="60")
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "100.00"))
    inv = fin.invoice(visit, cashier)
    _pay_all(inv, cashier)
    line.refresh_from_db()
    assert line.billing_status == "settled"
    accountant, cl = _answered_claim(insurer, D("0.00"), reason="not covered")
    claims.resolve_rejection(
        cl, resolution="rebilled", actor=accountant, reason_code="NOT_COVERED", note="rebill"
    )
    position = billing.refresh_settlement(inv)
    assert (position.patient_due, position.outstanding) == (D("100.00"), D("60.00"))
    line.refresh_from_db()
    assert line.billing_status == "invoiced"


def test_full_credit_of_performed_line_and_rebill_correction(doctor, cashier, supervisor):
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("procedure", "500.00"))
    inv = fin.invoice(visit, cashier)
    _pay_all(inv, cashier)
    orders.perform_line(line, doctor)
    # The right price, from tomorrow (a version never starts on a day already priced).
    fin.set_price(line.service, "400.00", on=timezone.localdate() + timedelta(days=1))
    cn = billing.create_credit_note(
        inv, [(_line(inv, line), 1)], actor=supervisor, reason="PRICE_ERROR"
    )
    outcome = billing.approve_credit_note(cn, actor=supervisor, rebill=True)
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("credited", "performed")
    assert outcome.deallocated == D("500.00")
    (replacement,) = outcome.replacements
    assert (replacement.billing_status, replacement.fulfilment_status) == ("unbilled", "performed")
    assert replacement.authorization is not None
    assert replacement.performed_by == doctor
    with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=1)):
        fixed = fin.invoice(visit, cashier, [replacement])
    assert fixed.patient_total == D("400.00")
    # The patient credit pays the corrected invoice.
    shift = fin.some(pay.current_shift(cashier))
    pay.record_payment(shift, visit.patient, "patient_credit", D("400.00"), actor=cashier)
    replacement.refresh_from_db()
    assert replacement.billing_status == "settled"
    assert pay.credit_balance(visit.patient) == D("100.00")
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(visit.patient)


def test_rebill_of_a_cancelled_line_is_a_fresh_request(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab", "80.00"))
    inv = fin.invoice(visit, cashier)
    cn = billing.create_credit_note(
        inv, [(_line(inv, line), 1)], actor=supervisor, reason="DUPLICATE_BILLING"
    )
    outcome = billing.approve_credit_note(cn, actor=supervisor, rebill=True)
    (replacement,) = outcome.replacements
    assert (replacement.billing_status, replacement.fulfilment_status) == ("unbilled", "pending")
    assert replacement.authorization is None
    assert outcome.deallocated == D("0.00")
    assert not Allocation.objects.exists()


# --- pharmacy sale ---------------------------------------------------------------------------


def test_walk_in_pharmacy_sale(cashier) -> None:
    pharmacist = fin.staff("pharmacist")
    patient = fin.patient()
    syrup, gauze = fin.priced("drug", "35.00"), fin.priced("consumable", "5.00")
    with pytest.raises(DomainError) as exc:
        billing.create_pharmacy_sale(patient, [{"service": fin.priced("lab")}], actor=pharmacist)
    assert _code(exc) == "SERVICE_NOT_SALEABLE"
    draft = billing.create_pharmacy_sale(
        patient, [{"service": syrup, "quantity": 2}, {"service": gauze}], actor=pharmacist
    )
    assert draft.visit.visit_type == "pharmacy_sale"
    assert draft.visit.payer is None
    assert draft.patient_total == D("75.00")
    assert set(
        ServiceLine.objects.filter(visit=draft.visit).values_list("order_source", flat=True)
    ) == {"pharmacy_sale"}
    inv = billing.approve_invoice(draft, actor=cashier)
    _pay_all(inv, cashier)
    assert {ln.pk for ln in orders.worklist("drug")} == set(
        inv.lines.filter(kind="drug").values_list("service_line", flat=True)
    )
    fin.assert_books_balance()


def test_invoice_position_of_documents(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    Policy.objects.update(allow_partial_payment=True)
    _a, c = fin.order(visit, doctor, fin.priced("lab", "60.00"), fin.priced("lab", "40.00"))
    inv = fin.invoice(visit, cashier)
    shift = pay.open_shift(cashier, D("0"))
    pay.record_payment(
        shift, visit.patient, "cash", D("70.00"), actor=cashier, allocations=[(inv, D("70.00"))]
    )
    pos = billing.invoice_position(inv)
    assert [(lp.patient_due, lp.patient_paid, lp.settled) for lp in pos.lines] == [
        (D("60.00"), D("60.00"), True),
        (D("40.00"), D("10.00"), False),
    ]
    assert billing.open_invoices(visit.patient) == [(inv, pos)]
    cn = billing.create_credit_note(
        inv, [(_line(inv, c), 1)], actor=supervisor, reason="PRICE_ERROR"
    )
    billing.approve_credit_note(cn, actor=supervisor)
    pos = billing.invoice_position(inv)
    assert (pos.outstanding, pos.over_allocation) == (D("0.00"), D("0.00"))
    assert pay.credit_balance(visit.patient) == D("10.00")
    assert CreditNote.objects.get().patient_total == D("40.00")
    assert billing.open_invoices(visit.patient) == []
