"""A payer payment allocated per claim batch (FEATURES 11.6, invariant 7).

The accountant enters what the payer's remittance advice says it paid for each claim; the
service spreads each amount over that claim's accepted, unpaid lines, oldest first, under the
same locks and checks as line allocations, then posts Dr BANK / Cr AR_PAYER.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine, PayerPaymentAllocation
from apps.claims.tests.test_services import ar_payer, insured_invoice, insured_payer, reconciles
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from domain.errors import DomainError

pytestmark = pytest.mark.django_db

D = Decimal


def _accepted_claim(payer, prices, cashier, accountant, version) -> Claim:
    """A claim of ``prices`` (payer pays 70%) submitted and fully accepted."""
    insured_invoice(payer, prices, cashier, version)
    today = timezone.localdate()
    claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    cs.submit_claim(claim, actor=accountant)
    lines = list(claim.lines.order_by("id"))
    return cs.record_responses(
        claim, [cs.ClaimResponse(cl.pk, cl.amount_claimed) for cl in lines], actor=accountant
    )


def _allocated(payment) -> list[tuple[int, Decimal]]:
    return list(
        PayerPaymentAllocation.objects.filter(payer_payment=payment)
        .order_by("claim_line_id")
        .values_list("claim_line_id", "amount")
    )


def test_amounts_per_claim_spread_over_their_own_lines(cashier, accountant, price_version) -> None:
    payer = insured_payer(70)
    first = _accepted_claim(payer, ["100.00", "50.00"], cashier, accountant, price_version)
    second = _accepted_claim(payer, ["10.00"], cashier, accountant, price_version)
    a, c = list(first.lines.order_by("id"))
    (d,) = list(second.lines.order_by("id"))
    assert ar_payer(payer) == D("112.00")
    bank_before = ledger.account_balance("BANK")

    payment = cs.record_payer_payment(
        payer=payer,
        amount=D("80.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=b.bank("BOK"),
        reference="RA-77",
        claim_amounts={first.pk: D("73.00"), second.pk: D("7.00")},
    )
    # The first claim's oldest line is paid in full before its second line gets anything.
    assert _allocated(payment) == [(a.pk, D("70.00")), (c.pk, D("3.00")), (d.pk, D("7.00"))]
    assert set(
        PayerPaymentAllocation.objects.filter(payer_payment=payment).values_list(
            "claim_id", flat=True
        )
    ) == {first.pk, second.pk}
    assert ar_payer(payer) == D("32.00")
    assert ledger.account_balance("BANK") - bank_before == D("80.00")
    assert cs.payer_receivables(payer=payer)[payer.pk].collected == D("80.00")
    reconciles(payer)


def test_amount_per_claim_is_checked(cashier, accountant, price_version) -> None:
    payer, other = insured_payer(70), insured_payer(70)
    claim = _accepted_claim(payer, ["100.00"], cashier, accountant, price_version)
    foreign = _accepted_claim(other, ["100.00"], cashier, accountant, price_version)
    bank = b.bank("BOK")
    common = {"received_on": timezone.localdate(), "actor": accountant, "bank": bank}

    def code(**kw) -> str:
        with pytest.raises(DomainError) as exc:
            cs.record_payer_payment(payer=payer, reference="RA-1", **common, **kw)
        return exc.value.code

    assert code(amount=D("70.01"), claim_amounts={claim.pk: D("70.01")}) == (
        "CLAIM_PAYMENT_EXCEEDS_ACCEPTED"
    )
    # Another payer's claim has nothing this payer owes.
    assert code(amount=D("10.00"), claim_amounts={foreign.pk: D("10.00")}) == (
        "CLAIM_NOTHING_UNPAID"
    )
    assert code(amount=D("20.00"), claim_amounts={claim.pk: D("10.00")}) == (
        "PAYER_PAYMENT_UNBALANCED"
    )
    line = ClaimLine.objects.get(claim=claim)
    assert code(
        amount=D("10.00"),
        claim_amounts={claim.pk: D("10.00")},
        allocations={line.pk: D("10.00")},
    ) == ("PAYER_ALLOCATION_CONFLICT")
    assert not PayerPaymentAllocation.objects.exists()
    reconciles(payer)
