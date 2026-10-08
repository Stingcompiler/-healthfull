from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.ledger import (
    CHART,
    MONEY_ACCOUNTS,
    Account,
    Dim,
    JournalDraft,
    JournalLine,
    RevenueLine,
    Side,
    SourceType,
    account_balance,
    assert_balanced,
    post_allocation,
    post_credit_note,
    post_invoice_approved,
    post_payer_payment,
    post_payer_rebill,
    post_payer_write_off,
    post_payment_received,
    post_refund,
    post_shift_variance,
    post_transfer_confirmed,
    post_transfer_rejected,
    trial_balance,
)
from domain.money import ZERO
from domain.payments import PaymentMethod

A = Account
pos = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=2)
amounts = st.decimals(min_value=0, max_value=Decimal("1000000"), places=2)
signed = st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=2)


@st.composite
def revenue_lines(draw: st.DrawFn) -> list[RevenueLine]:
    out = []
    for _ in range(draw(st.integers(1, 6))):
        discount, payer, patient = draw(amounts), draw(amounts), draw(amounts)
        payer_id = draw(st.none() | st.integers(1, 3)) if payer else None
        if payer_id is None:
            payer = ZERO
        out.append(
            RevenueLine(
                gross=discount + payer + patient,
                discount=discount,
                payer_share=payer,
                patient_share=patient,
                payer_id=payer_id,
                department_id=draw(st.integers(1, 3)),
                service_kind=draw(st.sampled_from(["consultation", "lab", "drug"])),
            )
        )
    return out


def _sum(draft: JournalDraft, account: Account, side: str) -> Decimal:
    return sum((getattr(ln, side) for ln in draft.lines if ln.account is account), ZERO)


# --- chart -----------------------------------------------------------------------------


def test_chart_matches_architecture() -> None:
    assert set(CHART) == set(Account)
    expected_dims = {
        A.CASH: {Dim.SHIFT},
        A.BANK_PENDING: set(),
        A.BANK: set(),
        A.AR_PATIENT: {Dim.PATIENT, Dim.INVOICE},
        A.AR_PAYER: {Dim.PAYER, Dim.INVOICE},
        A.PATIENT_CREDIT: {Dim.PATIENT},
        A.REVENUE: {Dim.DEPARTMENT, Dim.SERVICE_KIND},
        A.DISCOUNT: set(),
        A.WRITE_OFF: {Dim.PAYER},
        A.CASH_OVER_SHORT: {Dim.SHIFT},
        # ADR 0006: cash outside the drawers (safe, in transit between shifts).
        A.CASH_SAFE: set(),
    }
    for account, dims in expected_dims.items():
        assert CHART[account].dimensions == dims
        assert CHART[account].name_ar
        assert CHART[account].name_en
    assert CHART[A.PATIENT_CREDIT].normal is Side.CREDIT
    assert CHART[A.REVENUE].normal is Side.CREDIT
    assert CHART[A.AR_PATIENT].normal is Side.DEBIT
    assert {A.CASH, A.BANK, A.BANK_PENDING, A.CASH_SAFE} == MONEY_ACCOUNTS


# --- lines and balance ------------------------------------------------------------------


def test_line_must_be_one_sided_and_dimensioned() -> None:
    with pytest.raises(DomainError) as exc:
        JournalLine(A.BANK, debit=Decimal("1.00"), credit=Decimal("1.00"))
    assert exc.value.code == "JOURNAL_LINE_INVALID"
    with pytest.raises(DomainError) as exc:
        JournalLine(A.BANK)
    assert exc.value.code == "JOURNAL_LINE_INVALID"
    with pytest.raises(DomainError) as exc:
        JournalLine(A.BANK, debit=Decimal("-1.00"))
    assert exc.value.code == "INVALID_AMOUNT"
    with pytest.raises(DomainError) as exc:
        JournalLine(A.CASH, debit=Decimal("1.00"))
    assert exc.value.code == "JOURNAL_DIMENSIONS_INVALID"
    with pytest.raises(DomainError) as exc:
        JournalLine(A.BANK, debit=Decimal("1.00"), dimensions={Dim.PATIENT: 1})
    assert exc.value.code == "JOURNAL_DIMENSIONS_INVALID"


def test_assert_balanced_refuses_unbalanced_entries() -> None:
    draft = JournalDraft(
        SourceType.PAYMENT,
        1,
        (
            JournalLine(A.BANK_PENDING, debit=Decimal("10.00")),
            JournalLine(A.PATIENT_CREDIT, credit=Decimal("9.99"), dimensions={Dim.PATIENT: 1}),
        ),
    )
    with pytest.raises(DomainError) as exc:
        assert_balanced(draft)
    assert exc.value.code == "JOURNAL_UNBALANCED"


# --- builders ---------------------------------------------------------------------------------


@given(revenue_lines())
def test_invoice_posting(lines: list[RevenueLine]) -> None:
    d = post_invoice_approved(7, 3, lines)
    assert_balanced(d)
    assert d.source_type is SourceType.INVOICE
    assert _sum(d, A.AR_PATIENT, "debit") == sum((ln.patient_share for ln in lines), ZERO)
    assert _sum(d, A.AR_PAYER, "debit") == sum((ln.payer_share for ln in lines), ZERO)
    assert _sum(d, A.DISCOUNT, "debit") == sum((ln.discount for ln in lines), ZERO)
    assert _sum(d, A.REVENUE, "credit") == sum((ln.gross for ln in lines), ZERO)
    # Invariant 7: an invoice never touches money accounts; payer share is a receivable.
    assert not any(ln.account in MONEY_ACCOUNTS for ln in d.lines)
    assert all(ln.amount > 0 for ln in d.lines)


@given(revenue_lines())
def test_credit_note_mirrors_the_invoice(lines: list[RevenueLine]) -> None:
    inv = post_invoice_approved(7, 3, lines)
    cn = post_credit_note(9, 7, 3, lines)
    assert_balanced(cn)
    tb = trial_balance([inv, cn])
    assert all(v == 0 for v in tb.values())


@given(pos, st.sampled_from(list(PaymentMethod)))
def test_payment_received(amount: Decimal, method: PaymentMethod) -> None:
    d = post_payment_received(4, 3, method, amount, shift_id=2)
    assert_balanced(d)
    if method is PaymentMethod.PATIENT_CREDIT:
        assert d.is_empty
        return
    money = A.CASH if method is PaymentMethod.CASH else A.BANK_PENDING
    assert _sum(d, money, "debit") == amount
    assert _sum(d, A.PATIENT_CREDIT, "credit") == amount
    if money is A.CASH:
        assert d.lines[0].dimensions == {Dim.SHIFT: 2}


@given(signed.filter(lambda x: x != 0))
def test_allocation_posting_sign(amount: Decimal) -> None:
    d = post_allocation(5, patient_id=3, invoice_id=7, amount=amount)
    assert_balanced(d)
    assert account_balance([d], A.AR_PATIENT, patient=3, invoice=7) == -amount
    assert account_balance([d], A.PATIENT_CREDIT, patient=3) == -amount


@given(pos, st.booleans())
def test_transfer_confirm_and_reject(amount: Decimal, confirmed_first: bool) -> None:
    received = post_payment_received(4, 3, PaymentMethod.BANK_TRANSFER, amount, shift_id=1)
    entries = [received]
    if confirmed_first:
        entries.append(post_transfer_confirmed(4, amount))
    entries.append(post_transfer_rejected(4, 3, amount, was_confirmed=confirmed_first))
    for e in entries:
        assert_balanced(e)
    tb = trial_balance(entries)
    assert all(v == 0 for v in tb.values())


@given(pos)
def test_refund_and_variance(amount: Decimal) -> None:
    r = post_refund(1, patient_id=3, amount=amount, shift_id=2)
    assert_balanced(r)
    assert account_balance([r], A.CASH, shift=2) == -amount
    over = post_shift_variance(2, amount)
    short = post_shift_variance(2, -amount)
    assert account_balance([over], A.CASH, shift=2) == amount
    assert account_balance([short], A.CASH, shift=2) == -amount
    assert account_balance([short], A.CASH_OVER_SHORT, shift=2) == amount
    assert post_shift_variance(2, ZERO).is_empty


@given(pos)
def test_payer_postings(amount: Decimal) -> None:
    rebill = post_payer_rebill(1, patient_id=3, payer_id=4, invoice_id=7, amount=amount)
    wo = post_payer_write_off(2, payer_id=4, invoice_id=7, amount=amount)
    pay = post_payer_payment(3, payer_id=4, allocations=[(7, amount), (8, amount)])
    for d in (rebill, wo, pay):
        assert_balanced(d)
    assert account_balance([rebill], A.AR_PAYER, payer=4, invoice=7) == -amount
    assert account_balance([rebill], A.AR_PATIENT, patient=3, invoice=7) == amount
    assert account_balance([wo], A.WRITE_OFF, payer=4) == amount
    assert account_balance([pay], A.BANK) == amount * 2
    assert account_balance([pay], A.AR_PAYER, payer=4) == -amount * 2


@pytest.mark.parametrize(
    "build",
    [
        lambda: post_allocation(1, 1, 1, ZERO),
        lambda: post_refund(1, 1, ZERO, 1),
        lambda: post_payment_received(1, 1, PaymentMethod.CASH, ZERO, 1),
        lambda: post_payer_payment(1, 1, []),
        lambda: post_transfer_confirmed(1, Decimal("-1.00")),
    ],
)
def test_builders_refuse_empty_or_negative_amounts(build: object) -> None:
    with pytest.raises(DomainError):
        build()  # type: ignore[operator]


def test_account_balance_uses_normal_side() -> None:
    d = post_payment_received(1, 3, PaymentMethod.CASH, Decimal("100.00"), shift_id=1)
    assert account_balance([d], A.CASH) == Decimal("100.00")
    assert account_balance([d], A.PATIENT_CREDIT) == Decimal("100.00")
    assert account_balance([d], A.PATIENT_CREDIT, patient=4) == 0
    assert trial_balance([d]) == {A.CASH: Decimal("100.00"), A.PATIENT_CREDIT: Decimal("-100.00")}
