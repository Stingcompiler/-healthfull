from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.money import HUNDRED, q
from domain.pricing import (
    PriceVersion,
    RoundingRule,
    RoundMode,
    bulk_percentage_update,
    effective_version,
    round_price,
    unit_price,
    validate_new_version,
)

D0 = date(2026, 1, 1)
prices = st.decimals(min_value=0, max_value=Decimal("10000000"), places=2)
steps = st.sampled_from([Decimal(s) for s in ("0.01", "0.05", "0.50", "1", "5", "10", "50", "100")])
modes = st.sampled_from(list(RoundMode))
percents = st.decimals(min_value=Decimal("-99.99"), max_value=Decimal("500"), places=2)


@st.composite
def version_lists(draw: st.DrawFn) -> list[PriceVersion]:
    offsets = draw(st.lists(st.integers(0, 3000), min_size=1, max_size=8, unique=True))
    return [
        PriceVersion(
            version_id=i + 1,
            effective_from=D0 + timedelta(days=o),
            prices={"CONS": Decimal(1000 + o)},
        )
        for i, o in enumerate(offsets)
    ]


# --- effective version (invariant 6) ---------------------------------------------------


@given(version_lists(), st.integers(-10, 3100))
def test_effective_version_is_latest_started_on_or_before_the_date(
    versions: list[PriceVersion], offset: int
) -> None:
    on = D0 + timedelta(days=offset)
    started = [v for v in versions if v.effective_from <= on]
    if not started:
        with pytest.raises(DomainError) as exc:
            effective_version(versions, on)
        assert exc.value.code == "NO_EFFECTIVE_PRICE_LIST"
        return
    chosen = effective_version(versions, on)
    assert chosen.effective_from == max(v.effective_from for v in started)
    assert chosen.effective_from <= on
    # Order of the input never matters.
    assert effective_version(list(reversed(versions)), on) == chosen
    assert unit_price(versions, "CONS", on) == chosen.prices["CONS"]


def test_version_takes_effect_on_its_first_day() -> None:
    v1 = PriceVersion(1, date(2026, 1, 1), {"X": Decimal("100.00")})
    v2 = PriceVersion(2, date(2026, 3, 1), {"X": Decimal("120.00")})
    assert unit_price([v1, v2], "X", date(2026, 2, 28)) == Decimal("100.00")
    assert unit_price([v1, v2], "X", date(2026, 3, 1)) == Decimal("120.00")


def test_unknown_item_has_no_price() -> None:
    v1 = PriceVersion(1, D0, {"X": Decimal("1.00")})
    with pytest.raises(DomainError) as exc:
        unit_price([v1], "Y", D0)
    assert exc.value.code == "PRICE_NOT_FOUND"


def test_versions_reject_bad_prices() -> None:
    with pytest.raises(DomainError) as exc:
        PriceVersion(1, D0, {"X": Decimal("-1.00")})
    assert exc.value.code == "INVALID_PRICE"
    with pytest.raises(DomainError):
        PriceVersion(1, D0, {"X": Decimal("1.005")})


def test_new_version_date_rules() -> None:
    v1 = PriceVersion(1, date(2026, 10, 1), {})
    today = date(2026, 10, 7)
    validate_new_version([v1], date(2026, 10, 8), today)
    validate_new_version([v1], date(2026, 11, 1), today)
    # Only a list with nothing effective yet may start today (no invoice priced from it).
    validate_new_version([], today, today)
    validate_new_version([PriceVersion(3, date(2026, 12, 1), {})], today, today)
    with pytest.raises(DomainError) as exc:
        validate_new_version([v1], date(2026, 10, 6), today)
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    # A second version effective today would give one day two prices (invariant 6).
    with pytest.raises(DomainError) as exc:
        validate_new_version([v1], today, today)
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    v2 = PriceVersion(2, date(2026, 11, 1), {})
    with pytest.raises(DomainError) as exc:
        validate_new_version([v1, v2], date(2026, 11, 1), today)
    assert exc.value.code == "PRICE_VERSION_DATE_TAKEN"


# --- rounding -------------------------------------------------------------------------


@given(prices, steps, modes)
def test_round_price_lands_on_a_step_near_the_amount(
    x: Decimal, step: Decimal, mode: RoundMode
) -> None:
    r = round_price(x, RoundingRule(step, mode))
    assert r % step == 0
    assert r >= 0
    assert r == q(r)
    if mode is RoundMode.UP:
        assert x <= r < x + step
    elif mode is RoundMode.DOWN:
        assert x - step < r <= x
    else:
        assert abs(r - x) <= step / 2


@given(prices, prices, steps, modes)
def test_round_price_is_monotonic(a: Decimal, b: Decimal, step: Decimal, mode: RoundMode) -> None:
    lo, hi = sorted((a, b))
    rule = RoundingRule(step, mode)
    assert round_price(lo, rule) <= round_price(hi, rule)


def test_round_price_known_values() -> None:
    assert round_price(Decimal("1234.50"), RoundingRule(Decimal(5))) == Decimal("1235.00")
    assert round_price(Decimal("1232.49"), RoundingRule(Decimal(5))) == Decimal("1230.00")
    assert round_price(Decimal("1232.50"), RoundingRule(Decimal(5))) == Decimal("1235.00")
    assert round_price(Decimal("1201.00"), RoundingRule(Decimal(100), RoundMode.UP)) == Decimal(
        "1300.00"
    )
    assert round_price(Decimal("1299.99"), RoundingRule(Decimal(100), RoundMode.DOWN)) == Decimal(
        "1200.00"
    )


@pytest.mark.parametrize("bad", [Decimal(0), Decimal("-1"), Decimal("0.001")])
def test_rounding_step_must_be_positive_money(bad: Decimal) -> None:
    with pytest.raises(DomainError) as exc:
        RoundingRule(bad)
    assert exc.value.code == "INVALID_ROUNDING_STEP"


# --- bulk percentage update -----------------------------------------------------------


@given(
    st.dictionaries(st.text(min_size=1, max_size=4), prices, max_size=20), percents, steps, modes
)
def test_bulk_update_scales_every_price_and_rounds(
    table: dict[str, Decimal], percent: Decimal, step: Decimal, mode: RoundMode
) -> None:
    rule = RoundingRule(step, mode)
    out = bulk_percentage_update(table, percent, rule)
    assert set(out) == set(table)
    for key, old in table.items():
        assert out[key] == round_price(old * (HUNDRED + percent) / HUNDRED, rule)
        assert out[key] >= 0
        if percent >= 0:
            assert out[key] >= round_price(old, rule)
        else:
            assert out[key] <= round_price(old, rule)


@given(st.dictionaries(st.integers(1, 50), prices, min_size=1, max_size=20), percents)
def test_bulk_update_can_target_a_subset(table: dict[int, Decimal], percent: Decimal) -> None:
    only = set(list(table)[: len(table) // 2])
    out = bulk_percentage_update(table, percent, RoundingRule(), only=only)
    for key, old in table.items():
        if key not in only:
            assert out[key] == old


def test_bulk_update_example() -> None:
    out = bulk_percentage_update(
        {"A": Decimal("1000.00"), "B": Decimal("2499.00")},
        Decimal(15),
        RoundingRule(Decimal(50), RoundMode.HALF_UP),
    )
    assert out == {"A": Decimal("1150.00"), "B": Decimal("2850.00")}


@pytest.mark.parametrize("bad", [Decimal(-100), Decimal(-150), Decimal(1001)])
def test_bulk_update_refuses_absurd_percentages(bad: Decimal) -> None:
    with pytest.raises(DomainError) as exc:
        bulk_percentage_update({"A": Decimal("1.00")}, bad)
    assert exc.value.code == "INVALID_PERCENT"


@given(st.integers(1, 3000))
def test_bulk_update_unknown_subset_key_is_refused(n: int) -> None:
    assume(n != 1)
    with pytest.raises(DomainError) as exc:
        bulk_percentage_update({1: Decimal("1.00")}, 10, only={n})
    assert exc.value.code == "PRICE_NOT_FOUND"
