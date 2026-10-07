from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.errors import DomainError
from domain.lab import (
    Flag,
    ReferenceRange,
    ResultStatus,
    ResultVersion,
    Sex,
    age_in_days,
    approve_version,
    first_version,
    flag,
    needs_critical_alert,
    performs_line,
    require_editable,
    select_range,
    start_amendment,
    visible_version,
)

OK = Approval(approver_id=6, at=datetime(2026, 10, 7, tzinfo=UTC), reason="transcription error")
D = Decimal
YEAR = 365


# --- reference ranges -----------------------------------------------------------------------


def test_age_in_days() -> None:
    assert age_in_days(date(2026, 10, 1), date(2026, 10, 7)) == 6
    with pytest.raises(DomainError) as exc:
        age_in_days(date(2026, 10, 8), date(2026, 10, 7))
    assert exc.value.code == "INVALID_DATE_RANGE"


HB = [
    ReferenceRange(low=D("13.5"), high=D("17.5"), sex=Sex.MALE, age_min_days=18 * YEAR),
    ReferenceRange(low=D("12.0"), high=D("15.5"), sex=Sex.FEMALE, age_min_days=18 * YEAR),
    ReferenceRange(low=D("11.0"), high=D("13.5"), age_min_days=YEAR, age_max_days=18 * YEAR),
    ReferenceRange(low=D("14.0"), high=D("24.0"), age_max_days=28),
    ReferenceRange(low=D("11.0"), high=D("18.0"), critical_low=D("7.0"), critical_high=D("20.0")),
]


def test_select_range_by_sex_and_age() -> None:
    assert select_range(HB, Sex.MALE, 30 * YEAR) is HB[0]
    assert select_range(HB, Sex.FEMALE, 30 * YEAR) is HB[1]
    assert select_range(HB, Sex.MALE, 5 * YEAR) is HB[2]
    assert select_range(HB, Sex.FEMALE, 3) is HB[3]
    # Unknown sex or age: only ranges that do not depend on them apply.
    assert select_range(HB, None, 30 * YEAR) is HB[4]
    assert select_range(HB, Sex.MALE, None) is HB[4]
    assert select_range(HB[:2], None, None) is None


sexes = st.none() | st.sampled_from(list(Sex))


@st.composite
def ranges(draw: st.DrawFn) -> ReferenceRange:
    lo = draw(st.none() | st.integers(0, 5000))
    hi = draw(st.none() | st.integers(1, 20000))
    if lo is not None and hi is not None and hi <= lo:
        hi = lo + 1
    return ReferenceRange(low=D(1), high=D(2), sex=draw(sexes), age_min_days=lo, age_max_days=hi)


def _width(r: ReferenceRange) -> float:
    lo = r.age_min_days or 0
    return float("inf") if r.age_max_days is None else r.age_max_days - lo


@given(st.lists(ranges(), max_size=8), sexes, st.none() | st.integers(0, 30000))
def test_select_range_picks_the_most_specific_applicable(
    rs: list[ReferenceRange], sex: Sex | None, age: int | None
) -> None:
    chosen = select_range(rs, sex, age)
    applicable = [r for r in rs if r.applies_to(sex, age)]
    if not applicable:
        assert chosen is None
        return
    assert chosen is not None
    assert chosen.applies_to(sex, age)
    for r in applicable:
        assert (_width(r), r.sex is None) >= (_width(chosen), chosen.sex is None)


def test_invalid_ranges() -> None:
    for kwargs in (
        {"low": D(5), "high": D(4)},
        {"low": D(5), "critical_low": D(5)},
        {"high": D(5), "critical_high": D(5)},
        {"age_min_days": 10, "age_max_days": 10},
        {"age_min_days": -1},
    ):
        with pytest.raises(DomainError) as exc:
            ReferenceRange(**kwargs)
        assert exc.value.code == "INVALID_REFERENCE_RANGE"


values = st.decimals(min_value=-100, max_value=100, places=2)


@given(values)
def test_flagging(value: Decimal) -> None:
    rng = ReferenceRange(low=D(-10), high=D(10), critical_low=D(-50), critical_high=D(50))
    f = flag(value, rng)
    if value <= -50:
        assert f is Flag.CRITICAL_LOW
    elif value >= 50:
        assert f is Flag.CRITICAL_HIGH
    elif value < -10:
        assert f is Flag.LOW
    elif value > 10:
        assert f is Flag.HIGH
    else:
        assert f is Flag.NORMAL
    assert flag(value, None) is Flag.NONE
    assert flag(value, ReferenceRange()) is Flag.NORMAL


def test_critical_alert() -> None:
    assert needs_critical_alert([Flag.NORMAL, Flag.CRITICAL_HIGH])
    assert not needs_critical_alert([Flag.LOW, Flag.HIGH, Flag.NONE])


# --- result versions -------------------------------------------------------------------------


def test_result_version_lifecycle() -> None:
    v1 = first_version()
    assert (v1.number, v1.status) == (1, ResultStatus.DRAFT)
    require_editable(v1)
    assert visible_version([v1]) is None
    a1 = approve_version(v1)
    assert performs_line([v1], a1)
    with pytest.raises(DomainError) as exc:
        require_editable(a1)
    assert exc.value.code == "RESULT_APPROVED_IMMUTABLE"
    with pytest.raises(DomainError) as exc:
        approve_version(a1)
    assert exc.value.code == "RESULT_NOT_DRAFT"
    assert visible_version([a1]) == a1

    v2 = start_amendment([a1], OK)
    assert (v2.number, v2.status, v2.amends) == (2, ResultStatus.DRAFT, 1)
    # The amendment draft is not visible; the original approved version stays visible.
    assert visible_version([a1, v2]) == a1
    with pytest.raises(DomainError) as exc:
        start_amendment([a1, v2], OK)
    assert exc.value.code == "AMENDMENT_IN_PROGRESS"
    a2 = approve_version(v2)
    assert not performs_line([a1, v2], a2)
    assert visible_version([a1, a2]) == a2


def test_amendment_needs_an_approved_result_and_a_reason() -> None:
    with pytest.raises(DomainError) as exc:
        start_amendment([first_version()], OK)
    assert exc.value.code == "RESULT_NOT_APPROVED"
    with pytest.raises(DomainError) as exc:
        start_amendment([], OK)
    assert exc.value.code == "RESULT_NOT_APPROVED"
    with pytest.raises(TypeError):
        start_amendment([approve_version(first_version())], None)  # type: ignore[arg-type]


@given(st.lists(st.sampled_from(["approve", "amend"]), max_size=12))
def test_random_version_histories(ops: list[str]) -> None:
    versions: list[ResultVersion] = [first_version()]
    for op in ops:
        try:
            if op == "approve":
                draft = versions[-1]
                versions[-1] = approve_version(draft)
            else:
                versions.append(start_amendment(versions, OK))
        except DomainError:
            continue
        numbers = [v.number for v in versions]
        assert numbers == list(range(1, len(versions) + 1))
        # At most one draft, always the newest; every amendment points at its predecessor.
        drafts = [v for v in versions if v.status is ResultStatus.DRAFT]
        assert len(drafts) <= 1
        if drafts:
            assert drafts[0] is versions[-1]
        for v in versions[1:]:
            assert v.amends == v.number - 1
        visible = visible_version(versions)
        approved = [v for v in versions if v.status is ResultStatus.APPROVED]
        assert visible == (approved[-1] if approved else None)
