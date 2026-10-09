"""Lab bench rules: the work-list stage of a test and the turnaround summary (FEATURES 9.2, 9.8)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.lab import SampleState, Stage, TurnaroundStats, stage, turnaround_stats

# --- stage ---------------------------------------------------------------------------------


def test_stage_follows_the_bench_steps() -> None:
    assert stage(sample=None) is Stage.TO_COLLECT
    assert stage(sample=SampleState.REJECTED) is Stage.TO_COLLECT
    assert stage(sample=SampleState.COLLECTED) is Stage.TO_RECEIVE
    assert stage(sample=SampleState.RECEIVED) is Stage.TO_ENTER
    # Some values entered: still entering until every parameter has one.
    assert stage(sample=SampleState.RECEIVED, draft=True, entered=1, expected=3) is Stage.TO_ENTER
    assert stage(sample=SampleState.RECEIVED, draft=True, entered=3, expected=3) is Stage.TO_APPROVE
    assert stage(sample=SampleState.RECEIVED, approved=True) is Stage.DONE
    # An amendment of an approved result waits for approval again.
    amended = stage(sample=SampleState.RECEIVED, approved=True, draft=True, entered=3, expected=3)
    assert amended is Stage.TO_APPROVE
    assert stage(sample=SampleState.RECEIVED, cancelled=True) is Stage.CANCELLED


def test_stage_refuses_impossible_counts() -> None:
    with pytest.raises(ValueError, match="entered"):
        stage(sample=SampleState.RECEIVED, draft=True, entered=-1, expected=2)
    with pytest.raises(ValueError, match="draft"):
        stage(sample=SampleState.RECEIVED, draft=False, entered=1, expected=2)


samples = st.one_of(st.none(), st.sampled_from(list(SampleState)))


@given(
    sample=samples,
    cancelled=st.booleans(),
    approved=st.booleans(),
    draft=st.booleans(),
    expected=st.integers(0, 12),
    data=st.data(),
)
def test_stage_properties(
    sample: SampleState | None,
    cancelled: bool,
    approved: bool,
    draft: bool,
    expected: int,
    data: st.DataObject,
) -> None:
    entered = data.draw(st.integers(0, expected)) if draft else 0
    got = stage(
        sample=sample,
        cancelled=cancelled,
        approved=approved,
        draft=draft,
        entered=entered,
        expected=expected,
    )
    if cancelled:
        assert got is Stage.CANCELLED
        return
    # Only a complete draft is ever offered for approval (approval needs every value).
    if got is Stage.TO_APPROVE:
        assert draft
        assert expected > 0
        assert entered == expected
    if got is Stage.DONE:
        assert approved
        assert not draft
    # Before the sample is in the lab, no result step is offered for a first result.
    if not approved and not draft and sample is not SampleState.RECEIVED:
        assert got in (Stage.TO_COLLECT, Stage.TO_RECEIVE)


# --- turnaround ----------------------------------------------------------------------------


def test_turnaround_stats_example() -> None:
    stats = turnaround_stats([30, 50, 70, 200], target=60)
    assert stats == TurnaroundStats(
        count=4, mean=88, median=50, p90=200, maximum=200, within_target=2
    )
    assert stats.within_target_percent == 50
    empty = turnaround_stats([], target=60)
    assert empty == TurnaroundStats(0, None, None, None, None, 0)
    assert empty.within_target_percent is None


def test_turnaround_rounds_the_mean_half_up_and_refuses_bad_input() -> None:
    assert turnaround_stats([1, 2], target=1).mean == 2  # 1.5 -> 2
    with pytest.raises(ValueError, match="negative"):
        turnaround_stats([-1], target=60)
    with pytest.raises(ValueError, match="target"):
        turnaround_stats([1], target=0)


@given(st.lists(st.integers(0, 100_000), max_size=60), st.integers(1, 10_000))
def test_turnaround_properties(minutes: list[int], target: int) -> None:
    stats = turnaround_stats(minutes, target=target)
    assert stats.count == len(minutes)
    assert stats.within_target == sum(1 for m in minutes if m <= target)
    if not minutes:
        assert stats.mean is None
        assert stats.median is None
        assert stats.p90 is None
        assert stats.maximum is None
        return
    assert stats.maximum == max(minutes)
    assert stats.median is not None
    assert stats.p90 is not None
    assert stats.mean is not None
    assert min(minutes) <= stats.median <= stats.p90 <= max(minutes)
    assert min(minutes) <= stats.mean <= max(minutes)
    assert abs(stats.mean - sum(minutes) / len(minutes)) <= 0.5
    # Nearest rank: at least 90% of the values are at or below p90.
    assert sum(1 for m in minutes if m <= stats.p90) >= math.ceil(0.9 * len(minutes))
    assert stats.p90 in minutes
    assert stats.median in minutes
    percent = stats.within_target_percent
    assert percent is not None
    assert 0 <= percent <= 100
