from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.errors import DomainError
from domain.payments import (
    REFERENCE_METHODS,
    PaymentMethod,
    Verification,
    check_reference,
    confirm,
    counts_as_collected,
    covers_lines,
    initial_verification,
    normalize_reference,
    pending_age_days,
    reject,
    validate_payment,
)

M = PaymentMethod
V = Verification
OK = Approval(approver_id=5, at=datetime(2026, 10, 7, tzinfo=UTC), reason="matched statement")


def test_initial_verification() -> None:
    assert initial_verification(M.CASH) is V.CONFIRMED
    assert initial_verification(M.PATIENT_CREDIT) is V.CONFIRMED
    for method in REFERENCE_METHODS:
        assert initial_verification(method) is V.PENDING
    assert {M.BANK_TRANSFER, M.QR, M.CARD} == REFERENCE_METHODS


@given(st.sampled_from(list(M)), st.lists(st.sampled_from(["confirm", "reject"]), max_size=6))
def test_verification_machine(method: PaymentMethod, events: list[str]) -> None:
    v = initial_verification(method)
    history = [v]
    refused: set[str] = set()
    for event in events:
        try:
            v = confirm(method, v, OK) if event == "confirm" else reject(method, v, OK)
        except DomainError as exc:
            refused.add(exc.code)
            continue
        history.append(v)
    assert refused <= {"PAYMENT_NOT_PENDING", "PAYMENT_NOT_REJECTABLE"}
    # Cash and credit are always confirmed; others only move pending -> confirmed -> rejected
    # or pending -> rejected, and rejected is terminal.
    if method not in REFERENCE_METHODS:
        assert history == [V.CONFIRMED]
    else:
        assert history in (
            [V.PENDING],
            [V.PENDING, V.CONFIRMED],
            [V.PENDING, V.REJECTED],
            [V.PENDING, V.CONFIRMED, V.REJECTED],
        )


def test_specific_refusals() -> None:
    with pytest.raises(DomainError) as exc:
        confirm(M.CASH, V.CONFIRMED, OK)
    assert exc.value.code == "PAYMENT_NOT_PENDING"
    with pytest.raises(DomainError) as exc:
        reject(M.CASH, V.CONFIRMED, OK)
    assert exc.value.code == "PAYMENT_NOT_REJECTABLE"
    with pytest.raises(DomainError) as exc:
        reject(M.BANK_TRANSFER, V.REJECTED, OK)
    assert exc.value.code == "PAYMENT_NOT_REJECTABLE"
    with pytest.raises(DomainError) as exc:
        confirm(M.QR, V.PENDING, Approval(approver_id=5, at=OK.at, reason="  "))
    assert exc.value.code == "REASON_REQUIRED"


def test_collection_and_coverage_flags() -> None:
    # Pending money settles lines but is never reported as collected (FEATURES 6.4).
    assert covers_lines(V.PENDING)
    assert covers_lines(V.CONFIRMED)
    assert not covers_lines(V.REJECTED)
    assert counts_as_collected(V.CONFIRMED)
    assert not counts_as_collected(V.PENDING)
    assert not counts_as_collected(V.REJECTED)


# --- details and references -----------------------------------------------------------


def test_validate_payment() -> None:
    cash = validate_payment(M.CASH, Decimal("100.00"))
    assert (cash.bank, cash.reference) == (None, None)
    t = validate_payment(M.BANK_TRANSFER, Decimal("5.00"), bank=" bok ", reference=" trx 12-٣٤ ")
    assert (t.bank, t.reference) == ("BOK", "TRX1234")
    with pytest.raises(DomainError) as exc:
        validate_payment(M.BANK_TRANSFER, Decimal("5.00"), bank=None, reference="1")
    assert exc.value.code == "BANK_REQUIRED"
    with pytest.raises(DomainError) as exc:
        validate_payment(M.QR, Decimal("5.00"), bank="BOK", reference=" - ")
    assert exc.value.code == "REFERENCE_REQUIRED"
    for bad in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(DomainError) as exc:
            validate_payment(M.CASH, bad)
        assert exc.value.code == "INVALID_AMOUNT"


refs = st.text(alphabet="abcXYZ0123456789٠١٢٣ -", min_size=1, max_size=12)


@given(refs)
def test_normalize_reference_is_idempotent_and_canonical(ref: str) -> None:
    n = normalize_reference(ref)
    assert normalize_reference(n) == n
    assert n == n.upper()
    assert " " not in n
    assert "-" not in n
    assert all(c.isascii() for c in n)


@given(refs, refs)
def test_duplicate_reference_rule(a: str, b: str) -> None:
    na, nb = normalize_reference(a), normalize_reference(b)
    if not na or not nb:
        return
    existing = {("BOK", na)}
    if na == nb:
        with pytest.raises(DomainError) as exc:
            check_reference("BOK", b, existing)
        assert exc.value.code == "DUPLICATE_REFERENCE"
        with pytest.raises(DomainError) as exc:
            check_reference("BOK", b, existing, override=OK, can_override=False)
        assert exc.value.code == "OVERRIDE_NOT_PERMITTED"
        checked = check_reference("BOK", b, existing, override=OK, can_override=True)
        assert checked.duplicate
        assert checked.override == OK
    else:
        checked = check_reference("BOK", b, existing)
        assert not checked.duplicate
        assert checked.override is None
    # The same reference at another bank is not a duplicate.
    assert not check_reference("FAISAL", a, existing).duplicate


def test_pending_age_days() -> None:
    assert pending_age_days(date(2026, 10, 1), date(2026, 10, 7)) == 6
    assert pending_age_days(date(2026, 10, 7), date(2026, 10, 7)) == 0
    with pytest.raises(DomainError):
        pending_age_days(date(2026, 10, 8), date(2026, 10, 7))
