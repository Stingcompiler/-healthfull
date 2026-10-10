"""Report arithmetic (FEATURES 12.x): pure rules the report queries apply to aggregates."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain import reports as dr
from domain.errors import DomainError
from domain.money import ZERO

D = Decimal


def money_amounts() -> st.SearchStrategy[Decimal]:
    return st.decimals(min_value=0, max_value=10**8, places=2)


# --- age buckets ---------------------------------------------------------------------------


@given(st.integers(min_value=0, max_value=5000))
def test_every_age_falls_in_exactly_one_bucket(days: int) -> None:
    key = dr.age_bucket(days)
    assert key in dr.AGE_BUCKET_KEYS
    lower, upper = dr.bucket_bounds(key)
    assert lower <= days
    assert upper is None or days <= upper


@given(st.integers(min_value=0, max_value=5000), st.integers(min_value=0, max_value=5000))
def test_older_never_lands_in_a_younger_bucket(a: int, b: int) -> None:
    young, old = sorted((a, b))
    keys = list(dr.AGE_BUCKET_KEYS)
    assert keys.index(dr.age_bucket(young)) <= keys.index(dr.age_bucket(old))


@pytest.mark.parametrize(
    ("days", "key"),
    [
        (0, "age_0_1"),
        (1, "age_0_1"),
        (2, "age_2_3"),
        (7, "age_4_7"),
        (30, "age_8_30"),
        (31, "age_over_30"),
    ],
)
def test_bucket_edges(days: int, key: str) -> None:
    assert dr.age_bucket(days) == key


def test_negative_age_is_refused() -> None:
    with pytest.raises(DomainError) as err:
        dr.age_bucket(-1)
    assert err.value.code == "INVALID_DATE_RANGE"


# --- revenue -------------------------------------------------------------------------------


@given(money_amounts(), money_amounts(), money_amounts(), money_amounts())
def test_net_revenue_is_gross_less_discount_less_net_credits(
    gross: Decimal, discount: Decimal, credited: Decimal, credited_discount: Decimal
) -> None:
    r = dr.RevenueTotals(gross, discount, credited, credited_discount)
    assert r.net == gross - discount - (credited - credited_discount)
    # The same split the ledger books: REVENUE (gross - credited) less DISCOUNT.
    assert r.net == (gross - credited) - (discount - credited_discount)


@given(st.lists(st.tuples(money_amounts(), money_amounts()), max_size=20))
def test_revenue_totals_add_up(parts: list[tuple[Decimal, Decimal]]) -> None:
    rows = [dr.RevenueTotals(g, d, ZERO, ZERO) for g, d in parts]
    total = dr.add_revenue(rows)
    assert total.gross == sum((g for g, _ in parts), ZERO)
    assert total.net == sum((r.net for r in rows), ZERO)


# --- collections ---------------------------------------------------------------------------


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["cash", "bank_transfer", "qr", "card", "patient_credit"]),
            st.sampled_from(["pending", "confirmed", "rejected"]),
            money_amounts(),
        ),
        max_size=30,
    )
)
def test_pending_money_is_never_collected(rows: list[tuple[str, str, Decimal]]) -> None:
    c = dr.collections(rows)
    expected_confirmed = sum(
        (
            a
            for method, v, a in rows
            if method == "cash" or (method in ("bank_transfer", "qr", "card") and v == "confirmed")
        ),
        ZERO,
    )
    pending = sum(
        (a for meth, v, a in rows if meth in ("bank_transfer", "qr", "card") and v == "pending"),
        ZERO,
    )
    assert c.confirmed == expected_confirmed
    assert c.pending == pending
    # Spent credit is not new money; neither pending nor rejected transfers are collected.
    assert c.confirmed + c.pending + c.rejected + c.credit_used == sum((a for *_, a in rows), ZERO)


# --- shift variances -----------------------------------------------------------------------


@given(st.lists(st.decimals(min_value=-100000, max_value=100000, places=2), max_size=30))
def test_variances_split_into_short_and_over(values: list[Decimal]) -> None:
    v = dr.variances(values)
    assert v.short <= ZERO <= v.over
    assert v.net == v.short + v.over == sum(values, ZERO)
    assert v.count_short == sum(1 for x in values if x < 0)
    assert v.count_over == sum(1 for x in values if x > 0)


# --- shares --------------------------------------------------------------------------------


@given(st.integers(min_value=0, max_value=10**6), st.integers(min_value=1, max_value=10**6))
def test_share_percent_is_bounded_when_part_fits(part: int, whole: int) -> None:
    part = min(part, whole)
    p = dr.share_percent(part, whole)
    assert p is not None
    assert D("0.0") <= p <= D("100.0")
    assert p == p.quantize(D("0.1"))


def test_share_of_nothing_is_unknown() -> None:
    assert dr.share_percent(0, 0) is None
