"""A payer payment allocated per claim (FEATURES 11.6): ``domain.claims.allocate_to_claims``.

The accountant reads a payer's remittance advice per claim batch. Each claim's amount is
spread over that claim's own accepted, unpaid lines, oldest first, never beyond a line's due
and never onto another claim's lines; the parts add up exactly to what was entered.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.claims import allocate_to_claims, response_amount
from domain.errors import DomainError

D = Decimal
dues = st.decimals(min_value=D("0"), max_value=D("50000"), places=2)

Claims = dict[int, list[tuple[int, Decimal]]]


def _code(fn: object) -> str | None:
    try:
        fn()  # type: ignore[operator]
    except DomainError as exc:
        return exc.code
    return None


@st.composite
def claims_and_amounts(draw: st.DrawFn) -> tuple[Claims, dict[int, Decimal]]:
    """Up to four claims with up to five lines each, and an amount within each claim's due."""
    claims: Claims = {}
    line_id = 1
    for claim_id in range(1, draw(st.integers(1, 4)) + 1):
        rows = []
        for _ in range(draw(st.integers(1, 5))):
            rows.append((line_id, draw(dues)))
            line_id += 1
        claims[claim_id] = rows
    amounts: dict[int, Decimal] = {}
    for claim_id, rows in claims.items():
        total = sum((due for _, due in rows), D("0"))
        if total > 0 and draw(st.booleans()):
            cents = draw(st.integers(1, int(total * 100)))
            amounts[claim_id] = D(cents) / 100
    return claims, amounts


@given(claims_and_amounts())
def test_parts_add_up_per_claim_and_stay_within_each_line(
    data: tuple[Claims, dict[int, Decimal]],
) -> None:
    claims, amounts = data
    out = allocate_to_claims(amounts, claims)
    owner = {line: claim for claim, rows in claims.items() for line, _ in rows}
    due = {line: value for rows in claims.values() for line, value in rows}
    for claim_id, amount in amounts.items():
        mine = sum((v for line, v in out.items() if owner[line] == claim_id), D("0"))
        assert mine == amount
    for line, value in out.items():
        assert D("0") < value <= due[line]
        assert owner[line] in amounts
    assert sum(out.values(), D("0")) == sum(amounts.values(), D("0"))


@given(claims_and_amounts())
def test_oldest_lines_of_a_claim_are_paid_first(data: tuple[Claims, dict[int, Decimal]]) -> None:
    claims, amounts = data
    out = allocate_to_claims(amounts, claims)
    for claim_id in amounts:
        rows = [(line, due) for line, due in claims[claim_id] if due > 0]
        # A later line gets money only once every earlier line is paid in full.
        for index, (line, _) in enumerate(rows):
            if line in out:
                assert all(out.get(prev) == prev_due for prev, prev_due in rows[:index])


def test_example_spreads_over_the_claim_lines() -> None:
    claims = {7: [(70, D("6300.00")), (71, D("2000.00"))], 8: [(80, D("500.00"))]}
    assert allocate_to_claims({7: D("7000.00")}, claims) == {70: D("6300.00"), 71: D("700.00")}
    assert allocate_to_claims({7: D("8300.00"), 8: D("500.00")}, claims) == {
        70: D("6300.00"),
        71: D("2000.00"),
        80: D("500.00"),
    }


def test_more_than_a_claim_owes_is_refused() -> None:
    claims = {7: [(70, D("6300.00"))]}
    assert _code(lambda: allocate_to_claims({7: D("6300.01")}, claims)) == (
        "CLAIM_PAYMENT_EXCEEDS_ACCEPTED"
    )


def test_a_claim_with_nothing_payable_is_refused() -> None:
    claims = {7: [(70, D("0.00"))]}
    assert _code(lambda: allocate_to_claims({7: D("1.00")}, claims)) == "CLAIM_NOTHING_UNPAID"
    assert _code(lambda: allocate_to_claims({9: D("1.00")}, claims)) == "CLAIM_NOTHING_UNPAID"


@pytest.mark.parametrize("bad", [D("0"), D("-1.00")])
def test_amounts_are_positive(bad: Decimal) -> None:
    claims = {7: [(70, D("6300.00"))]}
    assert _code(lambda: allocate_to_claims({7: bad}, claims)) == "INVALID_AMOUNT"


def test_nothing_entered_allocates_nothing() -> None:
    assert allocate_to_claims({}, {7: [(70, D("1.00"))]}) == {}


# --- the payer's answer per line as the accountant enters it (FEATURES 11.4) ----------------


@given(st.decimals(min_value=D("0.01"), max_value=D("100000"), places=2))
def test_accepted_and_rejected_outcomes_take_the_whole_amount(claimed: Decimal) -> None:
    assert response_amount("accepted", claimed, None) == claimed
    assert response_amount("rejected", claimed, None) == D("0.00")
    # An amount typed for a whole answer is ignored, never half applied.
    assert response_amount("accepted", claimed, D("0.01")) == claimed


@given(
    st.decimals(min_value=D("0.02"), max_value=D("100000"), places=2),
    st.decimals(min_value=D("0"), max_value=D("1"), places=4),
)
def test_a_partial_answer_accepts_strictly_between_nothing_and_all(
    claimed: Decimal, share: Decimal
) -> None:
    accepted = (claimed * share).quantize(D("0.01"))
    if D("0") < accepted < claimed:
        assert response_amount("partial", claimed, accepted) == accepted
    else:
        assert _code(lambda: response_amount("partial", claimed, accepted)) == (
            "CLAIM_AMOUNT_INVALID"
        )


def test_a_partial_answer_needs_its_amount_and_a_known_outcome() -> None:
    assert _code(lambda: response_amount("partial", D("10.00"), None)) == "CLAIM_AMOUNT_INVALID"
    assert _code(lambda: response_amount("maybe", D("10.00"), None)) == "CLAIM_AMOUNT_INVALID"
