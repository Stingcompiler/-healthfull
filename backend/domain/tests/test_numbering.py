from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.numbering import DocumentNumber, format_document_number, parse_document_number

prefixes = st.from_regex(r"[A-Z][A-Z0-9]{0,9}", fullmatch=True)
years = st.integers(min_value=1000, max_value=9999)
seqs = st.integers(min_value=1, max_value=10**10)


def test_known_format() -> None:
    assert format_document_number("INV", 2026, 123) == "INV-2026-000123"
    assert format_document_number("RCT", 2026, 1, width=4) == "RCT-2026-0001"


def test_numbers_wider_than_width_are_not_truncated() -> None:
    assert format_document_number("INV", 2026, 1_234_567) == "INV-2026-1234567"


@given(prefixes, years, seqs)
def test_format_parse_round_trip(prefix: str, year: int, seq: int) -> None:
    text = format_document_number(prefix, year, seq)
    assert parse_document_number(text) == DocumentNumber(prefix, year, seq)


@given(prefixes, years, seqs, seqs)
def test_order_within_a_year_is_preserved_for_equal_width(
    prefix: str, year: int, a: int, b: int
) -> None:
    lo, hi = sorted((a % 999_999 + 1, b % 999_999 + 1))
    assert format_document_number(prefix, year, lo) <= format_document_number(prefix, year, hi)


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (("inv", 2026, 1), "INVALID_SEQUENCE_PREFIX"),
        (("", 2026, 1), "INVALID_SEQUENCE_PREFIX"),
        (("TOOLONGPREFIX", 2026, 1), "INVALID_SEQUENCE_PREFIX"),
        (("INV", 999, 1), "INVALID_SEQUENCE_YEAR"),
        (("INV", 2026, 0), "INVALID_SEQUENCE_NUMBER"),
    ],
)
def test_format_rejects_invalid_parts(args: tuple[str, int, int], code: str) -> None:
    with pytest.raises(DomainError) as exc:
        format_document_number(*args)
    assert exc.value.code == code


def test_format_rejects_bad_width() -> None:
    with pytest.raises(DomainError) as exc:
        format_document_number("INV", 2026, 1, width=0)
    assert exc.value.code == "INVALID_SEQUENCE_WIDTH"


@pytest.mark.parametrize("bad", ["", "INV2026000123", "INV-26-1", "inv-2026-1", "INV-2026-0"])
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(DomainError):
        parse_document_number(bad)
