from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.coverage import (
    CoverageKind,
    CoverageRule,
    check_discount,
    check_preapproval,
    discount_allowed,
    discount_within_limit,
    distribute_discount,
    max_discount_percent,
    payer_share_for,
    split_line,
)
from domain.errors import DomainError
from domain.money import ZERO, percent_of

OK = Approval(approver_id=3, at=datetime(2026, 10, 7, tzinfo=UTC), reason="loyal patient")
amounts = st.decimals(min_value=0, max_value=Decimal("100000000"), places=2)
percents = st.decimals(min_value=0, max_value=100, places=2)


@st.composite
def rules(draw: st.DrawFn) -> CoverageRule:
    kind = draw(st.sampled_from(list(CoverageKind)))
    if kind is CoverageKind.PERCENTAGE:
        return CoverageRule.percentage(draw(percents))
    if kind is CoverageKind.FIXED_PATIENT_COPAY:
        return CoverageRule.fixed_copay(draw(amounts))
    return CoverageRule.capped(draw(amounts), payer_percent=draw(percents))


optional_rules = st.none() | rules()


@st.composite
def gross_and_discount(draw: st.DrawFn) -> tuple[Decimal, Decimal, CoverageRule | None, bool]:
    gross = draw(amounts)
    rule = draw(optional_rules)
    excluded = draw(st.booleans())
    payer = payer_share_for(gross, rule, excluded=excluded)
    discount = draw(st.decimals(min_value=0, max_value=gross - payer, places=2))
    return gross, discount, rule, excluded


# --- split_line ---------------------------------------------------------------------


@given(gross_and_discount())
def test_split_parts_sum_to_gross_and_are_non_negative(
    case: tuple[Decimal, Decimal, CoverageRule | None, bool],
) -> None:
    gross, discount, rule, excluded = case
    s = split_line(gross, discount, rule, excluded=excluded)
    assert s.payer_share + s.patient_share + s.discount == gross
    assert s.patient_share == gross - discount - s.payer_share
    assert min(s.payer_share, s.patient_share, s.discount) >= 0
    assert s.patient_before_discount == gross - s.payer_share


@given(gross_and_discount())
def test_discount_only_touches_the_patient_side(
    case: tuple[Decimal, Decimal, CoverageRule | None, bool],
) -> None:
    gross, discount, rule, excluded = case
    with_d = split_line(gross, discount, rule, excluded=excluded)
    without = split_line(gross, ZERO, rule, excluded=excluded)
    assert with_d.payer_share == without.payer_share
    assert with_d.patient_share == without.patient_share - discount


@given(amounts, optional_rules, st.decimals(min_value=Decimal("0.01"), max_value=1000, places=2))
def test_discount_above_patient_share_is_refused(
    gross: Decimal, rule: CoverageRule | None, extra: Decimal
) -> None:
    payer = payer_share_for(gross, rule)
    with pytest.raises(DomainError) as exc:
        split_line(gross, gross - payer + extra, rule)
    assert exc.value.code == "DISCOUNT_EXCEEDS_PATIENT_SHARE"


@given(amounts, rules())
def test_exclusion_routes_everything_to_the_patient(gross: Decimal, rule: CoverageRule) -> None:
    s = split_line(gross, ZERO, rule, excluded=True)
    assert s.payer_share == 0
    assert s.patient_share == gross


@given(amounts)
def test_cash_line_has_no_payer_share(gross: Decimal) -> None:
    assert split_line(gross, ZERO, None).patient_share == gross


@given(amounts, percents)
def test_percentage_rule(gross: Decimal, p: Decimal) -> None:
    assert payer_share_for(gross, CoverageRule.percentage(p)) == percent_of(gross, p)


@given(amounts, amounts)
def test_fixed_copay_rule(gross: Decimal, copay: Decimal) -> None:
    s = split_line(gross, ZERO, CoverageRule.fixed_copay(copay))
    assert s.patient_share == min(copay, gross)


@given(amounts, amounts, percents)
def test_ceiling_rule(gross: Decimal, ceiling: Decimal, p: Decimal) -> None:
    payer = payer_share_for(gross, CoverageRule.capped(ceiling, payer_percent=p))
    assert payer == min(percent_of(gross, p), ceiling)
    assert payer <= ceiling


@given(amounts, amounts, rules())
def test_payer_share_never_decreases_with_gross(a: Decimal, b: Decimal, rule: CoverageRule) -> None:
    lo, hi = sorted((a, b))
    assert payer_share_for(lo, rule) <= payer_share_for(hi, rule)


def test_flow_example_drug_split() -> None:
    # DECISION.md: a 10,000 drug, 7,000 on the insurer, 3,000 paid by the patient.
    s = split_line(Decimal("10000.00"), ZERO, CoverageRule.percentage(Decimal(70)))
    assert (s.payer_share, s.patient_share) == (Decimal("7000.00"), Decimal("3000.00"))


@pytest.mark.parametrize(
    "build",
    [
        lambda: CoverageRule(CoverageKind.PERCENTAGE, payer_percent=Decimal(101)),
        lambda: CoverageRule(CoverageKind.PERCENTAGE, payer_percent=Decimal(-1)),
        lambda: CoverageRule(CoverageKind.FIXED_PATIENT_COPAY, copay=Decimal("-1.00")),
        lambda: CoverageRule(CoverageKind.PAYER_CEILING, ceiling=Decimal("1.001")),
    ],
)
def test_invalid_rules_are_refused(build: object) -> None:
    with pytest.raises(DomainError) as exc:
        build()  # type: ignore[operator]
    assert exc.value.code == "INVALID_COVERAGE_RULE"


def test_negative_amounts_are_refused() -> None:
    with pytest.raises(DomainError):
        split_line(Decimal("-1.00"), ZERO, None)
    with pytest.raises(DomainError):
        split_line(Decimal("1.00"), Decimal("-0.01"), None)


# --- discounts --------------------------------------------------------------------------


@given(amounts, amounts, percents)
def test_discount_within_limit_is_exact(discount: Decimal, base: Decimal, limit: Decimal) -> None:
    assert discount_within_limit(discount, base, limit) is (discount * 100 <= limit * base)


LIMITS: dict[str, Decimal | int] = {
    "cashier": 0,
    "cashier_supervisor": 25,
    "accountant": Decimal("12.5"),
    "manager": 100,
}


def test_max_discount_percent_is_best_role() -> None:
    assert max_discount_percent(["cashier"], LIMITS) == 0
    assert max_discount_percent(["cashier", "accountant"], LIMITS) == Decimal("12.5")
    assert max_discount_percent(["doctor"], LIMITS) == 0
    assert max_discount_percent([], LIMITS) == 0
    assert discount_allowed(Decimal(25), LIMITS, ["cashier_supervisor"])
    assert not discount_allowed(Decimal("25.01"), LIMITS, ["cashier_supervisor"])
    assert discount_allowed(Decimal(0), LIMITS, ["doctor"])


@given(st.lists(st.sampled_from(sorted(LIMITS)), max_size=4), percents)
def test_discount_allowed_iff_some_role_allows_it(roles: list[str], p: Decimal) -> None:
    expected = any(p <= Decimal(LIMITS[r]) for r in roles) or p == 0
    assert discount_allowed(p, LIMITS, roles) is expected


def test_check_discount() -> None:
    base = Decimal("1000.00")
    check_discount(ZERO, base, ["cashier"], LIMITS, None)
    check_discount(Decimal("250.00"), base, ["cashier_supervisor"], LIMITS, OK)
    with pytest.raises(DomainError) as exc:
        check_discount(Decimal("250.01"), base, ["cashier_supervisor"], LIMITS, OK)
    assert exc.value.code == "DISCOUNT_LIMIT_EXCEEDED"
    with pytest.raises(DomainError) as exc:
        check_discount(Decimal("10.00"), base, ["manager"], LIMITS, None)
    assert exc.value.code == "REASON_REQUIRED"
    with pytest.raises(DomainError) as exc:
        check_discount(Decimal("1000.01"), base, ["manager"], LIMITS, OK)
    assert exc.value.code == "DISCOUNT_EXCEEDS_PATIENT_SHARE"


@given(st.lists(amounts, min_size=1, max_size=10), st.data())
def test_distribute_discount_is_exact_and_capped(bases: list[Decimal], data: st.DataObject) -> None:
    total_base = sum(bases, ZERO)
    total = data.draw(st.decimals(min_value=0, max_value=total_base, places=2))
    assume(total == 0 or total_base > 0)
    parts = distribute_discount(total, bases)
    assert sum(parts, ZERO) == total
    assert all(0 <= p <= b for p, b in zip(parts, bases, strict=True))


def test_distribute_discount_refuses_more_than_bases() -> None:
    with pytest.raises(DomainError) as exc:
        distribute_discount(Decimal("10.01"), [Decimal("5.00"), Decimal("5.00")])
    assert exc.value.code == "DISCOUNT_EXCEEDS_PATIENT_SHARE"


# --- pre-approval ------------------------------------------------------------------------


def test_preapproval_reference() -> None:
    rule = CoverageRule.percentage(Decimal(80), requires_preapproval=True)
    assert check_preapproval(rule, " PA-77 ") == "PA-77"
    with pytest.raises(DomainError) as exc:
        check_preapproval(rule, " ")
    assert exc.value.code == "PREAPPROVAL_REQUIRED"
    assert check_preapproval(CoverageRule.percentage(Decimal(80)), None) is None
    assert check_preapproval(None, "x") == "x"
    # An excluded service is not covered, so no pre-approval is needed.
    assert check_preapproval(rule, None, excluded=True) is None
