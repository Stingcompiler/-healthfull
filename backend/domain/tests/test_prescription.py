"""Prescription rules: frequency codes and the quantity to dispense (FEATURES 3.5)."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.prescription import (
    FREQUENCIES,
    MAX_DURATION_DAYS,
    Prescription,
    dispense_quantity,
    frequency_per_day,
    order_quantity,
    resolve,
)

doses = st.decimals(min_value=Decimal("0.25"), max_value=Decimal(20), places=2)
per_day = st.sampled_from(sorted({f for f in FREQUENCIES.values() if f is not None}))
days = st.integers(min_value=1, max_value=MAX_DURATION_DAYS)


def _code(fn: object) -> str | None:
    assert callable(fn)
    try:
        fn()
    except DomainError as exc:
        return exc.code
    return None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("OD", Decimal(1)),
        ("bid", Decimal(2)),
        (" TID ", Decimal(3)),
        ("QID", Decimal(4)),
        ("Q6H", Decimal(4)),
        ("Q8H", Decimal(3)),
        ("Q12H", Decimal(2)),
        ("HS", Decimal(1)),
        ("QOD", Decimal("0.5")),
        ("PRN", None),
        ("STAT", None),
    ],
)
def test_frequency_codes(code: str, expected: Decimal | None) -> None:
    assert frequency_per_day(code) == expected


def test_unknown_frequency_is_refused() -> None:
    assert _code(lambda: frequency_per_day("SOMETIMES")) == "UNKNOWN_FREQUENCY"


@pytest.mark.parametrize(
    ("dose", "freq", "duration", "expected"),
    [
        (Decimal(1), Decimal(3), 7, 21),  # amoxicillin 1 cap TID x 7 days
        (Decimal(2), Decimal(1), 3, 6),
        (Decimal("0.5"), Decimal(2), 5, 5),
        (Decimal("0.5"), Decimal(3), 5, 8),  # 7.5 rounds up: never short
        (Decimal(1), Decimal("0.5"), 7, 4),  # every other day for a week
    ],
)
def test_dispense_quantity_examples(
    dose: Decimal, freq: Decimal, duration: int, expected: int
) -> None:
    assert dispense_quantity(dose, freq, duration) == expected


@given(doses, per_day, days)
def test_dispense_quantity_is_the_smallest_whole_cover(
    dose: Decimal, freq: Decimal, duration: int
) -> None:
    exact = dose * freq * duration
    qty = dispense_quantity(dose, freq, duration)
    assert isinstance(qty, int)
    assert qty >= 1
    assert qty >= exact  # never short of the course
    assert qty - 1 < exact  # never more than one unit over
    assert qty == math.ceil(exact)


@given(doses, per_day, days, st.integers(min_value=1, max_value=30))
def test_dispense_quantity_grows_with_the_course(
    dose: Decimal, freq: Decimal, duration: int, extra: int
) -> None:
    longer = min(MAX_DURATION_DAYS, duration + extra)
    assert dispense_quantity(dose, freq, longer) >= dispense_quantity(dose, freq, duration)
    assert dispense_quantity(dose + 1, freq, duration) >= dispense_quantity(dose, freq, duration)


@pytest.mark.parametrize(
    ("dose", "freq", "duration"),
    [
        (Decimal(0), Decimal(1), 1),
        (Decimal(-1), Decimal(1), 1),
        (Decimal(1), Decimal(0), 1),
        (Decimal(1), Decimal(1), 0),
        (Decimal(1), Decimal(1), MAX_DURATION_DAYS + 1),
        (Decimal(1), Decimal(25), 1),
        (Decimal("NaN"), Decimal(1), 1),
        (Decimal("Infinity"), Decimal(1), 1),
    ],
)
def test_dispense_quantity_refuses_impossible_courses(
    dose: Decimal, freq: Decimal, duration: int
) -> None:
    assert _code(lambda: dispense_quantity(dose, freq, duration)) == "INVALID_PRESCRIPTION"


def test_resolve_fills_the_frequency_and_quantity() -> None:
    assert resolve(
        dose_quantity=Decimal(1), frequency_code="tid", frequency_per_day=None, duration_days=7
    ) == Prescription(frequency_code="TID", frequency_per_day=Decimal(3), quantity=21)


def test_resolve_accepts_a_matching_or_a_free_frequency() -> None:
    same = resolve(
        dose_quantity=Decimal(1),
        frequency_code="BID",
        frequency_per_day=Decimal(2),
        duration_days=5,
    )
    assert same.quantity == 10
    free = resolve(
        dose_quantity=Decimal(1), frequency_code="", frequency_per_day=Decimal(5), duration_days=2
    )
    assert free == Prescription(frequency_code="", frequency_per_day=Decimal(5), quantity=10)


def test_resolve_refuses_a_contradicting_frequency() -> None:
    assert (
        _code(
            lambda: resolve(
                dose_quantity=Decimal(1),
                frequency_code="TID",
                frequency_per_day=Decimal(2),
                duration_days=5,
            )
        )
        == "FREQUENCY_MISMATCH"
    )


def test_stat_is_one_dose_and_prn_has_no_count() -> None:
    stat = resolve(
        dose_quantity=Decimal(2), frequency_code="STAT", frequency_per_day=None, duration_days=None
    )
    assert stat == Prescription(frequency_code="STAT", frequency_per_day=None, quantity=2)
    prn = resolve(
        dose_quantity=Decimal(1), frequency_code="PRN", frequency_per_day=None, duration_days=5
    )
    assert prn == Prescription(frequency_code="PRN", frequency_per_day=None, quantity=None)
    as_needed = resolve(
        dose_quantity=Decimal(1),
        frequency_code="TID",
        frequency_per_day=None,
        duration_days=5,
        as_needed=True,
    )
    assert as_needed.quantity is None
    assert as_needed.frequency_per_day == Decimal(3)


def test_resolve_without_enough_to_count() -> None:
    missing_days = resolve(
        dose_quantity=Decimal(1), frequency_code="OD", frequency_per_day=None, duration_days=None
    )
    assert missing_days.quantity is None
    missing_dose = resolve(
        dose_quantity=None, frequency_code="OD", frequency_per_day=None, duration_days=3
    )
    assert missing_dose.quantity is None


@given(
    computed=st.none() | st.integers(min_value=1, max_value=10_000),
    stated=st.none() | st.integers(min_value=1, max_value=10_000),
)
def test_order_quantity_never_falls_short_of_the_course(
    computed: int | None, stated: int | None
) -> None:
    """A stated quantity may round the course up, never down (FEATURES 3.5)."""
    if computed is not None and stated is not None and stated < computed:
        assert _code(lambda: order_quantity(computed, stated)) == "QUANTITY_BELOW_PRESCRIPTION"
        return
    result = order_quantity(computed, stated)
    assert result == (computed if stated is None else stated)
    if result is not None and computed is not None:
        assert result >= computed


def test_order_quantity_reports_both_numbers() -> None:
    with pytest.raises(DomainError) as exc:
        order_quantity(80, 1)
    assert exc.value.code == "QUANTITY_BELOW_PRESCRIPTION"
    assert (exc.value.details["quantity"], exc.value.details["computed"]) == (1, 80)
