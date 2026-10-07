from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.coverage import CoverageRule, split_line
from domain.errors import DomainError
from domain.invoice import (
    BillableLine,
    CreditLineDraft,
    InvoiceLineDraft,
    InvoiceStatus,
    Rebill,
    approve,
    build_credit_line,
    build_invoice_lines,
    credited_quantity,
    invoice_position,
    invoice_totals,
    payer_totals,
    require_editable,
    void,
)
from domain.money import ZERO
from domain.pricing import PriceVersion, unit_price
from domain.service_line import BillingStatus, FulfilmentStatus, LineStatus
from domain.tests.strategies import invoice_lines

OK = Approval(approver_id=1, at=datetime(2026, 10, 7, tzinfo=UTC), reason="x")
V1 = PriceVersion(1, date(2026, 1, 1), {"CONS": Decimal("5000.00"), "CBC": Decimal("3000.00")})
V2 = PriceVersion(2, date(2026, 10, 1), {"CONS": Decimal("6000.00"), "CBC": Decimal("3500.00")})
VERSIONS = (V1, V2)


def _billable(sid: int, item: str = "CONS", **kw: object) -> BillableLine:
    return BillableLine(
        service_line_id=sid,
        item=item,
        quantity=1,
        status=LineStatus(),
        price_versions=VERSIONS,
        **kw,  # type: ignore[arg-type]
    )


# --- invoice status -------------------------------------------------------------------


def test_invoice_status_edges() -> None:
    assert approve(InvoiceStatus.DRAFT) is InvoiceStatus.APPROVED
    assert void(InvoiceStatus.DRAFT, OK) is InvoiceStatus.VOID
    for status in (InvoiceStatus.APPROVED, InvoiceStatus.VOID):
        with pytest.raises(DomainError) as exc:
            approve(status)
        assert exc.value.code == "INVOICE_NOT_DRAFT"
    with pytest.raises(DomainError) as exc:
        void(InvoiceStatus.APPROVED, OK)
    assert exc.value.code == "INVOICE_FROZEN"
    with pytest.raises(DomainError) as exc:
        require_editable(InvoiceStatus.APPROVED)
    assert exc.value.code == "INVOICE_FROZEN"
    require_editable(InvoiceStatus.DRAFT)


# --- building lines (invariant 6) -------------------------------------------------------


@given(st.integers(-30, 400), st.lists(st.sampled_from(["CONS", "CBC"]), min_size=1, max_size=5))
def test_lines_freeze_the_price_effective_on_the_approval_day(
    offset: int, items: list[str]
) -> None:
    on = date(2026, 1, 1) + timedelta(days=offset)
    billables = [_billable(i + 1, item) for i, item in enumerate(items)]
    if on < V1.effective_from:
        with pytest.raises(DomainError) as exc:
            build_invoice_lines(billables, on)
        assert exc.value.code == "NO_EFFECTIVE_PRICE_LIST"
        return
    lines = build_invoice_lines(billables, on)
    assert [ln.position for ln in lines] == list(range(1, len(items) + 1))
    for line, item in zip(lines, items, strict=True):
        assert line.unit_price == unit_price(VERSIONS, item, on)
        assert line.price_version_id == (2 if on >= V2.effective_from else 1)
        assert line.gross == line.unit_price * line.quantity


def test_line_split_follows_coverage_and_discount() -> None:
    rule = CoverageRule.percentage(Decimal(70))
    lines = build_invoice_lines(
        [
            _billable(1, payer_id=9, coverage=rule, discount=Decimal("100.00")),
            _billable(2, "CBC", payer_id=9, coverage=rule, excluded=True),
            BillableLine(3, "CBC", 3, LineStatus(), VERSIONS),
        ],
        date(2026, 10, 7),
    )
    a, b, c = lines
    assert (a.gross, a.payer_share, a.discount, a.patient_share) == (
        Decimal("6000.00"),
        Decimal("4200.00"),
        Decimal("100.00"),
        Decimal("1700.00"),
    )
    assert (b.payer_share, b.patient_share) == (ZERO, Decimal("3500.00"))
    assert (c.gross, c.payer_id, c.patient_share) == (
        Decimal("10500.00"),
        None,
        Decimal("10500.00"),
    )
    totals = invoice_totals(lines)
    assert totals.gross == Decimal("20000.00")
    assert totals.gross == totals.discount + totals.payer_share + totals.patient_share
    assert payer_totals(lines) == {9: Decimal("4200.00")}


def test_build_refusals() -> None:
    on = date(2026, 10, 7)
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([], on)
    assert exc.value.code == "INVOICE_EMPTY"
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([_billable(1), _billable(1)], on)
    assert exc.value.code == "DUPLICATE_LINE"
    invoiced = BillableLine(1, "CONS", 1, LineStatus(BillingStatus.INVOICED), VERSIONS)
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([invoiced], on)
    assert exc.value.code == "LINE_NOT_BILLABLE"
    cancelled = BillableLine(
        1, "CONS", 1, LineStatus(fulfilment=FulfilmentStatus.CANCELLED), VERSIONS
    )
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([cancelled], on)
    assert exc.value.code == "LINE_CANCELLED"
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([BillableLine(1, "CONS", 0, LineStatus(), VERSIONS)], on)
    assert exc.value.code == "INVALID_QUANTITY"
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([_billable(1, coverage=CoverageRule.percentage(Decimal(50)))], on)
    assert exc.value.code == "COVERAGE_WITHOUT_PAYER"
    pre = CoverageRule.percentage(Decimal(50), requires_preapproval=True)
    with pytest.raises(DomainError) as exc:
        build_invoice_lines([_billable(1, payer_id=2, coverage=pre)], on)
    assert exc.value.code == "PREAPPROVAL_REQUIRED"
    line = build_invoice_lines([_billable(1, payer_id=2, coverage=pre, preapproval_ref="PA1")], on)
    assert line[0].preapproval_ref == "PA1"


def test_draft_line_must_be_internally_consistent() -> None:
    with pytest.raises(DomainError) as exc:
        InvoiceLineDraft(
            1, 1, "X", 1, Decimal("10.00"), 1, Decimal("10.00"), ZERO, None, ZERO, Decimal("9.00")
        )
    assert exc.value.code == "INVALID_INVOICE_LINE"
    with pytest.raises(DomainError):
        InvoiceLineDraft(
            1,
            1,
            "X",
            1,
            Decimal("10.00"),
            1,
            Decimal("10.00"),
            ZERO,
            None,
            Decimal("1.00"),
            Decimal("9.00"),
        )


# --- position: allocation applied in line order ------------------------------------------


@given(invoice_lines(), st.lists(st.decimals(min_value=0, max_value=200000, places=2), max_size=4))
def test_position_applies_money_in_line_order(
    lines: tuple[InvoiceLineDraft, ...], allocations: list[Decimal]
) -> None:
    pos = invoice_position(lines, (), allocations)
    total_due = sum((ln.patient_share for ln in lines), ZERO)
    allocated = sum(allocations, ZERO)
    assert pos.patient_due == total_due
    assert pos.allocated == allocated
    assert pos.applied == min(allocated, total_due)
    assert pos.outstanding == total_due - pos.applied
    assert pos.over_allocation == max(allocated - total_due, ZERO)
    assert sum((lp.patient_paid for lp in pos.lines), ZERO) == pos.applied
    seen_unpaid = False
    for lp in pos.lines:
        assert lp.outstanding == lp.patient_due - lp.patient_paid >= 0
        # Prefix property: once a line is short, no later line receives money.
        if seen_unpaid:
            assert lp.patient_paid == 0
        if lp.outstanding > 0:
            seen_unpaid = True
        assert lp.settled is (lp.outstanding == 0 and not lp.fully_credited)


@given(
    invoice_lines(),
    st.decimals(min_value=0, max_value=100000, places=2),
    st.decimals(min_value=0, max_value=100000, places=2),
)
def test_more_money_never_unsettles_a_line(
    lines: tuple[InvoiceLineDraft, ...], a: Decimal, b: Decimal
) -> None:
    lo, hi = sorted((a, b))
    assert invoice_position(lines, (), [lo]).settled_positions <= (
        invoice_position(lines, (), [hi]).settled_positions
    )


@given(invoice_lines())
def test_zero_patient_share_lines_settle_without_money(lines: tuple[InvoiceLineDraft, ...]) -> None:
    pos = invoice_position(lines)
    assert pos.settled_positions == {ln.position for ln in lines if ln.patient_share == 0}


def test_negative_net_allocation_is_inconsistent() -> None:
    line = InvoiceLineDraft(
        1, 1, "X", 1, Decimal("10.00"), 1, Decimal("10.00"), ZERO, None, ZERO, Decimal("10.00")
    )
    with pytest.raises(DomainError) as exc:
        invoice_position([line], (), [Decimal("5.00"), Decimal("-6.00")])
    assert exc.value.code == "ALLOCATION_NEGATIVE"


# --- credits (invariant 2: corrections are linked documents) ------------------------------


@given(invoice_lines(max_size=3), st.data())
def test_partial_credits_add_up_exactly_to_the_line(
    lines: tuple[InvoiceLineDraft, ...], data: st.DataObject
) -> None:
    line = lines[0]
    credits: list[CreditLineDraft] = []
    remaining = line.quantity
    while remaining:
        qty = data.draw(st.integers(1, remaining))
        c = build_credit_line(line, qty, credits)
        assert min(c.gross, c.discount, c.payer_share, c.patient_share) >= 0
        assert c.gross == c.discount + c.payer_share + c.patient_share
        credits.append(c)
        remaining -= qty
        assert credited_quantity(line.position, credits) == line.quantity - remaining
        for attr in ("gross", "discount", "payer_share", "patient_share"):
            assert sum((getattr(x, attr) for x in credits), ZERO) <= getattr(line, attr)
    for attr in ("gross", "discount", "payer_share", "patient_share"):
        assert sum((getattr(x, attr) for x in credits), ZERO) == getattr(line, attr)
    pos = invoice_position(lines, credits)
    assert pos.line(line.position).fully_credited
    assert not pos.line(line.position).settled
    assert pos.line(line.position).patient_due == 0
    with pytest.raises(DomainError) as exc:
        build_credit_line(line, 1, credits)
    assert exc.value.code == "CREDIT_EXCEEDS_LINE"


@given(invoice_lines(), st.data())
def test_credit_after_payment_creates_over_allocation(
    lines: tuple[InvoiceLineDraft, ...], data: st.DataObject
) -> None:
    due = sum((ln.patient_share for ln in lines), ZERO)
    paid = data.draw(st.decimals(min_value=0, max_value=due, places=2))
    victim = data.draw(st.sampled_from(lines))
    credit = build_credit_line(victim, victim.quantity)
    pos = invoice_position(lines, [credit], [paid])
    assert pos.patient_due == due - victim.patient_share
    assert pos.over_allocation == max(paid - pos.patient_due, ZERO)
    assert pos.applied + pos.over_allocation == paid


def test_credit_line_refusals() -> None:
    line = InvoiceLineDraft(
        1, 1, "X", 2, Decimal("10.00"), 1, Decimal("20.00"), ZERO, None, ZERO, Decimal("20.00")
    )
    with pytest.raises(DomainError) as exc:
        build_credit_line(line, 0)
    assert exc.value.code == "INVALID_QUANTITY"
    with pytest.raises(DomainError) as exc:
        build_credit_line(line, 3)
    assert exc.value.code == "CREDIT_EXCEEDS_LINE"
    bogus = CreditLineDraft(
        position=7,
        quantity=1,
        gross=Decimal("1.00"),
        discount=ZERO,
        payer_id=None,
        payer_share=ZERO,
        patient_share=Decimal("1.00"),
    )
    with pytest.raises(DomainError) as exc:
        invoice_position([line], [bogus])
    assert exc.value.code == "UNKNOWN_INVOICE_LINE"
    too_much = CreditLineDraft(
        position=1,
        quantity=1,
        gross=Decimal("21.00"),
        discount=ZERO,
        payer_id=None,
        payer_share=ZERO,
        patient_share=Decimal("21.00"),
    )
    with pytest.raises(DomainError) as exc:
        invoice_position([line], [too_much])
    assert exc.value.code == "CREDIT_EXCEEDS_LINE"


# --- rebills (payer rejection moved to the patient) ---------------------------------------


def test_rebill_moves_payer_share_onto_the_patient_due() -> None:
    split = split_line(Decimal("10000.00"), ZERO, CoverageRule.percentage(Decimal(70)))
    line = InvoiceLineDraft(
        1, 1, "X", 1, split.gross, 1, split.gross, ZERO, 4, split.payer_share, split.patient_share
    )
    paid = invoice_position([line], (), [Decimal("3000.00")])
    assert paid.line(1).settled
    rebilled = invoice_position([line], (), [Decimal("3000.00")], [Rebill(1, Decimal("2000.00"))])
    assert rebilled.outstanding == Decimal("2000.00")
    assert not rebilled.line(1).settled
    with pytest.raises(DomainError) as exc:
        invoice_position([line], (), (), [Rebill(1, Decimal("7000.01"))])
    assert exc.value.code == "REBILL_EXCEEDS_PAYER_SHARE"
