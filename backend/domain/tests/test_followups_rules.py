"""Phase 8 follow-up rules (ADR 0018): second-person approvals, voiding a line given under
an authorization recorded in error, and the plan for cancelling an admission made in error."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval, second_approval
from domain.errors import DomainError
from domain.inpatient import NightLine, plan_admission_cancel
from domain.service_line import (
    BILLED,
    BillingStatus,
    FulfilmentStatus,
    LineStatus,
    is_consistent,
    void_in_error,
)
from domain.stock import return_approval

B = BillingStatus
F = FulfilmentStatus
AT = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
OK = Approval(approver_id=1, at=AT, reason="admitted in error")

ALL_COMBOS = [
    (b, f, a) for b, f, a in itertools.product(B, F, [False, True]) if is_consistent(b, f, a)
]

ids = st.integers(min_value=1, max_value=10_000)


# --- second-person approval -----------------------------------------------------------------


@given(ids, ids)
def test_second_approval_needs_another_person(actor: int, approver: int) -> None:
    if actor == approver:
        with pytest.raises(DomainError) as exc:
            second_approval(actor, approver, AT, reason="r")
        assert exc.value.code == "SECOND_APPROVER_REQUIRED"
    else:
        approval = second_approval(actor, approver, AT, reason="  r ")
        assert approval.approver_id == approver
        assert approval.at == AT
        assert approval.reason_text == "r"


@given(ids)
def test_second_approval_without_an_approver_is_refused(actor: int) -> None:
    with pytest.raises(DomainError) as exc:
        second_approval(actor, None, AT, reason_code="WRONG_PATIENT")
    assert exc.value.code == "SECOND_APPROVER_REQUIRED"


def test_second_approval_still_needs_a_reason_and_an_aware_time() -> None:
    with pytest.raises(DomainError) as exc:
        second_approval(1, 2, AT)
    assert exc.value.code == "REASON_REQUIRED"
    with pytest.raises(DomainError) as exc:
        second_approval(1, 2, datetime(2026, 10, 10), reason="r")
    assert exc.value.code == "INVALID_TIMESTAMP"


# --- voiding a line recorded in error ---------------------------------------------------------


@pytest.mark.parametrize(("billing", "fulfilment", "authorized"), ALL_COMBOS)
def test_only_an_unbilled_authorized_performed_line_is_voided(
    billing: BillingStatus, fulfilment: FulfilmentStatus, authorized: bool
) -> None:
    status = LineStatus(billing, fulfilment, authorized)
    if billing is B.UNBILLED and fulfilment is F.PERFORMED and authorized:
        voided = void_in_error(status, OK)
        assert voided == LineStatus(B.UNBILLED, F.CANCELLED, True)
        return
    with pytest.raises(DomainError) as exc:
        void_in_error(status, OK)
    if billing in BILLED:
        assert exc.value.code == "CREDIT_NOTE_REQUIRED"
    elif fulfilment is F.CANCELLED:
        assert exc.value.code == "LINE_ALREADY_CANCELLED"
    else:
        assert exc.value.code == "LINE_NOT_VOIDABLE"


def test_voiding_needs_an_approval() -> None:
    with pytest.raises(TypeError):
        void_in_error(LineStatus(B.UNBILLED, F.PERFORMED, True), None)  # type: ignore[arg-type]


# --- cancelling an admission made in error -----------------------------------------------------

night_lines = st.lists(
    st.builds(
        NightLine,
        line_id=ids,
        billing=st.sampled_from(list(B)),
        fulfilment=st.sampled_from([F.PERFORMED, F.CANCELLED]),
    ),
    max_size=8,
    unique_by=lambda n: n.line_id,
)


@given(night_lines)
def test_admission_cancel_plan(nights: list[NightLine]) -> None:
    billed = sorted(n.line_id for n in nights if n.billing in BILLED)
    if billed:
        # Invoiced nights are corrected by a credit note at the cashier first (invariant 2).
        with pytest.raises(DomainError) as exc:
            plan_admission_cancel(nights)
        assert exc.value.code == "ADMISSION_NIGHTS_INVOICED"
        assert exc.value.details["line_ids"] == billed
        assert exc.value.details["count"] == len(billed)
        return
    plan = plan_admission_cancel(nights)
    expected = sorted(
        n.line_id for n in nights if n.billing is B.UNBILLED and n.fulfilment is F.PERFORMED
    )
    assert list(plan.void) == expected
    # Credited and already cancelled nights are left as they are.
    untouched = {n.line_id for n in nights} - set(plan.void)
    assert all(
        n.billing is B.CREDITED or n.fulfilment is F.CANCELLED
        for n in nights
        if n.line_id in untouched
    )


def test_an_admission_without_nights_cancels_with_nothing_to_void() -> None:
    assert plan_admission_cancel([]).void == ()


# --- dispense returns ------------------------------------------------------------------------


@given(st.booleans(), ids, st.one_of(st.none(), ids))
def test_return_of_billed_units_needs_a_second_person(
    billed: bool, actor: int, approver: int | None
) -> None:
    if billed and (approver is None or approver == actor):
        with pytest.raises(DomainError) as exc:
            return_approval(billed=billed, actor_id=actor, approver_id=approver, at=AT, reason="r")
        assert exc.value.code == "SECOND_APPROVER_REQUIRED"
        return
    approval = return_approval(
        billed=billed, actor_id=actor, approver_id=approver, at=AT, reason_code="PATIENT_RETURNED"
    )
    # A billed line's units come back on someone else's approval; unbilled ones on the actor's.
    assert approval.approver_id == (approver if billed else actor)


def test_a_return_needs_a_reason() -> None:
    with pytest.raises(DomainError) as exc:
        return_approval(billed=False, actor_id=1, approver_id=None, at=AT)
    assert exc.value.code == "REASON_REQUIRED"
