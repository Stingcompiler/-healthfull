from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.visit import check_close


def test_an_open_visit_out_of_the_queue_and_not_admitted_closes() -> None:
    check_close(status="open", active_queue_entries=0, open_admission=False)


@given(
    st.sampled_from(["open", "closed", "cancelled"]),
    st.integers(min_value=0, max_value=3),
    st.booleans(),
)
def test_exactly_the_clean_open_visit_closes(status: str, queued: int, admitted: bool) -> None:
    allowed = status == "open" and queued == 0 and not admitted
    if allowed:
        check_close(status=status, active_queue_entries=queued, open_admission=admitted)
        return
    if status != "open":
        expected = "VISIT_NOT_OPEN"
    else:
        expected = "VISIT_IN_QUEUE" if queued else "VISIT_ADMITTED"
    with pytest.raises(DomainError) as err:
        check_close(status=status, active_queue_entries=queued, open_admission=admitted)
    assert err.value.code == expected


def test_the_queue_count_is_reported() -> None:
    with pytest.raises(DomainError) as err:
        check_close(status="open", active_queue_entries=2, open_admission=False)
    assert err.value.details == {"entries": 2}
