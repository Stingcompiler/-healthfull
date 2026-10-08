"""Claims services: batches, responses, rebill/write-off, payer payments, receivables.

Invoices are built with the real financial engine (orders + billing services), so the payer
receivable derived from documents is checked against the AR_PAYER ledger balance.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.billing import services as billing
from apps.billing.models import Invoice, InvoiceLine
from apps.catalog.models import CoverageRule, PriceItem, PriceList, PriceListVersion
from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine, PayerPaymentAllocation
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.orders import services as orders
from domain.errors import DomainError

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def cashier(make_user):
    return make_user(roles=["cashier"])


@pytest.fixture
def accountant(make_user):
    return make_user(roles=["accountant"])


@pytest.fixture
def price_version() -> PriceListVersion:
    plist = PriceList.objects.filter(is_default=True).first()
    if plist is None:
        return b.price_version()
    return PriceListVersion.objects.get_or_create(
        price_list=plist, effective_from=b.REFERENCE_VERSION_DATE
    )[0]


def insured_payer(percent: int = 70):
    payer = b.payer(requires_card_number=False)
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=D(percent))
    return payer


def insured_invoice(payer, prices, actor, version) -> Invoice:
    """An approved invoice of a payer-covered visit with one line per price."""
    visit = b.visit(payer=payer)
    services = []
    for price in prices:
        svc = b.service("lab")
        PriceItem.objects.create(version=version, service=svc, unit_price=D(price))
        services.append(svc)
    orders.create_service_lines(visit, [{"service": s} for s in services], actor)
    invoice = billing.create_draft_invoice(visit, actor)
    return billing.approve_invoice(invoice, actor=actor)


def ar_payer(payer) -> Decimal:
    return ledger.account_balance("AR_PAYER", payer=payer)


def reconciles(payer) -> None:
    row = cs.payer_receivables(payer=payer).get(payer.pk)
    documents = row.receivable if row else D(0)
    assert documents == ar_payer(payer)
    if row:
        assert sum(row.aging.values()) == row.receivable


def _lines(claim: Claim) -> list[ClaimLine]:
    return list(claim.lines.order_by("id"))


# --- accrual and batches --------------------------------------------------------------------


def test_build_claim_from_accrued_payer_shares(cashier, accountant, price_version) -> None:
    payer, other = insured_payer(70), insured_payer(50)
    inv1 = insured_invoice(payer, ["100.00", "50.00"], cashier, price_version)
    inv2 = insured_invoice(payer, ["10.00"], cashier, price_version)
    insured_invoice(other, ["100.00"], cashier, price_version)
    today = timezone.localdate()
    accrued = cs.accrued_lines(payer, period_start=today, period_end=today)
    assert [a.amount for a in accrued] == [D("70.00"), D("35.00"), D("7.00")]
    assert ar_payer(payer) == D("112.00")
    reconciles(payer)

    claim = cs.build_claim(
        payer=payer, period_start=today, period_end=today, actor=accountant, note="October"
    )
    assert claim.number.startswith("CLM-")
    assert claim.claimed_total == D("112.00")
    assert [cl.amount_claimed for cl in _lines(claim)] == [D("70.00"), D("35.00"), D("7.00")]
    assert cs.accrued_lines(payer) == []
    with pytest.raises(DomainError) as exc:
        cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    assert exc.value.code == "CLAIM_EMPTY"
    # Claiming is not collecting: the receivable is unchanged and still reconciles.
    assert cs.payer_receivables(payer=payer)[payer.pk].claimed == D("112.00")
    reconciles(payer)
    assert {il.invoice_id for il in InvoiceLine.objects.filter(claim_lines__claim=claim)} == {
        inv1.pk,
        inv2.pk,
    }


def test_build_claim_choices_and_validation(cashier, accountant, price_version) -> None:
    payer, other = insured_payer(), insured_payer()
    inv = insured_invoice(payer, ["100.00", "20.00"], cashier, price_version)
    foreign = insured_invoice(other, ["100.00"], cashier, price_version)
    today = timezone.localdate()
    first = inv.lines.order_by("line_no").first()
    assert first is not None
    with pytest.raises(DomainError) as exc:
        cs.build_claim(
            payer=payer,
            period_start=today,
            period_end=today,
            actor=accountant,
            invoice_line_ids=[foreign.lines.get().pk],
        )
    assert exc.value.code == "CLAIM_LINE_NOT_ACCRUED"
    with pytest.raises(DomainError) as exc:
        cs.build_claim(
            payer=payer, period_start=today, period_end=today - timedelta(days=1), actor=accountant
        )
    assert exc.value.code == "INVALID_DATE_RANGE"
    with pytest.raises(DomainError) as exc:
        cs.build_claim(
            payer=payer,
            period_start=today - timedelta(days=30),
            period_end=today - timedelta(days=1),
            actor=accountant,
        )
    assert exc.value.code == "CLAIM_EMPTY"
    claim = cs.build_claim(
        payer=payer,
        period_start=today,
        period_end=today,
        actor=accountant,
        invoice_line_ids=[first.pk],
    )
    assert claim.claimed_total == D("70.00")
    assert [a.amount for a in cs.accrued_lines(payer)] == [D("14.00")]


def test_credit_before_claiming_reduces_the_claim(cashier, accountant, price_version) -> None:
    payer = insured_payer(70)
    inv = insured_invoice(payer, ["100.00"], cashier, price_version)
    il = inv.lines.get()
    cn = billing.create_credit_note(inv, [(il, 1)], actor=cashier, reason="PRICE_ERROR")
    billing.approve_credit_note(cn, actor=accountant)
    assert cs.accrued_lines(payer) == []  # fully credited: nothing to claim
    reconciles(payer)


def test_credit_of_a_claimed_line_withdraws_it_until_the_payer_paid(
    cashier, accountant, price_version
) -> None:
    """An unanswered claim line is withdrawn by the credit that takes its share back
    (the claim no longer asks for it); once the payer answered and paid, the payer side is
    corrected through the claim (CLAIM_LINE_LOCKED)."""
    payer = insured_payer()
    inv = insured_invoice(payer, ["100.00"], cashier, price_version)
    today = timezone.localdate()
    claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    cn = billing.create_credit_note(
        inv, [(inv.lines.get(), 1)], actor=cashier, reason="PRICE_ERROR"
    )
    billing.approve_credit_note(cn, actor=accountant)
    (line,) = _lines(claim)
    assert (line.status, line.withdrawn_by) == ("withdrawn", accountant)
    claim.refresh_from_db()
    assert claim.claimed_total == 0
    reconciles(payer)

    inv2 = insured_invoice(payer, ["50.00"], cashier, price_version)
    claim2 = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    cs.submit_claim(claim2, actor=accountant)
    (cl,) = _lines(claim2)
    cs.record_responses(claim2, [cs.ClaimResponse(cl.pk, cl.amount_claimed)], actor=accountant)
    cs.record_payer_payment(
        payer=payer,
        amount=cl.amount_claimed,
        received_on=today,
        actor=accountant,
        bank=b.bank(),
        reference="CLM-PAY-1",
    )
    with pytest.raises(DomainError) as exc:
        billing.create_credit_note(
            inv2, [(inv2.lines.get(), 1)], actor=cashier, reason="PRICE_ERROR"
        )
    assert exc.value.code == "CLAIM_LINE_LOCKED"
    reconciles(payer)


def test_remove_submit_and_void(cashier, accountant, price_version) -> None:
    payer = insured_payer()
    insured_invoice(payer, ["100.00", "50.00"], cashier, price_version)
    today = timezone.localdate()
    claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    first, second = _lines(claim)
    claim = cs.remove_claim_line(first, actor=accountant)
    assert claim.claimed_total == D("35.00")
    assert [a.amount for a in cs.accrued_lines(payer)] == [D("70.00")]  # claimable again
    submitted = cs.submit_claim(claim, actor=accountant)
    assert submitted.status == "submitted"
    assert submitted.submitted_by == accountant
    with pytest.raises(DomainError) as exc:
        cs.remove_claim_line(second, actor=accountant)
    assert exc.value.code == "CLAIM_STATUS_INVALID"
    with pytest.raises(DomainError) as exc:
        cs.void_claim(claim, actor=accountant, note=" ")
    assert exc.value.code == "REASON_REQUIRED"
    voided = cs.void_claim(claim, actor=accountant, note="sent to the wrong payer")
    assert voided.status == "void"
    assert sorted(a.amount for a in cs.accrued_lines(payer)) == [D("35.00"), D("70.00")]
    reconciles(payer)
    again = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    assert again.claimed_total == D("105.00")


# --- responses and rejections ---------------------------------------------------------------


@pytest.fixture
def answered(cashier, accountant, price_version):
    """A submitted claim of three lines (70, 35, 7) answered: full, partial (20), rejected."""
    payer = insured_payer(70)
    insured_invoice(payer, ["100.00", "50.00", "10.00"], cashier, price_version)
    today = timezone.localdate()
    claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    full, part, rejected = _lines(claim)
    with pytest.raises(DomainError) as exc:
        cs.record_responses(claim, [cs.ClaimResponse(full.pk, D("70.00"))], actor=accountant)
    assert exc.value.code == "CLAIM_STATUS_INVALID"  # not submitted yet
    cs.submit_claim(claim, actor=accountant)
    with pytest.raises(DomainError) as exc:
        cs.record_responses(claim, [cs.ClaimResponse(part.pk, D("20.00"))], actor=accountant)
    assert exc.value.code == "REASON_REQUIRED"
    claim = cs.record_responses(
        claim,
        [
            cs.ClaimResponse(full.pk, D("70.00"), reference="RA-1"),
            cs.ClaimResponse(part.pk, D("20.00"), reason="tariff limit"),
            cs.ClaimResponse(rejected.pk, D("0.00"), reason="not covered"),
        ],
        actor=accountant,
    )
    return payer, claim, full, part, rejected


def test_responses_set_statuses_and_totals(answered, accountant) -> None:
    payer, claim, full, part, rejected = answered
    assert claim.status == "responded"
    assert (claim.claimed_total, claim.accepted_total, claim.rejected_total) == (
        D("112.00"),
        D("90.00"),
        D("22.00"),
    )
    rows = {cl.pk: cl for cl in _lines(claim)}
    assert rows[full.pk].status == "accepted"
    assert (rows[part.pk].status, rows[part.pk].rejected_amount) == ("partial", D("15.00"))
    assert (rows[rejected.pk].status, rows[rejected.pk].payer_reason) == ("rejected", "not covered")
    with pytest.raises(DomainError) as exc:
        cs.record_responses(claim, [cs.ClaimResponse(full.pk, D("1.00"))], actor=accountant)
    assert exc.value.code == "CLAIM_LINE_NOT_CLAIMED"
    with pytest.raises(DomainError) as exc:
        cs.record_responses(claim, [cs.ClaimResponse(999_999, D("1.00"))], actor=accountant)
    assert exc.value.code == "CLAIM_LINE_UNKNOWN"
    receivable = cs.payer_receivables(payer=payer)[payer.pk]
    assert receivable.accepted_unpaid == D("90.00")
    assert receivable.rejected_unresolved == D("22.00")
    reconciles(payer)


def test_write_off_and_rebill_post_to_the_ledger(answered, accountant, cashier) -> None:
    payer, _claim, full, part, rejected = answered
    with pytest.raises(PermissionDenied):
        cs.resolve_rejection(
            rejected, resolution="written_off", actor=cashier, reason_code="NOT_COVERED"
        )
    with pytest.raises(DomainError) as exc:
        cs.resolve_rejection(
            full, resolution="written_off", actor=accountant, reason_code="NOT_COVERED"
        )
    assert exc.value.code == "CLAIM_NOTHING_REJECTED"
    with pytest.raises(DomainError) as exc:
        cs.resolve_rejection(
            rejected, resolution="forgiven", actor=accountant, reason_code="NOT_COVERED"
        )
    assert exc.value.code == "INVALID_RESOLUTION"
    with pytest.raises(DomainError) as exc:
        cs.resolve_rejection(
            rejected, resolution="written_off", actor=accountant, reason_code="OTHER"
        )
    assert exc.value.code == "REASON_NOTE_REQUIRED"

    before = ar_payer(payer)
    off = cs.resolve_rejection(
        part, resolution="written_off", actor=accountant, reason_code="SMALL_BALANCE"
    )
    assert off.resolved_by == accountant
    assert off.resolution_reason is not None
    assert ar_payer(payer) == before - D("15.00")
    assert ledger.account_balance("WRITE_OFF", payer=payer) == D("15.00")

    invoice = rejected.invoice_line.invoice
    patient_before = billing.invoice_position(invoice).outstanding
    rebilled = cs.resolve_rejection(
        rejected, resolution="rebilled", actor=accountant, reason_code="NOT_COVERED"
    )
    assert rebilled.resolution == "rebilled"
    assert ar_payer(payer) == before - D("22.00")
    assert billing.invoice_position(invoice).outstanding == patient_before + D("7.00")
    assert (
        ledger.account_balance("AR_PATIENT", invoice=invoice)
        == billing.invoice_position(invoice).outstanding
    )
    with pytest.raises(DomainError) as exc:
        cs.resolve_rejection(
            rejected, resolution="written_off", actor=accountant, reason_code="NOT_COVERED"
        )
    assert exc.value.code == "CLAIM_NOTHING_REJECTED"
    receivable = cs.payer_receivables(payer=payer)[payer.pk]
    assert (receivable.written_off, receivable.rebilled) == (D("15.00"), D("7.00"))
    reconciles(payer)


# --- payer payments -------------------------------------------------------------------------


def test_payer_payment_allocation_and_close(answered, accountant) -> None:
    payer, claim, full, part, rejected = answered
    bank = b.bank("BOK")
    with pytest.raises(DomainError) as exc:
        cs.record_payer_payment(
            payer=payer, amount=D("50.00"), received_on=timezone.localdate(), actor=accountant
        )
    assert exc.value.code == "BANK_REQUIRED"
    with pytest.raises(DomainError) as exc:
        cs.record_payer_payment(
            payer=payer,
            amount=D("100.00"),
            received_on=timezone.localdate(),
            actor=accountant,
            bank=bank,
            reference="T-1",
        )
    assert exc.value.code == "PAYER_PAYMENT_UNBALANCED"  # only 90 accepted
    with pytest.raises(DomainError) as exc:
        cs.record_payer_payment(
            payer=payer,
            amount=D("10.00"),
            received_on=timezone.localdate(),
            actor=accountant,
            bank=bank,
            reference="T-1",
            allocations={rejected.pk: D("10.00")},
        )
    assert exc.value.code == "CLAIM_LINE_NOT_ACCEPTED"

    first = cs.record_payer_payment(
        payer=payer,
        amount=D("50.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        bank=bank,
        reference="T-1",
    )
    assert first.number.startswith("PP-")
    # Auto allocation pays the oldest accepted amounts first, in line order.
    assert list(
        PayerPaymentAllocation.objects.filter(payer_payment=first).values_list(
            "claim_line_id", "amount"
        )
    ) == [(full.pk, D("50.00"))]
    assert ledger.account_balance("BANK") >= D("50.00")
    assert ledger.account_balance("CASH") == D("0.00")
    with pytest.raises(DomainError) as exc:
        cs.record_payer_payment(
            payer=payer,
            amount=D("20.00"),
            received_on=timezone.localdate(),
            actor=accountant,
            bank=bank,
            reference="t 1",
            allocations={full.pk: D("20.00")},
        )
    assert exc.value.code == "DUPLICATE_REFERENCE"
    with pytest.raises(DomainError) as exc:
        cs.close_claim(claim, actor=accountant)
    assert exc.value.code == "CLAIM_NOT_SETTLED"

    cs.record_payer_payment(
        payer=payer,
        amount=D("40.00"),
        received_on=timezone.localdate(),
        actor=accountant,
        method="cheque",
        allocations={full.pk: D("20.00"), part.pk: D("20.00")},
    )
    receivable = cs.payer_receivables(payer=payer)[payer.pk]
    assert receivable.collected == D("90.00")
    assert receivable.accepted_unpaid == D("0.00")
    assert cs.claim_line_state(ClaimLine.objects.get(pk=full.pk)).status == "paid"
    cs.resolve_rejection(
        part, resolution="written_off", actor=accountant, reason_code="SMALL_BALANCE"
    )
    cs.resolve_rejection(
        rejected, resolution="rebilled", actor=accountant, reason_code="NOT_COVERED"
    )
    reconciles(payer)
    assert ar_payer(payer) == D("0.00")
    closed = cs.close_claim(claim, actor=accountant)
    assert closed.status == "closed"
    assert closed.closed_at


def test_aging_buckets(cashier, accountant, price_version) -> None:
    payer = insured_payer(70)
    insured_invoice(payer, ["100.00"], cashier, price_version)
    today = timezone.localdate()
    assert cs.payer_aging(as_of=today)[payer.pk]["0_30"] == D("70.00")
    later = cs.payer_aging(as_of=today + timedelta(days=45))[payer.pk]
    assert later == {"0_30": D(0), "31_60": D("70.00"), "61_90": D(0), "over_90": D(0)}
    assert cs.payer_aging(as_of=today + timedelta(days=200))[payer.pk]["over_90"] == D("70.00")


# --- reconciliation property ----------------------------------------------------------------


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    prices=st.lists(st.integers(min_value=1, max_value=50_000), min_size=1, max_size=4),
    percent=st.integers(min_value=1, max_value=100),
    accept_ratios=st.lists(st.integers(min_value=0, max_value=100), min_size=4, max_size=4),
    resolutions=st.lists(
        st.sampled_from(["none", "rebilled", "written_off"]), min_size=4, max_size=4
    ),
    pay_ratio=st.integers(min_value=0, max_value=100),
)
def test_documents_always_reconcile_with_ar_payer(
    cashier, accountant, price_version, prices, percent, accept_ratios, resolutions, pay_ratio
) -> None:
    payer = insured_payer(percent)
    insured_invoice(payer, [f"{p}.00" for p in prices], cashier, price_version)
    reconciles(payer)
    today = timezone.localdate()
    claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=accountant)
    cs.submit_claim(claim, actor=accountant)
    reconciles(payer)
    lines = _lines(claim)
    responses = []
    for cl, ratio in zip(lines, accept_ratios, strict=False):
        accepted = (cl.amount_claimed * ratio / 100).quantize(D("0.01"))
        responses.append(cs.ClaimResponse(cl.pk, accepted, reason="payer rule"))
    cs.record_responses(claim, responses, actor=accountant)
    reconciles(payer)
    for cl, how in zip(_lines(claim), resolutions, strict=False):
        if how != "none" and cl.rejected_amount > 0:
            cs.resolve_rejection(cl, resolution=how, actor=accountant, reason_code="NOT_COVERED")
    reconciles(payer)
    accepted_total = sum((cl.accepted_amount for cl in _lines(claim)), D(0))
    pay = (accepted_total * pay_ratio / 100).quantize(D("0.01"))
    if pay > 0:
        cs.record_payer_payment(
            payer=payer,
            amount=pay,
            received_on=today,
            actor=accountant,
            method="cheque",
        )
    reconciles(payer)
    row = cs.payer_receivables(payer=payer)[payer.pk]
    assert row.collected == pay
    assert ledger.account_balance("CASH") == D("0.00")  # payer money never reaches CASH
