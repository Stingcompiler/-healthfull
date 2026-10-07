from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.money import (
    CENT,
    HUNDRED,
    MAX_AMOUNT,
    ZERO,
    allocate,
    is_money,
    money,
    percent_of,
    q,
    split_even,
    split_percent,
    sum_money,
)

amounts = st.decimals(
    min_value=-MAX_AMOUNT, max_value=MAX_AMOUNT, places=2, allow_nan=False, allow_infinity=False
)
non_negative_amounts = st.decimals(
    min_value=0, max_value=MAX_AMOUNT, places=2, allow_nan=False, allow_infinity=False
)
any_decimals = st.decimals(
    min_value=Decimal("-1e15"), max_value=Decimal("1e15"), allow_nan=False, allow_infinity=False
)
percents = st.decimals(min_value=0, max_value=100, places=4, allow_nan=False, allow_infinity=False)
weights = st.lists(
    st.decimals(min_value=0, max_value=Decimal("1e9"), places=3, allow_nan=False),
    min_size=1,
    max_size=30,
)


# --- q() ---------------------------------------------------------------------------


@given(any_decimals)
def test_q_has_two_places_and_is_idempotent(x: Decimal) -> None:
    r = q(x)
    assert r.as_tuple().exponent == -2
    assert q(r) == r


@given(any_decimals)
def test_q_error_is_at_most_half_a_cent(x: Decimal) -> None:
    assert abs(q(x) - x) <= Decimal("0.005")


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_q_rounds_half_away_from_zero(cents: int) -> None:
    # x.xx5 always rounds away from zero (ROUND_HALF_UP), never to even.
    x = Decimal(cents) / 100 + (Decimal("0.005") if cents >= 0 else Decimal("-0.005"))
    expected = Decimal(cents + (1 if cents >= 0 else -1)) / 100
    assert q(x) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.005", "0.01"),
        ("0.015", "0.02"),
        ("0.025", "0.03"),  # ROUND_HALF_EVEN would give 0.02
        ("2.675", "2.68"),
        ("-0.005", "-0.01"),
        ("-2.675", "-2.68"),
        ("0.0049", "0.00"),
        ("-0.001", "0.00"),
    ],
)
def test_q_known_values(raw: str, expected: str) -> None:
    assert str(q(Decimal(raw))) == expected


def test_q_normalises_negative_zero() -> None:
    assert str(q(Decimal("-0.00"))) == "0.00"


def test_q_rejects_non_decimal() -> None:
    with pytest.raises(TypeError):
        q(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        q(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_q_rejects_non_finite(bad: str) -> None:
    with pytest.raises(DomainError) as exc:
        q(Decimal(bad))
    assert exc.value.code == "INVALID_AMOUNT"


def test_q_handles_very_large_values() -> None:
    big = Decimal("123456789012345678901234567890.125")
    assert q(big) == Decimal("123456789012345678901234567890.13")


# --- money() ------------------------------------------------------------------------


@given(any_decimals)
def test_money_from_decimal_equals_q(x: Decimal) -> None:
    assert money(x) == q(x)


@given(any_decimals)
def test_money_from_string_round_trips(x: Decimal) -> None:
    # Plain positional notation only: exponent strings are rejected (see below).
    assert money(format(x, "f")) == q(x)


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_money_from_int_is_exact(n: int) -> None:
    m = money(n)
    assert m == Decimal(n)
    assert m.as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [1.5, 0.1, True, False, None, [1], b"1"])
def test_money_rejects_floats_bools_and_other_types(bad: object) -> None:
    with pytest.raises(TypeError):
        money(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "1,5",
        "1,000.00",
        "12..5",
        "NaN",
        "inf",
        "--1",
        # PEP 515 underscores and exponents are valid for Decimal() but never for money.
        "1_5",
        "1_000.00",
        "1e3",
        "1E+3",
        "2.5e-1",
        " 1 000",
        "1 000",
        ".5",
        "5.",
        "+-1",
        "0x10",
        # Arabic thousands separator and Arabic-Indic digit mixed with a comma.
        "١٬٠٠٠",
        "١,٥",
    ],
)
def test_money_rejects_malformed_strings(bad: str) -> None:
    with pytest.raises(DomainError) as exc:
        money(bad)
    assert exc.value.code == "INVALID_AMOUNT"


def test_money_strips_whitespace() -> None:
    assert money("  10000.5 ") == Decimal("10000.50")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("١٢٣", "123.00"),  # Arabic-Indic digits (U+0660..U+0669)
        ("١٢٫٥", "12.50"),  # Arabic decimal separator (U+066B)
        ("۱۲.۵", "12.50"),  # Extended Arabic-Indic digits (U+06F0..U+06F9)
        ("-١٠", "-10.00"),
        ("+7", "7.00"),
    ],
)
def test_money_normalises_arabic_digits(text: str, expected: str) -> None:
    assert money(text) == Decimal(expected)


# --- is_money / sum_money -------------------------------------------------------------


@given(amounts)
def test_is_money_accepts_two_place_values(x: Decimal) -> None:
    assert is_money(x)


@pytest.mark.parametrize(
    "value", [Decimal("1.001"), Decimal("NaN"), Decimal("Infinity"), 1.0, 1, "1.00", None]
)
def test_is_money_rejects_other_values(value: object) -> None:
    assert not is_money(value)


@given(st.lists(amounts, max_size=50))
def test_sum_money_is_exact(values: list[Decimal]) -> None:
    assert sum_money(values) == sum(values, ZERO)


def test_sum_money_of_nothing_is_zero() -> None:
    assert sum_money([]) == ZERO
    assert str(sum_money([])) == "0.00"


def test_sum_money_rejects_unrounded_values() -> None:
    with pytest.raises(DomainError):
        sum_money([Decimal("1.005")])
    with pytest.raises(TypeError):
        sum_money([1.5])  # type: ignore[list-item]


# --- percent_of / split_percent -------------------------------------------------------


@given(amounts, percents)
def test_split_percent_parts_sum_to_whole(total: Decimal, pct: Decimal) -> None:
    part, rest = split_percent(total, pct)
    assert part + rest == total
    assert is_money(part)
    assert is_money(rest)


@given(non_negative_amounts, percents)
def test_split_percent_parts_are_within_bounds(total: Decimal, pct: Decimal) -> None:
    part, rest = split_percent(total, pct)
    assert ZERO <= part <= total
    assert ZERO <= rest <= total


@given(non_negative_amounts, percents)
def test_percent_of_is_correctly_rounded(total: Decimal, pct: Decimal) -> None:
    exact = total * pct / HUNDRED
    assert abs(percent_of(total, pct) - exact) <= Decimal("0.005")


@given(non_negative_amounts, percents, percents)
def test_percent_of_is_monotonic_in_percent(total: Decimal, a: Decimal, b: Decimal) -> None:
    lo, hi = sorted((a, b))
    assert percent_of(total, lo) <= percent_of(total, hi)


@given(non_negative_amounts)
def test_split_percent_extremes(total: Decimal) -> None:
    assert split_percent(total, 0) == (ZERO, total)
    assert split_percent(total, 100) == (total, ZERO)


def test_split_percent_known_value() -> None:
    # 15% of 333.33 = 49.9995 -> 50.00; patient keeps the remainder.
    assert split_percent(Decimal("333.33"), Decimal("15")) == (Decimal("50.00"), Decimal("283.33"))


@pytest.mark.parametrize("pct", [Decimal("-0.01"), Decimal("100.01"), Decimal("NaN"), 101, -1])
def test_split_percent_rejects_out_of_range(pct: Decimal) -> None:
    with pytest.raises(DomainError) as exc:
        split_percent(Decimal("10.00"), pct)
    assert exc.value.code == "INVALID_PERCENT"


def test_split_percent_rejects_bad_types() -> None:
    with pytest.raises(TypeError):
        split_percent(Decimal("10.00"), 50.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        split_percent(Decimal("10.00"), True)
    with pytest.raises(TypeError):
        split_percent(10, 50)  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        split_percent(Decimal("10.001"), 50)


# --- allocate / split_even ------------------------------------------------------------


@given(amounts, weights)
def test_allocate_sums_exactly_to_total(total: Decimal, ws: list[Decimal]) -> None:
    assume(sum(ws) > 0)
    parts = allocate(total, ws)
    assert len(parts) == len(ws)
    assert sum(parts, ZERO) == total
    assert all(is_money(p) for p in parts)


@given(amounts, weights)
def test_allocate_parts_are_within_a_cent_of_exact_share(total: Decimal, ws: list[Decimal]) -> None:
    weight_sum = sum(ws)
    assume(weight_sum > 0)
    for part, w in zip(allocate(total, ws), ws, strict=True):
        exact = total * w / weight_sum
        assert abs(part - exact) < CENT


@given(non_negative_amounts, weights)
def test_allocate_non_negative_total_gives_non_negative_parts(
    total: Decimal, ws: list[Decimal]
) -> None:
    assume(sum(ws) > 0)
    parts = allocate(total, ws)
    assert all(p >= 0 for p in parts)
    for part, w in zip(parts, ws, strict=True):
        if w == 0:
            assert part == ZERO


@given(amounts, weights)
def test_allocate_negative_total_mirrors_positive(total: Decimal, ws: list[Decimal]) -> None:
    assume(sum(ws) > 0)
    assert allocate(-total, ws) == [q(-p) for p in allocate(total, ws)]


@given(amounts, weights, st.randoms(use_true_random=False))
def test_allocate_is_permutation_equivariant_within_a_cent(
    total: Decimal, ws: list[Decimal], rnd: Any
) -> None:
    """Reordering the weights reorders the parts; only tie-break cents may move."""
    assume(sum(ws) > 0)
    order = list(range(len(ws)))
    rnd.shuffle(order)
    base = allocate(total, ws)
    shuffled = allocate(total, [ws[i] for i in order])
    assert sum(shuffled, ZERO) == total
    for position, original_index in enumerate(order):
        assert abs(shuffled[position] - base[original_index]) <= CENT


def test_allocate_tie_break_is_by_position() -> None:
    # Three equal shares of 1.00: the leftover cent goes to the first position.
    assert allocate(Decimal("1.00"), [1, 1, 1]) == [
        Decimal("0.34"),
        Decimal("0.33"),
        Decimal("0.33"),
    ]


@given(amounts, st.integers(min_value=1, max_value=50))
@example(Decimal("100.00"), 3)
def test_split_even_parts_differ_by_at_most_a_cent(total: Decimal, n: int) -> None:
    parts = split_even(total, n)
    assert len(parts) == n
    assert sum(parts, ZERO) == total
    assert max(parts) - min(parts) <= CENT


def test_split_even_known_value() -> None:
    assert split_even(Decimal("100.00"), 3) == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]


def test_allocate_zero_total_over_zero_weights_is_all_zero() -> None:
    assert allocate(ZERO, [0, 0]) == [ZERO, ZERO]


@pytest.mark.parametrize(
    "ws", [[], [Decimal("-1"), Decimal("2")], [0, 0], [Decimal("NaN")], [Decimal("Infinity")]]
)
def test_allocate_rejects_bad_weights(ws: list[Decimal]) -> None:
    with pytest.raises(DomainError) as exc:
        allocate(Decimal("10.00"), ws)
    assert exc.value.code == "INVALID_WEIGHTS"


def test_allocate_rejects_bad_types() -> None:
    with pytest.raises(TypeError):
        allocate(Decimal("10.00"), [1.0])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        allocate(Decimal("10.00"), [True])
    with pytest.raises(DomainError):
        allocate(Decimal("10.001"), [1])


@pytest.mark.parametrize("n", [0, -1, True])
def test_split_even_rejects_bad_part_count(n: int) -> None:
    with pytest.raises(DomainError):
        split_even(Decimal("10.00"), n)
