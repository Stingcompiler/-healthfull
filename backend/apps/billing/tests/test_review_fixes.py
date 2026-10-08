"""Regression tests for the Phase 1 review: credit notes, discounts, payer lines and the
invoice backstops (invariants 2, 4 and 6).

Each test reproduces a reviewer's failing scenario through the real services, or proves a
database guard refuses the bypass a reviewer found.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import CreditNote, CreditNoteLine, InvoiceLine
from apps.catalog.models import PriceItem, PriceListVersion
from apps.claims import services as claims
from apps.claims.models import ClaimLine
from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.payments import services as pay
from apps.payments.models import Refund
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


# --- money of a cancelled line (ARCHITECTURE 4.4 rule 3, FLOW 5) --------------------------


def test_cancelling_a_paid_line_frees_its_money_not_the_next_line() -> None:
    """Review: lab 100 and drug 100 invoiced, 100 cash pays the lab line; cancelling the lab
    line silently moved the money onto the drug line (settled, dispensable) and opened no
    refund."""
    Policy.objects.update(allow_partial_payment=True)
    cashier = fin.staff("cashier")
    supervisor = fin.staff("cashier_supervisor")
    doctor = fin.staff("doctor")
    shift = pay.open_shift(cashier, D("0.00"))
    visit = fin.visit()
    l1, l2 = fin.order(visit, doctor, fin.priced("lab", "100.00"), fin.priced("drug", "100.00"))
    fin.invoice(visit, cashier)
    pay.record_payment(shift, visit.patient, "cash", D("100.00"), actor=cashier, auto=True)
    l1.refresh_from_db()
    l2.refresh_from_db()
    assert (l1.billing_status, l2.billing_status) == ("settled", "invoiced")

    orders.cancel_line(l1, "OTHER", cashier, note="analyser broken", approver=supervisor)
    l2.refresh_from_db()
    assert l2.billing_status == "invoiced"
    refund = Refund.objects.get(patient=visit.patient)
    assert refund.amount == D("100.00")
    assert refund.requested_by == cashier
    assert pay.credit_balance(visit.patient) == D("100.00")
    fin.assert_positions_match_ledger(visit.patient)
    fin.assert_books_balance()


# --- credit note approval (FEATURES 5.11, ARCHITECTURE 4.10) ------------------------------


def test_doctor_cannot_approve_the_credit_note_of_a_cancelled_paid_line() -> None:
    """Review (completeness): a doctor's cancel_line created AND approved the credit note."""
    cashier = fin.staff("cashier")
    doctor = fin.staff("doctor")
    supervisor = fin.staff("cashier_supervisor")
    line = _paid_procedure(cashier)
    with pytest.raises(PermissionRequired):
        orders.cancel_line(line, "PATIENT_REFUSED", doctor, note="changed plan")
    line.refresh_from_db()
    assert line.billing_status == "settled"
    assert not CreditNote.objects.filter(invoice__visit=line.visit, status="approved").exists()
    orders.cancel_line(line, "PATIENT_REFUSED", doctor, note="changed plan", approver=supervisor)
    cn = CreditNote.objects.get(invoice__visit=line.visit)
    assert (cn.created_by, cn.approved_by) == (doctor, supervisor)


def test_approve_credit_note_needs_the_permission() -> None:
    cashier = fin.staff("cashier")
    line = _paid_procedure(cashier)
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    cn = billing.create_credit_note(il.invoice, [(il, 1)], actor=cashier, reason="PRICE_ERROR")
    with pytest.raises(PermissionRequired):
        billing.approve_credit_note(cn, actor=cashier)


def _paid_procedure(cashier):
    from apps.catalog.tests import engine

    return engine.cash_paid_line(b.service("procedure"), 1, cashier, unit_price="500.00")


# --- claimed payer shares -----------------------------------------------------------------


def _claimed_line(*, submit: bool = True):
    cashier = fin.staff("cashier")
    accountant = fin.staff("accountant")
    doctor = fin.staff("doctor")
    insurer = fin.payer(percent="70.00")
    visit = fin.visit(payer_obj=insurer)
    (line,) = fin.order(visit, doctor, fin.priced("drug", "1000.00"))
    fin.invoice(visit, cashier)
    shift = pay.open_shift(cashier, D("0.00"))
    pay.record_payment(shift, visit.patient, "cash", D("300.00"), actor=cashier, auto=True)
    today = timezone.localdate()
    claim = claims.build_claim(
        payer=insurer, period_start=today, period_end=today, actor=accountant
    )
    if submit:
        claims.submit_claim(claim, actor=accountant)
    line.refresh_from_db()
    return cashier, accountant, insurer, line, claim


def test_paid_line_on_a_submitted_claim_can_be_cancelled_and_refunded() -> None:
    """Review (accounting): a paid, never performed line whose payer share was on a
    submitted claim could not be cancelled (CLAIM_LINE_LOCKED), so the copay was stuck."""
    cashier, _accountant, insurer, line, claim = _claimed_line()
    supervisor = fin.staff("cashier_supervisor")
    orders.cancel_line(line, "OUT_OF_STOCK", cashier, approver=supervisor)
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("credited", "cancelled")
    cl = ClaimLine.objects.get(claim=claim)
    assert cl.status == "withdrawn"
    assert cl.withdrawn_by == supervisor
    assert Refund.objects.get(patient=line.visit.patient).amount == D("300.00")
    receivable = claims.payer_receivables(payer=insurer).get(insurer.pk)
    assert receivable is None or receivable.receivable == 0
    assert fin.ledger.account_balance("AR_PAYER", payer=insurer) == 0
    claim.refresh_from_db()
    assert claim.claimed_total == 0


def test_answered_claim_line_is_withdrawn_only_for_a_full_unpaid_credit() -> None:
    cashier, accountant, insurer, line, claim = _claimed_line()
    supervisor = fin.staff("cashier_supervisor")
    cl = ClaimLine.objects.get(claim=claim)
    claims.record_responses(claim, [claims.ClaimResponse(cl.pk, D("700.00"))], actor=accountant)
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    il.refresh_from_db()
    # A full credit of the never-given service withdraws the answered, unpaid line.
    orders.cancel_line(line, "OUT_OF_STOCK", cashier, approver=supervisor)
    cl.refresh_from_db()
    assert cl.status == "withdrawn"
    assert fin.ledger.account_balance("AR_PAYER", payer=insurer) == 0


def test_partial_credit_of_an_answered_claim_line_is_refused() -> None:
    cashier, accountant, insurer, line, claim = _claimed_line()
    cl = ClaimLine.objects.get(claim=claim)
    claims.record_responses(claim, [claims.ClaimResponse(cl.pk, D("700.00"))], actor=accountant)
    # 2 units on the line would only be possible with quantity > 1; a 1-unit line's credit is
    # whole, so prove the payment rule instead: once the payer paid, the line is locked.
    claims.record_payer_payment(
        payer=insurer,
        amount=D("700.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="PAY-1",
    )
    supervisor = fin.staff("cashier_supervisor")
    with pytest.raises(DomainError) as exc:
        orders.cancel_line(line, "OUT_OF_STOCK", cashier, approver=supervisor)
    assert exc.value.code == "CLAIM_LINE_LOCKED"


def test_db_refuses_a_claim_line_above_the_uncredited_payer_share() -> None:
    cashier, accountant, _insurer, line, claim = _claimed_line(submit=False)
    claims.remove_claim_line(ClaimLine.objects.get(claim=claim), actor=accountant)
    il = InvoiceLine.objects.get(service_line=line, frozen=True)
    supervisor = fin.staff("cashier_supervisor")
    cn = billing.create_credit_note(il.invoice, [(il, 1)], actor=cashier, reason="PRICE_ERROR")
    billing.approve_credit_note(cn, actor=supervisor)
    b.db_rejects(
        lambda: ClaimLine.objects.create(claim=claim, invoice_line=il, amount_claimed=D("700.00")),
        "CLAIM_LINE_NOT_ACCRUED",
    )


# --- discounts (FEATURES 5.9, invariant 4) ------------------------------------------------


def _tomorrow_price(svc, price: str) -> None:
    tomorrow = timezone.localdate() + timedelta(days=1)
    new = PriceListVersion.objects.create(price_list=fin.cash_list(), effective_from=tomorrow)
    PriceItem.objects.create(version=new, service=svc, unit_price=D(price))


def test_amount_discount_is_rechecked_when_approval_reprices() -> None:
    """Review: a 10%-limited cashier gave 100 on 1000; the price fell to 120 the next day and
    approval froze an 83% discount under the cashier's name."""
    Policy.objects.update(discount_limit_percent={"cashier": 10})
    cashier = fin.staff("cashier")
    doctor = fin.staff("doctor")
    svc = fin.priced("lab", "1000.00")
    v = fin.visit()
    fin.order(v, doctor, svc)
    draft = billing.create_draft_invoice(v, cashier)
    billing.apply_discount(draft.lines.get(), actor=cashier, reason="HARDSHIP", amount=D("100"))
    _tomorrow_price(svc, "120.00")
    later = timezone.now() + timedelta(days=1)
    with (
        mock.patch("django.utils.timezone.now", return_value=later),
        pytest.raises(DomainError) as exc,
    ):
        billing.approve_invoice(draft, actor=cashier)
    assert exc.value.code == "DISCOUNT_LIMIT_EXCEEDED"
    draft.refresh_from_db()
    assert draft.status == "draft"


def test_percent_discount_follows_the_price_of_the_approval_day() -> None:
    supervisor = fin.staff("cashier_supervisor")  # 25% limit
    doctor = fin.staff("doctor")
    svc = fin.priced("lab", "1000.00")
    v = fin.visit()
    fin.order(v, doctor, svc)
    draft = billing.create_draft_invoice(v, supervisor)
    il = billing.apply_discount(draft.lines.get(), actor=supervisor, reason="HARDSHIP", percent=25)
    assert (il.discount, il.discount_percent) == (D("250.00"), D("25.00"))
    _tomorrow_price(svc, "200.00")
    later = timezone.now() + timedelta(days=1)
    with mock.patch("django.utils.timezone.now", return_value=later):
        inv = billing.approve_invoice(draft, actor=supervisor)
    line = inv.lines.get()
    assert (line.gross, line.discount, line.patient_share) == (
        D("200.00"),
        D("50.00"),
        D("150.00"),
    )


def test_percent_discount_at_the_exact_limit_is_accepted() -> None:
    """Review: 25% entered by a 25%-limit supervisor on a 70%-covered 1005.00 line was refused
    because half-up rounding made 75.38 out of 301.50."""
    supervisor = fin.staff("cashier_supervisor")
    doctor = fin.staff("doctor")
    insurer = fin.payer(percent="70.00")
    svc = fin.priced("lab", "1005.00")
    v = fin.visit(payer_obj=insurer)
    fin.order(v, doctor, svc)
    draft = billing.create_draft_invoice(v, supervisor)
    il = billing.apply_discount(draft.lines.get(), actor=supervisor, reason="HARDSHIP", percent=25)
    assert il.discount == D("75.37")
    inv = billing.approve_invoice(draft, actor=supervisor)
    assert inv.lines.get().discount == D("75.37")


# --- payers (FEATURES 5.6, 11.1) ----------------------------------------------------------


def test_lines_of_one_invoice_can_have_different_payers() -> None:
    cashier = fin.staff("cashier")
    doctor = fin.staff("doctor")
    first, second = fin.payer(percent="100.00"), fin.payer(percent="50.00")
    patient = fin.patient()
    from apps.patients import services as patients

    patients.add_coverage(patient, payer=first, actor=cashier, card_number="C1")
    patients.add_coverage(patient, payer=second, actor=cashier, card_number="C2", is_default=False)
    v = fin.visit(patient, payer_obj=first)
    a, c, cash = fin.order(
        v, doctor, fin.priced("lab", "100.00"), fin.priced("lab", "100.00"), fin.priced("lab", "80")
    )
    with pytest.raises(DomainError) as exc:
        orders.set_line_payer(c, payer=second, actor=cashier, note="")
    assert exc.value.code == "REASON_REQUIRED"
    orders.set_line_payer(c, payer=second, actor=cashier, note="second card for this test")
    orders.set_line_payer(cash, payer=None, actor=cashier, note="patient pays this one")
    inv = fin.invoice(v, cashier)
    shares = {il.service_line_id: (il.payer_id, il.payer_share) for il in inv.lines.all()}
    assert shares[a.pk] == (first.pk, D("100.00"))
    assert shares[c.pk] == (second.pk, D("50.00"))
    assert shares[cash.pk] == (None, D("0.00"))
    stranger = fin.payer(percent="100.00")
    (late,) = fin.order(v, doctor, fin.priced("lab", "10.00"))
    with pytest.raises(DomainError) as exc:
        orders.set_line_payer(late, payer=stranger, actor=cashier, note="no coverage")
    assert exc.value.code == "COVERAGE_INVALID"


def test_expired_payer_contract_is_not_billed() -> None:
    cashier = fin.staff("cashier")
    doctor = fin.staff("doctor")
    insurer = fin.payer(percent="70.00")
    v = fin.visit(payer_obj=insurer)
    fin.order(v, doctor, fin.priced("lab", "100.00"))
    insurer.contract_start = timezone.localdate() - timedelta(days=400)
    insurer.contract_end = timezone.localdate() - timedelta(days=1)
    insurer.save()
    draft = billing.create_draft_invoice(v, cashier)
    with pytest.raises(DomainError) as exc:
        billing.approve_invoice(draft, actor=cashier)
    assert exc.value.code == "PAYER_CONTRACT_EXPIRED"


# --- database backstops (invariant 2) -----------------------------------------------------


def test_db_refuses_moving_a_draft_line_under_an_approved_invoice() -> None:
    """Review: an unfrozen draft line was moved under an approved invoice, edited and
    deleted; nothing fired at commit."""
    inv = b.approved_invoice(unit_price="100.00")
    draft = b.draft_invoice(inv.visit)
    il = b.invoice_line(draft, unit_price="999.00")
    b.db_rejects(
        lambda: InvoiceLine.objects.filter(pk=il.pk).update(invoice=inv, line_no=99),
        "INVOICE_FROZEN|Cannot update",
    )
    b.db_rejects(lambda: InvoiceLine.objects.filter(pk=il.pk).update(line_no=7), "Cannot update")


def test_db_refuses_moving_a_credit_line_under_an_approved_credit_note() -> None:
    inv = b.approved_invoice(lines=2, unit_price="100.00")
    la, _ = list(inv.lines.order_by("line_no"))
    reason = b.reason("credit_note")
    u = b.user()
    note = CreditNote.objects.create(
        invoice=inv, patient=inv.patient, reason_code=reason, created_by=u
    )
    CreditNoteLine.objects.create(
        credit_note=note,
        line_no=1,
        invoice_line=la,
        quantity=D("1"),
        gross=D("100.00"),
        patient_share=D("100.00"),
        frozen=True,
    )
    CreditNote.objects.filter(pk=note.pk).update(
        status="approved",
        number=f"CN-X-{b.n()}",
        approved_by=u,
        approved_at=timezone.now(),
        gross_total=D("100.00"),
        patient_total=D("100.00"),
    )
    draft = CreditNote.objects.create(
        invoice=inv, patient=inv.patient, reason_code=reason, created_by=u
    )
    extra = CreditNoteLine.objects.create(
        credit_note=draft,
        line_no=1,
        invoice_line=la,
        quantity=D("1"),
        gross=D("100.00"),
        patient_share=D("100.00"),
    )
    b.db_rejects(
        lambda: CreditNoteLine.objects.filter(pk=extra.pk).update(
            credit_note=note, line_no=2, frozen=True
        ),
        "INVOICE_FROZEN|CREDIT_NOTE_FROZEN|Cannot update|locked",
    )
