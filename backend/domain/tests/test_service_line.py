from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.errors import DomainError
from domain.service_line import (
    BillingStatus,
    FulfilmentStatus,
    LineState,
    LineStatus,
    apply_settlement,
    authorize,
    can_enter_worklist,
    cancel,
    credit,
    derived_state,
    invoice,
    is_consistent,
    perform,
    replacement,
    settle,
    start,
    unsettle,
)

B = BillingStatus
F = FulfilmentStatus
OK = Approval(approver_id=1, at=datetime(2026, 10, 7, tzinfo=UTC), reason="test")

ALL_COMBOS = [
    (b, f, a) for b, f, a in itertools.product(B, F, [False, True]) if is_consistent(b, f, a)
]
statuses = st.sampled_from([LineStatus(b, f, a) for b, f, a in ALL_COMBOS])


def _code(fn: Callable[[], object]) -> str | None:
    try:
        fn()
    except DomainError as exc:
        return exc.code
    return None


# --- derived state and eligibility ------------------------------------------------------


@pytest.mark.parametrize(("billing", "fulfilment", "authorized"), ALL_COMBOS)
def test_derived_state_follows_architecture_order(
    billing: BillingStatus, fulfilment: FulfilmentStatus, authorized: bool
) -> None:
    state = derived_state(billing, fulfilment)
    if fulfilment is F.CANCELLED:
        assert state is LineState.CANCELLED
    elif fulfilment is F.PERFORMED:
        assert state is LineState.PERFORMED
    elif billing is B.SETTLED:
        assert state is LineState.PAID
    elif billing is B.INVOICED:
        assert state is LineState.INVOICED
    else:
        assert state is LineState.REQUESTED
    assert LineStatus(billing, fulfilment, authorized).state is state


@pytest.mark.parametrize(("billing", "fulfilment", "authorized"), ALL_COMBOS)
def test_worklist_rule(
    billing: BillingStatus, fulfilment: FulfilmentStatus, authorized: bool
) -> None:
    status = LineStatus(billing, fulfilment, authorized)
    expected = fulfilment in (F.PENDING, F.IN_PROGRESS) and (billing is B.SETTLED or authorized)
    assert can_enter_worklist(status) is expected


def test_inconsistent_combinations_are_refused() -> None:
    bad = [
        (b, f, a)
        for b, f, a in itertools.product(B, F, [False, True])
        if not is_consistent(b, f, a)
    ]
    # Performed or started without an invoice needs a perform-first authorization; a credited
    # line is never still open; an invoiced line is cancelled only through a credit note.
    assert (B.UNBILLED, F.PERFORMED, False) in bad
    assert (B.UNBILLED, F.IN_PROGRESS, False) in bad
    assert (B.CREDITED, F.PENDING, True) in bad
    assert (B.SETTLED, F.CANCELLED, False) in bad
    for b, f, a in bad:
        with pytest.raises(DomainError) as exc:
            LineStatus(b, f, a)
        assert exc.value.code == "INVALID_LINE_STATUS"


def test_new_line_is_requested_and_not_on_worklists() -> None:
    line = LineStatus()
    assert line.state is LineState.REQUESTED
    assert not can_enter_worklist(line)


# --- individual edges -----------------------------------------------------------------


def test_invoice_with_patient_due_is_invoiced_and_zero_due_settles() -> None:
    assert invoice(LineStatus(), patient_due=Decimal("10.00")).billing is B.INVOICED
    settled = invoice(LineStatus(), patient_due=Decimal("0.00"))
    assert settled.billing is B.SETTLED
    assert can_enter_worklist(settled)


def test_invoice_refusals() -> None:
    due = Decimal("1.00")
    assert _code(lambda: invoice(LineStatus(B.INVOICED), patient_due=due)) == "LINE_NOT_BILLABLE"
    cancelled = LineStatus(B.UNBILLED, F.CANCELLED)
    assert _code(lambda: invoice(cancelled, patient_due=due)) == "LINE_CANCELLED"
    assert _code(lambda: invoice(LineStatus(), patient_due=Decimal("-1.00"))) == "INVALID_AMOUNT"


def test_authorized_performed_line_can_be_invoiced_later() -> None:
    line = perform(authorize(LineStatus(), OK))
    assert line == LineStatus(B.UNBILLED, F.PERFORMED, True)
    assert invoice(line, patient_due=Decimal("5.00")).state is LineState.PERFORMED


def test_settle_and_unsettle() -> None:
    inv = LineStatus(B.INVOICED)
    assert settle(inv).billing is B.SETTLED
    assert unsettle(settle(inv)) == inv
    assert _code(lambda: settle(LineStatus())) == "LINE_NOT_PAYABLE"
    assert _code(lambda: settle(LineStatus(B.SETTLED))) == "LINE_NOT_PAYABLE"
    assert _code(lambda: unsettle(inv)) == "LINE_NOT_SETTLED"


def test_payment_reversal_takes_a_started_line_off_the_worklist() -> None:
    line = start(LineStatus(B.SETTLED))
    assert can_enter_worklist(line)
    back = unsettle(line)
    assert back == LineStatus(B.INVOICED, F.IN_PROGRESS)
    assert not can_enter_worklist(back)
    assert _code(lambda: perform(back)) == "LINE_NOT_ELIGIBLE"


@given(statuses, st.decimals(min_value=0, max_value=1000, places=2))
def test_apply_settlement_matches_outstanding(status: LineStatus, outstanding: Decimal) -> None:
    after = apply_settlement(status, outstanding=outstanding)
    if status.billing in (B.INVOICED, B.SETTLED):
        assert after.billing is (B.SETTLED if outstanding == 0 else B.INVOICED)
        assert (after.fulfilment, after.authorized) == (status.fulfilment, status.authorized)
    else:
        assert after == status


def test_perform_needs_payment_or_authorization() -> None:
    for status in (LineStatus(), LineStatus(B.INVOICED)):
        assert _code(lambda s=status: perform(s)) == "LINE_NOT_ELIGIBLE"  # type: ignore[misc]
        assert _code(lambda s=status: start(s)) == "LINE_NOT_ELIGIBLE"  # type: ignore[misc]
    assert perform(LineStatus(B.SETTLED)).state is LineState.PERFORMED
    assert perform(LineStatus(B.INVOICED, authorized=True)).state is LineState.PERFORMED
    assert start(LineStatus(B.SETTLED)).fulfilment is F.IN_PROGRESS


def test_terminal_fulfilment_refusals() -> None:
    done = LineStatus(B.SETTLED, F.PERFORMED)
    gone = LineStatus(B.UNBILLED, F.CANCELLED)
    assert _code(lambda: perform(done)) == "LINE_ALREADY_PERFORMED"
    assert _code(lambda: start(done)) == "LINE_ALREADY_PERFORMED"
    assert _code(lambda: cancel(done, OK, with_credit_note=True)) == "LINE_ALREADY_PERFORMED"
    assert _code(lambda: perform(gone)) == "LINE_CANCELLED"
    assert _code(lambda: start(gone)) == "LINE_CANCELLED"
    assert _code(lambda: cancel(gone, OK)) == "LINE_ALREADY_CANCELLED"
    assert _code(lambda: start(LineStatus(B.SETTLED, F.IN_PROGRESS))) == "LINE_ALREADY_STARTED"


def test_cancel_rules() -> None:
    assert cancel(LineStatus(), OK) == LineStatus(B.UNBILLED, F.CANCELLED)
    assert _code(lambda: cancel(LineStatus(B.INVOICED), OK)) == "CREDIT_NOTE_REQUIRED"
    assert _code(lambda: cancel(LineStatus(B.SETTLED), OK)) == "CREDIT_NOTE_REQUIRED"
    assert cancel(LineStatus(B.SETTLED), OK, with_credit_note=True) == LineStatus(
        B.CREDITED, F.CANCELLED
    )
    with pytest.raises(DomainError) as exc:
        cancel(LineStatus(), Approval(approver_id=1, at=OK.at, reason=" "))
    assert exc.value.code == "REASON_REQUIRED"


def test_credit_rules() -> None:
    # A full credit removes the line: an open line is cancelled, a performed one stays performed.
    assert credit(LineStatus(B.INVOICED), OK) == LineStatus(B.CREDITED, F.CANCELLED)
    assert credit(LineStatus(B.SETTLED, F.PERFORMED), OK) == LineStatus(B.CREDITED, F.PERFORMED)
    # A partial credit (e.g. the undispensed rest of a prescription) keeps the line as it is.
    part = LineStatus(B.SETTLED, F.PERFORMED)
    assert credit(part, OK, fully_credited=False) == part
    assert _code(lambda: credit(LineStatus(), OK)) == "LINE_NOT_CREDITABLE"
    assert _code(lambda: credit(LineStatus(B.CREDITED, F.CANCELLED), OK)) == "LINE_NOT_CREDITABLE"


def test_authorize_rules() -> None:
    assert authorize(LineStatus(), OK).authorized
    assert authorize(LineStatus(B.INVOICED), OK).authorized
    assert _code(lambda: authorize(LineStatus(B.SETTLED), OK)) == "LINE_ALREADY_SETTLED"
    assert _code(lambda: authorize(authorize(LineStatus(), OK), OK)) == "LINE_ALREADY_AUTHORIZED"
    assert _code(lambda: authorize(LineStatus(B.SETTLED, F.PERFORMED), OK)) == (
        "LINE_ALREADY_PERFORMED"
    )
    assert _code(lambda: authorize(LineStatus(B.UNBILLED, F.CANCELLED), OK)) == "LINE_CANCELLED"


def test_replacement_for_a_correction() -> None:
    performed = LineStatus(B.CREDITED, F.PERFORMED)
    assert replacement(performed, OK) == LineStatus(B.UNBILLED, F.PERFORMED, True)
    assert replacement(LineStatus(B.CREDITED, F.CANCELLED), OK) == LineStatus()
    assert _code(lambda: replacement(LineStatus(B.SETTLED), OK)) == "LINE_NOT_CREDITED"


# --- random walks: invariant 1 and terminal states --------------------------------------

EVENTS = ["invoice0", "invoice1", "settle", "unsettle", "credit", "credit_part", "authorize"]
EVENTS += ["start", "perform", "cancel", "cancel_cn"]


def _apply(status: LineStatus, event: str) -> LineStatus:
    if event == "invoice0":
        return invoice(status, patient_due=Decimal("0.00"))
    if event == "invoice1":
        return invoice(status, patient_due=Decimal("1.00"))
    if event == "settle":
        return settle(status)
    if event == "unsettle":
        return unsettle(status)
    if event == "credit":
        return credit(status, OK)
    if event == "credit_part":
        return credit(status, OK, fully_credited=False)
    if event == "authorize":
        return authorize(status, OK)
    if event == "start":
        return start(status)
    if event == "perform":
        return perform(status)
    if event == "cancel":
        return cancel(status, OK)
    return cancel(status, OK, with_credit_note=True)


@given(st.lists(st.sampled_from(EVENTS), max_size=40))
def test_random_walks_keep_every_rule(events: list[str]) -> None:
    status = LineStatus()
    for event in events:
        before = status
        try:
            status = _apply(status, event)
        except DomainError:
            assert status == before
            continue
        # Every state reached is a consistent one.
        assert is_consistent(status.billing, status.fulfilment, status.authorized)
        # Invariant 1: work starts or completes only on a paid or authorized line.
        if event in ("start", "perform"):
            assert can_enter_worklist(before)
        # Terminal fulfilment never changes.
        if before.fulfilment in (F.PERFORMED, F.CANCELLED):
            assert status.fulfilment is before.fulfilment
        # Authorization is never lost.
        assert status.authorized or not before.authorized
        # Credited is terminal for billing.
        if before.billing is B.CREDITED:
            assert status.billing is B.CREDITED


@given(statuses, st.sampled_from(EVENTS))
def test_every_edge_from_every_state_either_moves_consistently_or_refuses(
    status: LineStatus, event: str
) -> None:
    code = _code(lambda: _apply(status, event))
    if code is not None:
        assert code in {
            "LINE_NOT_BILLABLE",
            "LINE_CANCELLED",
            "LINE_NOT_PAYABLE",
            "LINE_NOT_SETTLED",
            "LINE_NOT_CREDITABLE",
            "LINE_ALREADY_SETTLED",
            "LINE_ALREADY_AUTHORIZED",
            "LINE_ALREADY_PERFORMED",
            "LINE_ALREADY_STARTED",
            "LINE_ALREADY_CANCELLED",
            "LINE_NOT_ELIGIBLE",
            "CREDIT_NOTE_REQUIRED",
        }
        return
    after = _apply(status, event)
    assert is_consistent(after.billing, after.fulfilment, after.authorized)
