from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.claims import (
    ClaimLine,
    ClaimLineStatus,
    Resolution,
    accrue,
    is_settled,
    record_payment,
    reduce_for_credit,
    require_creditable,
    resolve_rejection,
    respond,
    submit,
    validate_payer_payment,
)
from domain.errors import DomainError
from domain.money import ZERO

S = ClaimLineStatus
OK = Approval(approver_id=4, at=datetime(2026, 10, 7, tzinfo=UTC), reason="contract excludes")
amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2)


def _code(fn: object) -> str | None:
    try:
        fn()  # type: ignore[operator]
    except DomainError as exc:
        return exc.code
    return None


def test_happy_paths() -> None:
    line = submit(accrue(Decimal("7000.00")))
    assert line.status is S.CLAIMED
    accepted = respond(line, Decimal("7000.00"))
    assert accepted.status is S.ACCEPTED
    paid = record_payment(accepted, Decimal("7000.00"))
    assert paid.status is S.PAID
    assert paid.receivable == 0
    assert is_settled(paid)

    rejected = respond(line, ZERO, reason="not covered")
    assert rejected.status is S.REJECTED
    assert rejected.rejected == Decimal("7000.00")
    rebilled = resolve_rejection(rejected, Resolution.REBILLED, OK)
    assert rebilled.status is S.REBILLED
    assert rebilled.receivable == 0
    assert is_settled(rebilled)
    assert resolve_rejection(rejected, Resolution.WRITTEN_OFF, OK).status is S.WRITTEN_OFF


def test_partial_acceptance_needs_payment_and_resolution() -> None:
    line = respond(submit(accrue(Decimal("1000.00"))), Decimal("600.00"), reason="ceiling")
    assert line.status is S.PARTIALLY_ACCEPTED
    assert (line.accepted, line.rejected) == (Decimal("600.00"), Decimal("400.00"))
    paid = record_payment(line, Decimal("600.00"))
    assert paid.status is S.PAID
    assert paid.receivable == Decimal("400.00")
    assert not is_settled(paid)
    done = resolve_rejection(paid, Resolution.WRITTEN_OFF, OK)
    assert done.status is S.PAID
    assert done.resolution is Resolution.WRITTEN_OFF
    assert is_settled(done)


def test_refusals() -> None:
    accrued = accrue(Decimal("100.00"))
    claimed = submit(accrued)
    assert _code(lambda: submit(claimed)) == "CLAIM_LINE_NOT_ACCRUED"
    assert _code(lambda: respond(accrued, ZERO, reason="x")) == "CLAIM_LINE_NOT_CLAIMED"
    assert _code(lambda: respond(claimed, Decimal("100.01"))) == "CLAIM_AMOUNT_INVALID"
    assert _code(lambda: respond(claimed, ZERO)) == "REASON_REQUIRED"
    assert _code(lambda: record_payment(claimed, Decimal("1.00"))) == "CLAIM_LINE_NOT_ACCEPTED"
    accepted = respond(claimed, Decimal("100.00"))
    assert (
        _code(lambda: record_payment(accepted, Decimal("100.01")))
        == "CLAIM_PAYMENT_EXCEEDS_ACCEPTED"
    )
    assert _code(lambda: resolve_rejection(accepted, Resolution.REBILLED, OK)) == (
        "CLAIM_NOTHING_REJECTED"
    )
    rejected = respond(claimed, ZERO, reason="x")
    resolved = resolve_rejection(rejected, Resolution.REBILLED, OK)
    assert _code(lambda: resolve_rejection(resolved, Resolution.REBILLED, OK)) == (
        "CLAIM_NOTHING_REJECTED"
    )
    assert _code(lambda: reduce_for_credit(claimed, Decimal("1.00"))) == "CLAIM_LINE_LOCKED"
    assert _code(lambda: accrue(ZERO)) == "INVALID_AMOUNT"


def test_credit_before_claim_reduces_or_voids() -> None:
    line = accrue(Decimal("100.00"))
    less = reduce_for_credit(line, Decimal("40.00"))
    assert (less.status, less.amount) == (S.ACCRUED, Decimal("60.00"))
    gone = reduce_for_credit(less, Decimal("60.00"))
    assert (gone.status, gone.amount, gone.receivable) == (S.VOIDED, ZERO, ZERO)
    assert _code(lambda: reduce_for_credit(less, Decimal("60.01"))) == "CLAIM_AMOUNT_INVALID"
    assert _code(lambda: submit(gone)) == "CLAIM_LINE_NOT_ACCRUED"


def test_inconsistent_snapshots_are_refused() -> None:
    with pytest.raises(DomainError) as exc:
        ClaimLine(S.ACCEPTED, Decimal("10.00"), accepted=Decimal("5.00"))
    assert exc.value.code == "CLAIM_AMOUNT_INVALID"
    with pytest.raises(DomainError):
        ClaimLine(S.PAID, Decimal("10.00"), accepted=Decimal("10.00"), paid=Decimal("9.00"))
    with pytest.raises(DomainError):
        ClaimLine(S.REBILLED, Decimal("10.00"), resolution=Resolution.WRITTEN_OFF)


OPS = [
    "submit",
    "accept_all",
    "accept_part",
    "reject",
    "pay_part",
    "pay_rest",
    "rebill",
    "write_off",
    "credit",
]


@given(amounts, st.lists(st.sampled_from(OPS), max_size=12), st.data())
def test_random_walks_conserve_the_payer_share(
    amount: Decimal, ops: list[str], data: st.DataObject
) -> None:
    line = accrue(amount)
    original = amount
    credited = ZERO
    for op in ops:
        try:
            if op == "submit":
                line = submit(line)
            elif op == "accept_all":
                line = respond(line, line.amount)
            elif op == "accept_part":
                part = data.draw(st.decimals(min_value=0, max_value=line.amount, places=2))
                line = respond(line, part, reason="partial")
            elif op == "reject":
                line = respond(line, ZERO, reason="rejected")
            elif op in ("pay_part", "pay_rest"):
                left = line.accepted - line.paid
                pay = (
                    left
                    if op == "pay_rest"
                    else data.draw(
                        st.decimals(
                            min_value=Decimal("0.01"),
                            max_value=max(left, Decimal("0.01")),
                            places=2,
                        )
                    )
                )
                line = record_payment(line, pay)
            elif op == "rebill":
                line = resolve_rejection(line, Resolution.REBILLED, OK)
            elif op == "write_off":
                line = resolve_rejection(line, Resolution.WRITTEN_OFF, OK)
            else:
                c = data.draw(st.decimals(min_value=Decimal("0.01"), max_value=original, places=2))
                line = reduce_for_credit(line, c)
                credited += c
        except DomainError:
            continue
        # Conservation: accrued share = credited + receivable + paid + resolved rejection.
        resolved = line.rejected if line.resolution is not None else ZERO
        assert original == credited + line.receivable + line.paid + resolved
        assert line.receivable >= 0
        assert line.paid <= line.accepted <= line.amount


def test_payer_payment_allocation() -> None:
    lines = {
        1: record_payment(
            respond(submit(accrue(Decimal("100.00"))), Decimal("100.00")), Decimal("30.00")
        ),
        2: respond(submit(accrue(Decimal("50.00"))), Decimal("20.00"), reason="x"),
    }
    validate_payer_payment(Decimal("90.00"), {1: Decimal("70.00"), 2: Decimal("20.00")}, lines)
    cases = [
        (Decimal("80.00"), {1: Decimal("70.00"), 2: Decimal("20.00")}, "PAYER_PAYMENT_UNBALANCED"),
        (Decimal("71.00"), {1: Decimal("71.00")}, "CLAIM_PAYMENT_EXCEEDS_ACCEPTED"),
        (Decimal("1.00"), {3: Decimal("1.00")}, "CLAIM_LINE_UNKNOWN"),
        (Decimal("1.00"), {1: Decimal("0.00"), 2: Decimal("1.00")}, "INVALID_AMOUNT"),
    ]
    for amount, alloc, code in cases:
        with pytest.raises(DomainError) as exc:
            validate_payer_payment(amount, alloc, lines)
        assert exc.value.code == code


def test_credit_notes_need_an_unclaimed_payer_share() -> None:
    require_creditable(None)
    require_creditable(accrue(Decimal("10.00")))
    for line in (
        submit(accrue(Decimal("10.00"))),
        respond(submit(accrue(Decimal("10.00"))), Decimal("10.00")),
    ):
        with pytest.raises(DomainError) as exc:
            require_creditable(line)
        assert exc.value.code == "CLAIM_LINE_LOCKED"
