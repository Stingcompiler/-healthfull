from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.payments import PaymentMethod, Verification
from domain.shift import (
    CashMovements,
    ShiftPayment,
    ShiftRef,
    ShiftStatus,
    collection_summary,
    ensure_cash_available,
    expected_cash,
    late_effect_shift,
    require_open,
    validate_close,
    validate_open,
    variance,
)

amounts = st.decimals(min_value=0, max_value=Decimal("10000000"), places=2)


@given(amounts, amounts, amounts, amounts, amounts)
def test_expected_cash_formula(
    opening: Decimal, cash_in: Decimal, refunds: Decimal, out: Decimal, into: Decimal
) -> None:
    m = CashMovements(
        opening_float=opening,
        cash_in=cash_in,
        cash_refunds=refunds,
        handovers_out=out,
        handovers_in=into,
    )
    assert expected_cash(m) == opening + cash_in - refunds - out + into


def test_movements_must_be_non_negative() -> None:
    with pytest.raises(DomainError) as exc:
        CashMovements(opening_float=Decimal("-1.00"), cash_in=Decimal(0), cash_refunds=Decimal(0))
    assert exc.value.code == "INVALID_AMOUNT"


@given(amounts, amounts)
def test_variance_and_close(counted: Decimal, expected: Decimal) -> None:
    v = variance(counted, expected)
    assert v == counted - expected
    if v == 0:
        result = validate_close(
            ShiftStatus.OPEN, expected=expected, counted=counted, explanation=""
        )
        assert result.variance == 0
    else:
        with pytest.raises(DomainError) as exc:
            validate_close(ShiftStatus.OPEN, expected=expected, counted=counted, explanation="  ")
        assert exc.value.code == "VARIANCE_EXPLANATION_REQUIRED"
        result = validate_close(
            ShiftStatus.OPEN, expected=expected, counted=counted, explanation=" note fell "
        )
        assert result.variance == v
        assert result.explanation == "note fell"


def test_closed_shift_is_locked() -> None:
    with pytest.raises(DomainError) as exc:
        validate_close(ShiftStatus.CLOSED, expected=Decimal(0), counted=Decimal(0), explanation="")
    assert exc.value.code == "SHIFT_CLOSED"
    with pytest.raises(DomainError) as exc:
        require_open(ShiftStatus.CLOSED)
    assert exc.value.code == "SHIFT_CLOSED"
    with pytest.raises(DomainError) as exc:
        require_open(None)
    assert exc.value.code == "SHIFT_NOT_OPEN"
    require_open(ShiftStatus.OPEN)


def test_counted_cash_cannot_be_negative() -> None:
    with pytest.raises(DomainError) as exc:
        validate_close(
            ShiftStatus.OPEN, expected=Decimal(0), counted=Decimal("-0.01"), explanation="x"
        )
    assert exc.value.code == "INVALID_AMOUNT"


def test_one_open_shift_per_cashier() -> None:
    assert validate_open(0, Decimal("500.00")) == Decimal("500.00")
    with pytest.raises(DomainError) as exc:
        validate_open(1, Decimal("500.00"))
    assert exc.value.code == "SHIFT_ALREADY_OPEN"


def test_cash_out_never_exceeds_the_drawer() -> None:
    ensure_cash_available(Decimal("10.00"), Decimal("10.00"))
    with pytest.raises(DomainError) as exc:
        ensure_cash_available(Decimal("10.01"), Decimal("10.00"))
    assert exc.value.code == "CASH_INSUFFICIENT"


# --- invariant 3: late effects ----------------------------------------------------------------


@given(st.integers(1, 9), st.sampled_from(list(ShiftStatus)), st.none() | st.integers(10, 19))
def test_late_effects_never_touch_a_closed_shift(
    original_id: int, status: ShiftStatus, current_id: int | None
) -> None:
    original = ShiftRef(original_id, status)
    current = ShiftRef(current_id, ShiftStatus.OPEN) if current_id is not None else None
    if status is ShiftStatus.OPEN:
        assert late_effect_shift(original, current) == original_id
    elif current is None:
        with pytest.raises(DomainError) as exc:
            late_effect_shift(original, current)
        assert exc.value.code == "SHIFT_NOT_OPEN"
    else:
        assert late_effect_shift(original, current) == current_id


def test_current_shift_must_be_open() -> None:
    with pytest.raises(DomainError) as exc:
        late_effect_shift(ShiftRef(1, ShiftStatus.CLOSED), ShiftRef(2, ShiftStatus.CLOSED))
    assert exc.value.code == "SHIFT_NOT_OPEN"


# --- shift report ----------------------------------------------------------------------------


def test_collection_summary_separates_confirmed_and_pending() -> None:
    s = collection_summary(
        [
            ShiftPayment(PaymentMethod.CASH, Verification.CONFIRMED, Decimal("100.00")),
            ShiftPayment(PaymentMethod.BANK_TRANSFER, Verification.CONFIRMED, Decimal("50.00")),
            ShiftPayment(PaymentMethod.QR, Verification.PENDING, Decimal("30.00")),
            ShiftPayment(PaymentMethod.CARD, Verification.REJECTED, Decimal("20.00")),
            ShiftPayment(PaymentMethod.PATIENT_CREDIT, Verification.CONFIRMED, Decimal("9.00")),
        ]
    )
    assert s.cash_confirmed == Decimal("100.00")
    assert s.bank_confirmed == Decimal("50.00")
    assert s.bank_pending == Decimal("30.00")
    assert s.bank_rejected == Decimal("20.00")
    assert s.credit_used == Decimal("9.00")
    assert s.confirmed_collection == Decimal("150.00")
