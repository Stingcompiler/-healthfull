"""Patient import rows (FEATURES 1.8): headers, row parsing and repeats inside one file."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.patient_import import (
    COLUMNS,
    match_headers,
    missing_headers,
    parse_row,
    repeated_rows,
)

TODAY = date(2026, 10, 8)


def test_headers_match_in_english_arabic_and_keys() -> None:
    matched = match_headers(
        ["Name (Arabic)", "full_name_en", "الجنس", " DATE OF BIRTH ", "Mobile", "Unknown", None]
    )
    assert matched == {
        0: "full_name_ar",
        1: "full_name_en",
        2: "sex",
        3: "date_of_birth",
        4: "phone",
    }
    assert missing_headers(matched) == []
    assert missing_headers(match_headers(["Phone"])) == ["full_name_ar|full_name_en", "sex"]
    # A repeated header keeps its first column.
    assert match_headers(["sex", "Gender"]) == {0: "sex"}


def test_every_template_header_matches_its_own_column() -> None:
    for labels in (
        [c.label_en for c in COLUMNS],
        [c.label_ar for c in COLUMNS],
        [c.key for c in COLUMNS],
    ):
        assert list(match_headers(labels).values()) == [c.key for c in COLUMNS]


def test_a_full_row_reads_into_registration_data() -> None:
    row = parse_row(
        {
            "full_name_ar": "  أحمد   علي ",
            "sex": "ذكر",
            "date_of_birth": "02/01/1990",
            "phone": 912345678.0,
            "national_id": "123",
        },
        today=TODAY,
    )
    assert row is not None
    assert row.errors == []
    assert row.data["full_name_ar"] == "أحمد علي"
    assert row.data["sex"] == "male"
    assert row.data["date_of_birth"] == date(1990, 1, 2)
    assert row.data["age_years"] is None
    assert row.data["phone"] == "912345678"
    assert row.data["full_name_en"] == ""


@pytest.mark.parametrize(
    ("cells", "codes"),
    [
        ({"sex": "female"}, ["NAME_REQUIRED"]),
        ({"full_name_en": "Sara", "sex": "unknown"}, ["INVALID_SEX"]),
        ({"full_name_en": "Sara", "sex": ""}, ["INVALID_SEX"]),
        (
            {"full_name_en": "Sara", "sex": "F", "date_of_birth": "2027-01-01"},
            ["INVALID_DATE_OF_BIRTH"],
        ),
        ({"full_name_en": "Sara", "sex": "F", "date_of_birth": "soon"}, ["INVALID_DATE_OF_BIRTH"]),
        ({"full_name_en": "Sara", "sex": "F", "age_years": "131"}, ["INVALID_AGE"]),
        ({"full_name_en": "Sara", "sex": "F", "age_years": "2.5"}, ["INVALID_AGE"]),
        ({"full_name_en": "Sara", "sex": "F", "age_years": True}, ["INVALID_AGE"]),
        ({"full_name_en": "S" * 201, "sex": "F"}, ["VALUE_TOO_LONG"]),
    ],
)
def test_row_errors(cells: dict[str, object], codes: list[str]) -> None:
    row = parse_row(cells, today=TODAY)
    assert row is not None
    assert row.errors == codes
    assert len(row.error_fields) == len(codes)


def test_dates_ages_and_sex_spellings() -> None:
    def read(**cells: object) -> dict[str, object]:
        row = parse_row({"full_name_en": "X", "sex": "m", **cells}, today=TODAY)
        assert row is not None
        assert row.errors == []
        return row.data

    assert read(date_of_birth=datetime(1990, 5, 6, 0, 0))["date_of_birth"] == date(1990, 5, 6)
    assert read(date_of_birth=date(1990, 5, 6))["date_of_birth"] == date(1990, 5, 6)
    assert read(date_of_birth="٠٦-٠٥-١٩٩٠")["date_of_birth"] == date(1990, 5, 6)
    assert read(date_of_birth="1990/05/06")["date_of_birth"] == date(1990, 5, 6)
    assert read(age_years="٤٠")["age_years"] == 40
    assert read(age_years=40.0)["age_years"] == 40
    # A date of birth wins over an age.
    assert read(date_of_birth="1990-05-06", age_years=3)["age_years"] is None
    for spelling, sex in (
        ("Male", "male"),
        ("F", "female"),
        ("أنثى", "female"),
        ("انثى", "female"),
    ):
        assert read(sex=spelling)["sex"] == sex


def test_blank_rows_are_skipped() -> None:
    assert parse_row({"full_name_ar": " ", "sex": None, "phone": ""}, today=TODAY) is None


def test_repeated_rows_point_at_the_first_row() -> None:
    keys = [(2, {"p:0912"}), (3, {"p:0913"}), (4, {"p:0912", "n:9"}), (5, {"n:9"}), (6, set())]
    assert repeated_rows(keys) == {4: 2, 5: 4}


@given(st.lists(st.sets(st.sampled_from("abcdef"), max_size=3), max_size=20))
def test_repeated_rows_only_point_backwards_to_a_shared_key(sets: list[set[str]]) -> None:
    keys = list(enumerate(sets, start=2))
    found = repeated_rows(keys)
    by_row = dict(keys)
    for row_no, first in found.items():
        assert first < row_no
        assert by_row[first] & by_row[row_no]
    for row_no, row_keys in keys:
        shared = any(row_keys & by_row[r] for r in by_row if r < row_no)
        assert (row_no in found) == shared
