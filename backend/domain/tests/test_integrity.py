"""Property tests for ``domain.integrity`` (manage.py integrity_check)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from domain.integrity import MAX_LISTED, CheckResult, all_ok, compare_amounts

amounts = st.decimals(
    min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=2, allow_nan=False
)
books = st.dictionaries(st.integers(min_value=1, max_value=40), amounts, max_size=30)


@given(books)
def test_a_book_matches_itself(book: dict[int, Decimal]) -> None:
    assert compare_amounts(book, book) == []


@given(books)
def test_zero_entries_equal_missing_keys(book: dict[int, Decimal]) -> None:
    padded = {**book, **{k + 1000: Decimal("0.00") for k in book}}
    assert compare_amounts(book, padded) == []
    assert compare_amounts(padded, book) == []


@given(books, books)
def test_mismatches_are_exactly_the_keys_that_differ(
    expected: dict[int, Decimal], actual: dict[int, Decimal]
) -> None:
    found = compare_amounts(expected, actual)
    zero = Decimal(0)
    differ = {
        k for k in set(expected) | set(actual) if expected.get(k, zero) != actual.get(k, zero)
    }
    assert {m.key for m in found} == differ
    for m in found:
        assert m.expected == expected.get(m.key, zero)
        assert m.actual == actual.get(m.key, zero)
        assert m.difference == m.actual - m.expected != 0
    # Swapping the sides finds the same keys with opposite differences.
    swapped = {m.key: m.difference for m in compare_amounts(actual, expected)}
    assert swapped == {m.key: -m.difference for m in found}


@given(st.integers(min_value=0, max_value=60))
def test_a_check_counts_everything_and_lists_a_bounded_number(n: int) -> None:
    result = CheckResult("x")
    result.add_all(f"problem {i}" for i in range(n))
    assert result.count == n
    assert len(result.problems) == min(n, MAX_LISTED)
    assert result.ok is (n == 0)
    assert all_ok([result, CheckResult("y")]) is (n == 0)
