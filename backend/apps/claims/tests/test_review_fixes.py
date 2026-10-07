"""Regression tests for the Phase 1 review: payer money by method, bounced payer payments,
short payments written off, and the claim line backstops (invariants 4 and 7; FEATURES
11.5-11.7).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.payments import services as pay
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _accepted_claim(amount: str = "100.00", accepted: str | None = None):
    """One insured lab line, claimed, submitted and answered (accepted by default)."""
    cashier = fin.staff("cashier")
    accountant = fin.staff("accountant")
    insurer = fin.payer(percent="100.00")
    v = fin.visit(payer_obj=insurer)
    fin.order(v, fin.staff("doctor"), fin.priced("lab", amount))
    fin.invoice(v, cashier)
    today = timezone.localdate()
    claim = cs.build_claim(payer=insurer, period_start=today, period_end=today, actor=accountant)
    cs.submit_claim(claim, actor=accountant)
    cl = claim.lines.get()
    cs.record_responses(
        claim,
        [cs.ClaimResponse(cl.pk, D(accepted or amount), reason="deduction")],
        actor=accountant,
    )
    cl.refresh_from_db()
    return accountant, insurer, claim, cl


def _reconciles(insurer) -> None:
    row = cs.payer_receivables(payer=insurer).get(insurer.pk)
    assert (row.receivable if row else D(0)) == ledger.account_balance("AR_PAYER", payer=insurer)


def test_payer_cash_goes_into_the_recorders_drawer() -> None:
    """Review: payer cash was booked Dr BANK and never reached any shift drawer."""
    accountant, insurer, _claim, _cl = _accepted_claim()
    with pytest.raises(DomainError) as exc:
        cs.record_payer_payment(
            payer=insurer,
            amount=D("100.00"),
            received_on=timezone.localdate(),
            actor=accountant,
            method="cash",
        )
    assert exc.value.code == "SHIFT_NOT_OPEN"
    shift = pay.open_shift(accountant, D("0.00"))
    cs.record_payer_payment(
        payer=insurer,
        amount=D("100.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        method="cash",
    )
    assert pay.expected_cash(shift) == D("100.00")
    assert ledger.account_balance("CASH", shift=shift) == D("100.00")
    assert ledger.account_balance("BANK") == D("0.00")
    _reconciles(insurer)


def test_payer_cheque_waits_in_bank_pending_until_it_clears() -> None:
    """Review: an uncleared cheque was booked as confirmed bank money."""
    accountant, insurer, _claim, _cl = _accepted_claim()
    payment = cs.record_payer_payment(
        payer=insurer,
        amount=D("100.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        method="cheque",
        bank=b.bank(),
        reference="CHQ-1",
    )
    assert ledger.account_balance("BANK_PENDING") == D("100.00")
    assert ledger.account_balance("BANK") == D("0.00")
    cs.clear_payer_cheque(payment, actor=accountant)
    assert ledger.account_balance("BANK_PENDING") == D("0.00")
    assert ledger.account_balance("BANK") == D("100.00")
    with pytest.raises(DomainError) as exc:
        cs.clear_payer_cheque(payment, actor=accountant)
    assert exc.value.code == "PAYMENT_NOT_PENDING"
    _reconciles(insurer)


def test_bounced_payer_payment_is_reversed_and_owed_again() -> None:
    accountant, insurer, _claim, cl = _accepted_claim()
    payment = cs.record_payer_payment(
        payer=insurer,
        amount=D("100.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="TRX-1",
    )
    assert cs.claim_line_state(cl).receivable == 0
    with pytest.raises(DomainError) as exc:
        cs.reverse_payer_payment(payment, actor=accountant, note=" ")
    assert exc.value.code == "REASON_REQUIRED"
    cs.reverse_payer_payment(payment, actor=accountant, note="returned by the bank")
    cl.refresh_from_db()
    assert cs.claim_line_state(cl).receivable == D("100.00")
    assert ledger.account_balance("BANK") == D("0.00")
    assert ledger.account_balance("AR_PAYER", payer=insurer) == D("100.00")
    with pytest.raises(DomainError) as exc:
        cs.reverse_payer_payment(payment, actor=accountant, note="again")
    assert exc.value.code == "PAYMENT_NOT_REVERSIBLE"
    _reconciles(insurer)


def test_short_paid_accepted_amount_is_written_off_and_the_claim_closes() -> None:
    """Review: an accepted amount the payer short-paid could never be cleared, so the claim
    could never close (CLAIM_NOT_SETTLED) and AR_PAYER kept the shortfall."""
    accountant, insurer, claim, cl = _accepted_claim()
    cs.record_payer_payment(
        payer=insurer,
        amount=D("90.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="TRX-2",
    )
    with pytest.raises(DomainError) as exc:
        cs.close_claim(claim, actor=accountant)
    assert exc.value.code == "CLAIM_NOT_SETTLED"
    with pytest.raises(DomainError) as exc:
        cs.write_off_shortfall(cl, D("10.01"), actor=accountant, reason_code="SMALL_BALANCE")
    assert exc.value.code == "CLAIM_AMOUNT_INVALID"
    cs.write_off_shortfall(
        cl, D("10.00"), actor=accountant, reason_code="SMALL_BALANCE", note="withholding"
    )
    cl.refresh_from_db()
    assert (cl.written_off_amount, cl.written_off_by) == (D("10.00"), accountant)
    assert ledger.account_balance("AR_PAYER", payer=insurer) == D("0.00")
    assert ledger.account_balance("WRITE_OFF", payer=insurer) == D("10.00")
    _reconciles(insurer)
    assert cs.close_claim(claim, actor=accountant).status == "closed"


def test_db_freezes_claim_lines_of_a_closed_claim() -> None:
    """Review: a line of a closed, paid claim could be set to 'withdrawn', which made its
    payer share creditable a second time."""
    accountant, insurer, claim, cl = _accepted_claim()
    cs.record_payer_payment(
        payer=insurer,
        amount=D("100.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="TRX-3",
    )
    cs.close_claim(claim, actor=accountant)
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=cl.pk).update(
            status="withdrawn",
            withdrawn_at=timezone.now(),
            withdrawn_by=accountant,
            withdraw_note="x",
        ),
        "CLAIM_FINAL",
    )
    b.sql_rejects("DELETE FROM claims_claimline WHERE id = %s", [cl.pk], "CLAIM_LINE_PERMANENT")


def test_db_keeps_a_paid_answer_and_its_amounts() -> None:
    accountant, insurer, claim, cl = _accepted_claim()
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=cl.pk).update(amount_claimed=D("1.00")),
        "CLAIM_LINE_READONLY",
    )
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=cl.pk).update(accepted_amount=D("1.00")),
        "CLAIM_LINE_READONLY",
    )
    cs.record_payer_payment(
        payer=insurer,
        amount=D("40.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank(),
        reference="TRX-4",
    )
    # With payer money on it, an answered line is not withdrawn.
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=cl.pk).update(
            status="withdrawn",
            withdrawn_at=timezone.now(),
            withdrawn_by=accountant,
            withdraw_note="x",
        ),
        "CLAIM_LINE_TRANSITION",
    )
    assert Claim.objects.get(pk=claim.pk).status == "responded"
