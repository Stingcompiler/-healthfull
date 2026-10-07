"""Shared Hypothesis strategies for domain tests (not a test module)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import strategies as st

from domain.coverage import CoverageKind, CoverageRule, payer_share_for
from domain.invoice import InvoiceLineDraft

MAX_TEST_AMOUNT = Decimal("1000000")

amounts = st.decimals(min_value=0, max_value=MAX_TEST_AMOUNT, places=2)
positive_amounts = st.decimals(min_value=Decimal("0.01"), max_value=MAX_TEST_AMOUNT, places=2)
percents = st.decimals(min_value=0, max_value=100, places=2)


@st.composite
def coverage_rules(draw: st.DrawFn) -> CoverageRule:
    kind = draw(st.sampled_from(list(CoverageKind)))
    if kind is CoverageKind.PERCENTAGE:
        return CoverageRule.percentage(draw(percents))
    if kind is CoverageKind.FIXED_PATIENT_COPAY:
        return CoverageRule.fixed_copay(draw(amounts))
    return CoverageRule.capped(draw(amounts), payer_percent=draw(percents))


@st.composite
def invoice_line(draw: st.DrawFn, position: int, service_line_id: int) -> InvoiceLineDraft:
    quantity = draw(st.integers(1, 30))
    unit = draw(st.decimals(min_value=0, max_value=Decimal("50000"), places=2))
    gross = unit * quantity
    payer_id = draw(st.none() | st.integers(1, 3))
    rule = draw(coverage_rules()) if payer_id is not None else None
    payer = payer_share_for(gross, rule)
    discount = draw(st.decimals(min_value=0, max_value=gross - payer, places=2))
    return InvoiceLineDraft(
        position=position,
        service_line_id=service_line_id,
        item="X",
        quantity=quantity,
        unit_price=unit,
        price_version_id=1,
        gross=gross,
        discount=discount,
        payer_id=payer_id if payer > 0 else None,
        payer_share=payer,
        patient_share=gross - payer - discount,
    )


@st.composite
def invoice_lines(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 6
) -> tuple[InvoiceLineDraft, ...]:
    n = draw(st.integers(min_size, max_size))
    return tuple(draw(invoice_line(i + 1, 100 + i)) for i in range(n))
