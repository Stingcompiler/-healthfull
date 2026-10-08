"""Property tests for the rules added by the Phase 1 review fixes.

Quantities (credited units are never given), percent discounts within their percent, money a
credit note releases, claim-line withdrawal for credits, payer contract windows, stock
returns and transfer shortages, the doctor's view of a line, and the small rules moved out
of services (oldest-first payer allocation, aging buckets, refund source, reorder).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from domain import allocation as da
from domain import claims as dclaims
from domain import coverage as dc
from domain import invoice as di
from domain import ledger as dl
from domain import service_line as dsl
from domain import stock as ds
from domain.audit import Approval
from domain.errors import DomainError
from domain.payments import PaymentMethod
from domain.tests.strategies import amounts, invoice_lines, percents, positive_amounts

D = Decimal
APPROVAL = Approval(1, datetime(2026, 10, 7, tzinfo=UTC), "checked", "OTHER")

units = st.integers(min_value=0, max_value=500)


# --- quantities (invariant 1) -------------------------------------------------------------


@given(units, units, units)
def test_open_quantity_never_gives_credited_units(ordered: int, credited: int, given_: int) -> None:
    if credited + given_ > ordered:
        with pytest.raises(DomainError) as exc:
            dsl.open_quantity(ordered, credited=credited, given=given_)
        assert exc.value.code == "CREDIT_EXCEEDS_UNGIVEN"
        return
    left = dsl.open_quantity(ordered, credited=credited, given=given_)
    assert left >= 0
    assert left + credited + given_ == ordered


@given(st.integers(1, 500), st.data())
def test_closing_a_remainder_bills_exactly_the_performed_units(ordered: int, data) -> None:
    credited = data.draw(st.integers(0, ordered - 1))
    performed = data.draw(st.integers(0, ordered - credited))
    if credited + performed == ordered:
        with pytest.raises(DomainError) as exc:
            dsl.remainder_to_credit(ordered, credited=credited, performed=performed)
        assert exc.value.code == "LINE_NOTHING_REMAINING"
        return
    rest = dsl.remainder_to_credit(ordered, credited=credited, performed=performed)
    # Billed units less every credited unit equal the units given.
    assert ordered - (credited + rest) == performed


@pytest.mark.parametrize("bad", [-1, True, 1.5, D("2")])
def test_quantities_are_whole_non_negative_ints(bad) -> None:
    with pytest.raises(DomainError) as exc:
        dsl.open_quantity(10, credited=bad)
    assert exc.value.code == "INVALID_QUANTITY"


# --- the doctor's view (FEATURES 3.7) -----------------------------------------------------


@given(
    st.sampled_from(list(dsl.BillingStatus)),
    st.sampled_from(list(dsl.FulfilmentStatus)),
    st.booleans(),
)
def test_doctor_status_keeps_work_in_progress_visible(billing, fulfilment, authorized) -> None:
    status = dsl.doctor_status(billing, fulfilment, authorized=authorized)
    if fulfilment is dsl.FulfilmentStatus.IN_PROGRESS:
        assert status is dsl.DoctorStatus.IN_PROGRESS
    if fulfilment is dsl.FulfilmentStatus.PERFORMED:
        assert status is dsl.DoctorStatus.DONE
    if fulfilment is dsl.FulfilmentStatus.CANCELLED:
        assert status is dsl.DoctorStatus.CANCELLED
    if fulfilment is dsl.FulfilmentStatus.PENDING:
        paid = billing is dsl.BillingStatus.SETTLED or authorized
        assert status is (dsl.DoctorStatus.PAID if paid else dsl.DoctorStatus.REQUESTED)


# --- percent discounts (FEATURES 5.9) -----------------------------------------------------


@given(amounts, percents)
def test_percent_discount_never_exceeds_its_percent(base: Decimal, percent: Decimal) -> None:
    value = dc.percent_discount(base, percent)
    assert value == value.quantize(D("0.01"))
    assert D(0) <= value <= base
    assert dc.discount_within_limit(value, base, percent)
    assert base * percent / 100 - value < D("0.01")


def test_percent_discount_at_the_limit_passes_the_limit_check() -> None:
    base = D("1005.00") - D("703.50")  # 301.50 patient share of a 70% covered line
    value = dc.percent_discount(base, 25)
    assert value == D("75.37")  # half-up would give 75.38, above 25%
    dc.check_discount(value, base, ["cashier_supervisor"], {"cashier_supervisor": 25}, APPROVAL)


# --- payer contract window (FEATURES 11.1) ------------------------------------------------


@given(
    st.none() | st.dates(date(2020, 1, 1), date(2030, 1, 1)),
    st.none() | st.dates(date(2020, 1, 1), date(2030, 1, 1)),
    st.dates(date(2020, 1, 1), date(2030, 1, 1)),
)
def test_contract_window(start: date | None, end: date | None, on: date) -> None:
    inside = (start is None or start <= on) and (end is None or on <= end)
    if inside:
        dc.require_contract(start, end, on)
    else:
        with pytest.raises(DomainError) as exc:
            dc.require_contract(start, end, on)
        assert exc.value.code == "PAYER_CONTRACT_EXPIRED"


# --- money a credit note releases (ARCHITECTURE 4.4 rule 3) -------------------------------


@given(invoice_lines(max_size=4), st.data())
def test_credit_release_keeps_other_lines_paid_amounts(lines, data) -> None:
    due = sum((ln.patient_share for ln in lines), D(0))
    paid = data.draw(st.decimals(min_value=0, max_value=due, places=2))
    target = data.draw(st.sampled_from(lines))
    qty = data.draw(st.integers(1, target.quantity))
    credit = di.build_credit_line(target, qty)
    before = di.invoice_position(lines, [], [paid])
    after = di.invoice_position(lines, [credit], [paid])
    release = di.credit_release(before, after)
    assert release >= 0
    settled = di.invoice_position(lines, [credit], [paid, -release])
    assert settled.over_allocation == 0
    for old in before.lines:
        new = settled.line(old.position)
        if old.position == target.position:
            assert new.patient_paid <= new.patient_due
        else:
            assert new.patient_paid == old.patient_paid


def test_credit_release_refuses_positions_of_other_invoices() -> None:
    a = di.invoice_position(
        [di.InvoiceLineDraft(1, 1, "X", 1, D(10), 1, D(10), D(0), None, D(0), D(10))], [], []
    )
    b = di.invoice_position(
        [di.InvoiceLineDraft(2, 2, "X", 1, D(10), 1, D(10), D(0), None, D(0), D(10))], [], []
    )
    with pytest.raises(DomainError):
        di.credit_release(a, b)


# --- claims: withdrawing a claimed share for a credit -------------------------------------


@given(positive_amounts, positive_amounts)
def test_unanswered_claim_line_is_withdrawn_for_any_credit(amount, credit) -> None:
    line = dclaims.ClaimLine(dclaims.ClaimLineStatus.CLAIMED, amount)
    assert dclaims.withdraw_for_credit(line, credit).status is dclaims.ClaimLineStatus.VOIDED


@given(positive_amounts, st.data())
def test_answered_claim_line_needs_a_full_credit_and_nothing_collected(amount, data) -> None:
    accepted = data.draw(st.decimals(min_value=0, max_value=amount, places=2))
    status = (
        dclaims.ClaimLineStatus.ACCEPTED
        if accepted == amount
        else dclaims.ClaimLineStatus.REJECTED
        if accepted == 0
        else dclaims.ClaimLineStatus.PARTIALLY_ACCEPTED
    )
    line = dclaims.ClaimLine(status, amount, accepted)
    assert dclaims.withdraw_for_credit(line, amount).status is dclaims.ClaimLineStatus.VOIDED
    partial = data.draw(st.decimals(min_value=D("0.01"), max_value=amount, places=2))
    assume(partial < amount)
    with pytest.raises(DomainError) as exc:
        dclaims.withdraw_for_credit(line, partial)
    assert exc.value.code == "CLAIM_LINE_LOCKED"
    if accepted > 0:
        paid = dclaims.record_payment(line, accepted)
        with pytest.raises(DomainError):
            dclaims.withdraw_for_credit(paid, amount)


# --- claims: short payments, reversals, oldest first, aging -------------------------------


@given(positive_amounts, st.data())
def test_short_payment_write_off_closes_the_receivable(amount, data) -> None:
    line = dclaims.ClaimLine(dclaims.ClaimLineStatus.ACCEPTED, amount, amount)
    pay = data.draw(st.decimals(min_value=0, max_value=amount, places=2))
    if pay > 0:
        line = dclaims.record_payment(line, pay)
    if line.unpaid == 0:
        with pytest.raises(DomainError) as exc:
            dclaims.write_off_shortfall(line, amount, APPROVAL)
        assert exc.value.code == "CLAIM_NOTHING_UNPAID"
        return
    off = dclaims.write_off_shortfall(line, line.unpaid, APPROVAL)
    assert off.receivable == 0
    assert dclaims.is_settled(off)
    with pytest.raises(DomainError):
        dclaims.record_payment(off, D("0.01"))


@given(positive_amounts, st.data())
def test_reversing_a_payment_owes_it_again(amount, data) -> None:
    line = dclaims.ClaimLine(dclaims.ClaimLineStatus.ACCEPTED, amount, amount)
    pay = data.draw(st.decimals(min_value=D("0.01"), max_value=amount, places=2))
    paid = dclaims.record_payment(line, pay)
    back = dclaims.reverse_payment(paid, pay, dclaims.ClaimLineStatus.ACCEPTED)
    assert back.receivable == line.receivable
    with pytest.raises(DomainError):
        dclaims.reverse_payment(paid, pay + D("0.01"), dclaims.ClaimLineStatus.ACCEPTED)


@given(positive_amounts, st.lists(amounts, max_size=8))
def test_oldest_first_allocation_respects_order_and_dues(amount, dues) -> None:
    rows = list(enumerate(dues, start=1))
    out = dclaims.allocate_oldest_first(amount, rows)
    assert sum(out.values(), D(0)) <= amount
    for line_id, value in out.items():
        assert D(0) < value <= dict(rows)[line_id]
    # A later line gets money only when every earlier line with a due is paid in full.
    for line_id, _due in rows:
        if out.get(line_id, D(0)) > 0 and any(out.get(i, D(0)) < d for i, d in rows if i < line_id):
            raise AssertionError("allocation skipped an older due")


@given(st.integers(0, 2000))
def test_aging_buckets_are_ordered(age: int) -> None:
    name = dclaims.aging_bucket(age)
    expected = (
        "0_30" if age <= 30 else "31_60" if age <= 60 else "61_90" if age <= 90 else "over_90"
    )
    assert name == expected
    with pytest.raises(DomainError):
        dclaims.aging_bucket(-1)


# --- refunds and stock --------------------------------------------------------------------


@given(st.lists(positive_amounts, max_size=4), st.lists(positive_amounts, max_size=4))
def test_refund_source_is_deallocated_credit_less_refunds(deallocated, refunds) -> None:
    rows = [-a for a in deallocated]
    available = da.refund_source_available(rows, refunds)
    assert available == sum(deallocated, D(0)) - sum(refunds, D(0))


@given(st.integers(0, 500), st.integers(0, 200), st.integers(0, 300))
def test_reorder_suggestion(on_hand: int, minimum: int, fixed: int) -> None:
    value = ds.reorder_suggestion(on_hand, minimum, fixed)
    assert value == (fixed or max(2 * minimum - on_hand, 0))
    assert value >= 0


@given(st.integers(1, 100), st.integers(0, 100), st.integers(1, 100))
def test_returns_never_exceed_what_was_dispensed(dispensed: int, returned: int, qty: int) -> None:
    assume(returned <= dispensed)
    if qty > dispensed - returned:
        with pytest.raises(DomainError) as exc:
            ds.return_move(1, 2, 3, qty, dispensed=dispensed, returned=returned, approval=APPROVAL)
        assert exc.value.code == "RETURN_EXCEEDS_DISPENSED"
        return
    move = ds.return_move(1, 2, 3, qty, dispensed=dispensed, returned=returned, approval=APPROVAL)
    assert move.kind is ds.MoveKind.RETURN
    assert move.quantity == qty


@given(st.integers(1, 100), st.integers(0, 120))
def test_transfer_shortage_needs_an_approval(sent: int, received: int) -> None:
    if received > sent:
        with pytest.raises(DomainError) as exc:
            ds.transfer_receipt(sent, received, APPROVAL)
        assert exc.value.code == "RECEIPT_EXCEEDS_SENT"
        return
    if received < sent:
        with pytest.raises(DomainError) as exc:
            ds.transfer_receipt(sent, received, None)
        assert exc.value.code == "REASON_REQUIRED"
    assert ds.transfer_receipt(sent, received, APPROVAL) == sent - received


# --- ledger: cash outside the drawers (ADR 0006) ------------------------------------------


@given(amounts, st.lists(positive_amounts, max_size=4), st.data())
def test_shift_cash_in_the_ledger_follows_the_drawer(float_: Decimal, cash_in, data) -> None:
    shift = 7
    drafts = [dl.post_shift_opening(shift, float_)]
    drawer = float_
    for i, amount in enumerate(cash_in):
        drafts.append(dl.post_payment_received(i + 1, 3, PaymentMethod.CASH, amount, shift))
        drawer += amount
    out = data.draw(st.decimals(min_value=0, max_value=drawer, places=2))
    if out > 0:
        drafts.append(dl.post_cash_handover(1, shift, out, to_bank=data.draw(st.booleans())))
        drawer -= out
    assert dl.account_balance(drafts, dl.Account.CASH, shift=shift) == drawer
    drafts.append(dl.post_shift_sweep(shift, drawer))
    assert dl.account_balance(drafts, dl.Account.CASH, shift=shift) == 0
    # The float came out of the safe and went back; the money everywhere is what came in.
    money = sum(
        (
            dl.account_balance(drafts, a)
            for a in (dl.Account.CASH, dl.Account.CASH_SAFE, dl.Account.BANK)
        ),
        D(0),
    )
    assert money == sum(cash_in, D(0))


@given(positive_amounts, st.booleans())
def test_cancelled_handover_mirrors_the_handover(amount: Decimal, to_bank: bool) -> None:
    drafts = [
        dl.post_cash_handover(1, 5, amount, to_bank=to_bank),
        dl.post_handover_cancelled(1, 5, amount, to_bank=to_bank),
    ]
    for account in (dl.Account.CASH, dl.Account.CASH_SAFE, dl.Account.BANK):
        assert dl.account_balance(drafts, account) == 0


@given(positive_amounts)
def test_allocation_across_merged_files_keeps_each_file_whole(amount: Decimal) -> None:
    drafts = [dl.post_allocation(1, 10, 99, amount, invoice_patient_id=20)]
    # The duplicate's credit pays the survivor's invoice: each file's own dimension moves.
    assert dl.account_balance(drafts, dl.Account.PATIENT_CREDIT, patient=10) == -amount
    assert dl.account_balance(drafts, dl.Account.AR_PATIENT, patient=20, invoice=99) == -amount
    assert dl.account_balance(drafts, dl.Account.AR_PATIENT, patient=10) == 0


def test_payer_cash_needs_a_shift_and_cheques_wait_in_bank_pending() -> None:
    with pytest.raises(DomainError) as exc:
        dl.post_payer_payment(1, 2, [(3, D("10.00"))], money=dl.PayerMoney.CASH)
    assert exc.value.code == "SHIFT_NOT_OPEN"
    cash = dl.post_payer_payment(1, 2, [(3, D("10.00"))], money=dl.PayerMoney.CASH, shift_id=4)
    assert dl.account_balance([cash], dl.Account.CASH, shift=4) == D("10.00")
    cheque = dl.post_payer_payment(1, 2, [(3, D("10.00"))], money=dl.PayerMoney.CHEQUE)
    assert dl.account_balance([cheque], dl.Account.BANK_PENDING) == D("10.00")
    cleared = dl.post_payer_cheque_cleared(1, D("10.00"))
    assert dl.account_balance([cheque, cleared], dl.Account.BANK) == D("10.00")
    assert dl.account_balance([cheque, cleared], dl.Account.BANK_PENDING) == 0
    bounced = dl.post_payer_payment_reversed(1, 2, [(3, D("10.00"))], money=dl.PayerMoney.BANK)
    assert dl.account_balance([cheque, cleared, bounced], dl.Account.BANK) == 0
    assert dl.account_balance([cheque, cleared, bounced], dl.Account.AR_PAYER, payer=2) == 0
    with pytest.raises(DomainError):
        dl.post_payer_payment_reversed(1, 2, [(3, D("10.00"))], money=dl.PayerMoney.CASH)
