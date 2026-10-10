from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from domain.allocation import (
    AllocationRecord,
    AllocationRequest,
    OpenInvoice,
    auto_allocate,
    deallocate_excess,
    later_allocation_limit,
    net_by_invoice,
    net_by_payment,
    plan_rejection,
    reverse_payment,
    spendable_credit,
    unallocated,
    validate_allocations,
    validate_credit_spend,
    validate_refund,
)
from domain.audit import Approval
from domain.errors import DomainError
from domain.money import ZERO

T0 = datetime(2026, 10, 1, tzinfo=UTC)
amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("50000"), places=2)


@st.composite
def open_invoices(draw: st.DrawFn) -> list[OpenInvoice]:
    n = draw(st.integers(0, 6))
    hours = draw(st.lists(st.integers(0, 500), min_size=n, max_size=n, unique=True))
    return [
        OpenInvoice(
            invoice_id=10 + i, approved_at=T0 + timedelta(hours=h), outstanding=draw(amounts)
        )
        for i, h in enumerate(hours)
    ]


# --- explicit allocations ------------------------------------------------------------------


def test_validate_allocations_happy_path() -> None:
    plan = validate_allocations(
        Decimal("500.00"),
        [AllocationRequest(1, Decimal("200.00")), AllocationRequest(2, Decimal("100.00"))],
        {1: Decimal("200.00"), 2: Decimal("100.00")},
        allow_partial=False,
    )
    assert plan.allocated == Decimal("300.00")
    assert plan.unallocated == Decimal("200.00")


@pytest.mark.parametrize(
    ("requests", "code"),
    [
        ([AllocationRequest(1, Decimal("0.00"))], "INVALID_AMOUNT"),
        ([AllocationRequest(1, Decimal("-1.00"))], "INVALID_AMOUNT"),
        ([AllocationRequest(9, Decimal("1.00"))], "INVOICE_NOT_OPEN"),
        (
            [AllocationRequest(1, Decimal("1.00")), AllocationRequest(1, Decimal("1.00"))],
            "DUPLICATE_ALLOCATION",
        ),
        ([AllocationRequest(1, Decimal("200.01"))], "ALLOCATION_EXCEEDS_OUTSTANDING"),
        (
            [
                AllocationRequest(1, Decimal("200.00")),
                AllocationRequest(2, Decimal("100.00")),
                AllocationRequest(3, Decimal("300.00")),
            ],
            "ALLOCATION_EXCEEDS_PAYMENT",
        ),
        ([AllocationRequest(1, Decimal("150.00"))], "PARTIAL_PAYMENT_NOT_ALLOWED"),
    ],
)
def test_validate_allocations_refusals(requests: list[AllocationRequest], code: str) -> None:
    outstanding = {1: Decimal("200.00"), 2: Decimal("100.00"), 3: Decimal("300.00")}
    with pytest.raises(DomainError) as exc:
        validate_allocations(Decimal("500.00"), requests, outstanding, allow_partial=False)
    assert exc.value.code == code


def test_partial_allowed_by_policy_and_credit_spend_must_be_whole() -> None:
    plan = validate_allocations(
        Decimal("150.00"),
        [AllocationRequest(1, Decimal("150.00"))],
        {1: Decimal("200.00")},
        allow_partial=True,
    )
    assert plan.unallocated == 0
    with pytest.raises(DomainError) as exc:
        validate_allocations(
            Decimal("150.00"),
            [AllocationRequest(1, Decimal("100.00"))],
            {1: Decimal("200.00")},
            allow_partial=True,
            require_full=True,
        )
    assert exc.value.code == "ALLOCATION_INCOMPLETE"


@given(amounts, open_invoices(), st.booleans())
def test_auto_allocate_oldest_first(
    payment: Decimal, invoices: list[OpenInvoice], allow_partial: bool
) -> None:
    plan = auto_allocate(payment, invoices, allow_partial=allow_partial)
    assert plan.allocated + plan.unallocated == payment
    assert plan.unallocated >= 0
    got = {a.invoice_id: a.amount for a in plan.allocations}
    ordered = sorted(invoices, key=lambda i: (i.approved_at, i.invoice_id))
    # Allocations are listed oldest first and never exceed what is owed.
    assert [a.invoice_id for a in plan.allocations] == [
        i.invoice_id for i in ordered if i.invoice_id in got
    ]
    for inv in ordered:
        assert got.get(inv.invoice_id, ZERO) <= inv.outstanding
    # The plan always passes explicit validation.
    validate_allocations(
        payment,
        plan.allocations,
        {i.invoice_id: i.outstanding for i in invoices},
        allow_partial=allow_partial,
    )
    if allow_partial:
        # Strict oldest first: a later invoice gets money only once earlier ones are paid.
        short = False
        for inv in ordered:
            if short:
                assert inv.invoice_id not in got
            if got.get(inv.invoice_id, ZERO) < inv.outstanding:
                short = True
        if short:
            assert plan.unallocated == 0
    else:
        # Whole invoices only; an invoice is skipped only if it did not fit what was left.
        left = payment
        for inv in ordered:
            if inv.outstanding <= left:
                assert got[inv.invoice_id] == inv.outstanding
                left -= inv.outstanding
            else:
                assert inv.invoice_id not in got


# --- records, reversals and de-allocation ------------------------------------------------------


@st.composite
def records(draw: st.DrawFn) -> list[AllocationRecord]:
    """Positive allocation rows for payments 1-3 over invoices 1-3, some partially reversed."""
    out: list[AllocationRecord] = []
    for seq in range(1, draw(st.integers(0, 8)) + 1):
        pid = draw(st.integers(1, 3))
        out.append(
            AllocationRecord(
                payment_id=pid,
                invoice_id=draw(st.integers(1, 3)),
                amount=draw(amounts),
                seq=seq,
                pending=pid == 2,
                from_credit=pid == 3,
            )
        )
    return out


@given(records(), st.integers(1, 3))
def test_reverse_payment_brings_its_allocations_to_zero(
    rows: list[AllocationRecord], pid: int
) -> None:
    drafts = reverse_payment(pid, rows)
    assert all(d.amount < 0 and d.payment_id == pid for d in drafts)
    after = rows + [
        AllocationRecord(d.payment_id, d.invoice_id, d.amount, seq=1000 + i)
        for i, d in enumerate(drafts)
    ]
    assert net_by_payment(after).get(pid, ZERO) == 0
    # Other payments are untouched.
    for other, net in net_by_payment(rows).items():
        if other != pid:
            assert net_by_payment(after)[other] == net


@given(records(), st.integers(1, 3), st.data())
def test_deallocate_excess_prefers_pending_then_newest(
    rows: list[AllocationRecord], invoice_id: int, data: st.DataObject
) -> None:
    net = net_by_invoice(rows).get(invoice_id, ZERO)
    excess = data.draw(st.decimals(min_value=0, max_value=net, places=2))
    drafts = deallocate_excess(invoice_id, rows, excess)
    assert sum((d.amount for d in drafts), ZERO) == -excess
    assert all(d.invoice_id == invoice_id and d.amount < 0 for d in drafts)
    per_payment: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for r in rows:
        if r.invoice_id == invoice_id:
            per_payment[r.payment_id] += r.amount
    for d in drafts:
        per_payment[d.payment_id] += d.amount
    assert all(v >= 0 for v in per_payment.values())
    # A confirmed payment is touched only when every pending one is fully de-allocated.
    if any(d.payment_id != 2 for d in drafts):
        assert per_payment.get(2, ZERO) == 0


def test_deallocate_more_than_allocated_is_refused() -> None:
    rows = [AllocationRecord(1, 1, Decimal("10.00"), seq=1)]
    with pytest.raises(DomainError) as exc:
        deallocate_excess(1, rows, Decimal("10.01"))
    assert exc.value.code == "DEALLOCATION_EXCEEDS_ALLOCATED"


def test_unallocated_and_nets() -> None:
    rows = [
        AllocationRecord(1, 1, Decimal("60.00"), seq=1),
        AllocationRecord(1, 2, Decimal("30.00"), seq=2),
        AllocationRecord(1, 1, Decimal("-20.00"), seq=3),
    ]
    assert unallocated(Decimal("100.00"), rows) == Decimal("30.00")
    assert net_by_invoice(rows) == {1: Decimal("40.00"), 2: Decimal("30.00")}
    with pytest.raises(DomainError) as exc:
        unallocated(Decimal("50.00"), rows)
    assert exc.value.code == "ALLOCATION_EXCEEDS_PAYMENT"


# --- patient credit -----------------------------------------------------------------------------


@given(
    st.decimals(min_value=-1000, max_value=100000, places=2),
    st.lists(st.decimals(min_value=0, max_value=1000, places=2), max_size=4),
)
def test_spendable_credit_excludes_pending_money(balance: Decimal, pending: list[Decimal]) -> None:
    s = spendable_credit(balance, pending)
    assert s == max(balance - sum(pending, ZERO), ZERO)
    assert ZERO <= s <= max(balance, ZERO)


def test_credit_spend_and_refund_limits() -> None:
    validate_credit_spend(Decimal("10.00"), Decimal("10.00"))
    with pytest.raises(DomainError) as exc:
        validate_credit_spend(Decimal("10.01"), Decimal("10.00"))
    assert exc.value.code == "INSUFFICIENT_CREDIT"
    ok = Approval(approver_id=3, at=T0, reason="test cancelled, sample damaged")
    validate_refund(
        Decimal("5.00"), source_available=Decimal("5.00"), spendable=Decimal("9.00"), approval=ok
    )
    with pytest.raises(DomainError) as exc:
        validate_refund(
            Decimal("6.00"),
            source_available=Decimal("5.00"),
            spendable=Decimal("9.00"),
            approval=ok,
        )
    assert exc.value.code == "REFUND_EXCEEDS_SOURCE"
    with pytest.raises(DomainError) as exc:
        validate_refund(
            Decimal("5.00"),
            source_available=Decimal("5.00"),
            spendable=Decimal("4.00"),
            approval=ok,
        )
    assert exc.value.code == "REFUND_EXCEEDS_CREDIT"
    # Invariant 4: a refund records its approver, time and reason.
    with pytest.raises(TypeError):
        validate_refund(
            Decimal("1.00"),
            source_available=Decimal("5.00"),
            spendable=Decimal("9.00"),
            approval=None,  # type: ignore[arg-type]
        )


# --- rejection plan ------------------------------------------------------------------------------


def test_rejection_of_pending_transfer_only_reverses_its_own_rows() -> None:
    rows = [
        AllocationRecord(1, 1, Decimal("600.00"), seq=1, pending=True),
        AllocationRecord(2, 2, Decimal("300.00"), seq=2),
    ]
    plan = plan_rejection(1, Decimal("1000.00"), rows, pending=True, spendable=ZERO)
    assert [(d.payment_id, d.invoice_id, d.amount) for d in plan.reversals] == [
        (1, 1, Decimal("-600.00"))
    ]
    assert plan.recovery == ()
    assert plan.uncovered == 0


def test_rejection_of_pending_transfer_never_recovers_spent_credit() -> None:
    # Regression (stateful machine): a pending transfer's remainder is never spendable, so
    # even with the pool already short (an earlier bounce) its rejection takes back nothing.
    rows = [
        AllocationRecord(1, 1, Decimal("5.00"), seq=1, pending=True),
        AllocationRecord(3, 2, Decimal("1205.00"), seq=2, from_credit=True),
    ]
    plan = plan_rejection(1, Decimal("10.14"), rows, pending=True, spendable=ZERO)
    assert [d.amount for d in plan.reversals] == [Decimal("-5.00")]
    assert plan.recovery == ()
    assert plan.uncovered == 0


def test_bounce_is_covered_by_confirmed_credit_only() -> None:
    # Regression (stateful machine): confirmed 1205 spent in full by credit payment 3 while a
    # 0.01 transfer was pending. The pool holds 0.01, but it is pending money: the whole
    # spend is taken back, not 1204.99 of it.
    rows = [AllocationRecord(3, 2, Decimal("1205.00"), seq=1, from_credit=True)]
    spendable = spendable_credit(Decimal("0.01"), [Decimal("0.01")])
    plan = plan_rejection(1, Decimal("1205.00"), rows, pending=False, spendable=spendable)
    assert [(d.payment_id, d.amount) for d in plan.recovery] == [(3, Decimal("-1205.00"))]
    assert plan.uncovered == 0


def test_rejection_after_credit_was_spent_recovers_newest_credit_spend_first() -> None:
    # Confirmed transfer 1000: 600 to invoice 1, 400 left as credit, later spent by credit
    # payment 3 on invoices 2 (150) and 3 (250). The bank then reverses the transfer.
    rows = [
        AllocationRecord(1, 1, Decimal("600.00"), seq=1),
        AllocationRecord(3, 2, Decimal("150.00"), seq=2, from_credit=True),
        AllocationRecord(3, 3, Decimal("250.00"), seq=3, from_credit=True),
    ]
    plan = plan_rejection(1, Decimal("1000.00"), rows, pending=False, spendable=ZERO)
    assert [(d.invoice_id, d.amount) for d in plan.reversals] == [(1, Decimal("-600.00"))]
    assert [(d.payment_id, d.invoice_id, d.amount) for d in plan.recovery] == [
        (3, 3, Decimal("-250.00")),
        (3, 2, Decimal("-150.00")),
    ]
    assert plan.uncovered == 0


@given(records(), st.decimals(min_value=0, max_value=100000, places=2), st.data())
def test_rejection_plan_takes_back_exactly_what_confirmed_credit_cannot_cover(
    rows: list[AllocationRecord], extra: Decimal, data: st.DataObject
) -> None:
    pid = data.draw(st.sampled_from([1, 2]))  # payment 2 is the pending one in records()
    pending = pid == 2
    allocated = net_by_payment(rows).get(pid, ZERO)
    amount = allocated + extra
    assume(amount > 0)
    spendable = data.draw(st.decimals(min_value=0, max_value=100000, places=2))
    plan = plan_rejection(pid, amount, rows, pending=pending, spendable=spendable)
    # Its own allocations are always reversed in full.
    assert all(d.payment_id == pid for d in plan.reversals)
    assert -sum((d.amount for d in plan.reversals), ZERO) == allocated
    taken = sum((-d.amount for d in plan.recovery), ZERO)
    if pending:
        # Pending money was never spendable: nothing elsewhere is taken back or reported.
        assert (plan.recovery, plan.uncovered) == ((), ZERO)
        return
    # The remainder leaves the pool; spendable credit covers what it can, the rest was spent.
    assert taken + plan.uncovered == max(extra - spendable, ZERO)
    # Recovery only ever takes back credit-funded allocations, and never more than they hold.
    for d in plan.recovery:
        assert d.payment_id == 3
    nets = net_by_payment(rows)
    assert taken <= nets.get(3, ZERO)
    if plan.uncovered > 0:
        assert taken == nets.get(3, ZERO)


def test_later_allocation_is_capped_by_the_credit_pool() -> None:
    # Spending patient credit draws on the pooled balance, not on a particular payment, so a
    # payment's own remainder can be larger than what the patient still holds.
    assert later_allocation_limit(
        Decimal("500.00"),
        pending=False,
        credit_balance=Decimal("200.00"),
        spendable=Decimal("200.00"),
    ) == Decimal("200.00")
    # Confirmed money is further limited to spendable (it must not use pending money).
    assert later_allocation_limit(
        Decimal("500.00"),
        pending=False,
        credit_balance=Decimal("900.00"),
        spendable=Decimal("100.00"),
    ) == Decimal("100.00")
    # A pending payment may allocate its own remainder (pending money settles lines).
    assert later_allocation_limit(
        Decimal("500.00"), pending=True, credit_balance=Decimal("900.00"), spendable=Decimal("0.00")
    ) == Decimal("500.00")
    assert later_allocation_limit(
        Decimal("500.00"), pending=True, credit_balance=Decimal("-5.00"), spendable=Decimal("0.00")
    ) == Decimal("0.00")


@given(
    st.decimals(min_value=0, max_value=1000, places=2),
    st.booleans(),
    st.decimals(min_value=-100, max_value=1000, places=2),
    st.decimals(min_value=0, max_value=1000, places=2),
)
def test_later_allocation_limit_bounds(
    remainder: Decimal, pending: bool, balance: Decimal, spendable: Decimal
) -> None:
    limit = later_allocation_limit(
        remainder, pending=pending, credit_balance=balance, spendable=spendable
    )
    assert ZERO <= limit <= remainder
    assert limit <= max(balance, ZERO)
    if not pending:
        assert limit <= spendable
