"""Patient-facing status mapping for the visit timeline and notices (plan section 5; ADR 0029
"Phase 5 as built"). Every combination of every internal status enum maps to a patient-facing
value, never to an "unknown" (Hypothesis over the whole product of the enums)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.appointments import AppointmentState
from domain.portal_status import (
    BookingDisplay,
    NoticeKind,
    OrderDisplay,
    PaymentDisplay,
    VisitDisplay,
    VisitState,
    booking_display,
    booking_notice,
    invoice_display,
    order_display,
    visit_display,
)
from domain.service_line import BillingStatus, FulfilmentStatus

amounts = st.decimals(min_value=Decimal("-100"), max_value=Decimal("100000"), places=2)


@given(status=st.sampled_from(list(VisitState)))
def test_visit_display_is_total(status: VisitState) -> None:
    assert visit_display(status) in set(VisitDisplay)


@pytest.mark.parametrize(
    ("status", "shown"),
    [("open", "at_center"), ("closed", "completed"), ("cancelled", "cancelled")],
)
def test_visit_display_examples(status: str, shown: str) -> None:
    assert visit_display(status) == shown


def test_visit_display_refuses_an_unknown_status() -> None:
    with pytest.raises(ValueError, match="archived"):
        visit_display("archived")


@given(
    billing=st.sampled_from(list(BillingStatus)),
    fulfilment=st.sampled_from(list(FulfilmentStatus)),
    authorized=st.booleans(),
    is_lab=st.booleans(),
    published=st.booleans(),
)
def test_order_display_is_total(
    billing: BillingStatus,
    fulfilment: FulfilmentStatus,
    authorized: bool,
    is_lab: bool,
    published: bool,
) -> None:
    shown = order_display(
        billing=billing,
        fulfilment=fulfilment,
        authorized=authorized,
        is_lab=is_lab,
        result_published=published,
    )
    assert shown in set(OrderDisplay)
    # A line never reads "done" or "result published" before it is performed, and a lab
    # result is announced only when an approved version exists.
    if shown in (OrderDisplay.DONE, OrderDisplay.RESULT_PUBLISHED):
        assert fulfilment == FulfilmentStatus.PERFORMED
    if shown == OrderDisplay.RESULT_PUBLISHED:
        assert is_lab
        assert published
    # "Paid, waiting" only for money settled or a documented perform-first authorization.
    if shown == OrderDisplay.WAITING:
        assert billing == BillingStatus.SETTLED or authorized
    if fulfilment == FulfilmentStatus.CANCELLED:
        assert shown == OrderDisplay.CANCELLED


@pytest.mark.parametrize(
    ("billing", "fulfilment", "authorized", "is_lab", "published", "shown"),
    [
        ("unbilled", "pending", False, False, False, "pay_at_reception"),
        ("invoiced", "pending", False, True, False, "pay_at_reception"),
        ("settled", "pending", False, True, False, "waiting"),
        ("unbilled", "pending", True, False, False, "waiting"),
        ("settled", "in_progress", False, True, False, "in_progress"),
        ("settled", "performed", False, False, False, "done"),
        ("settled", "performed", False, True, False, "done"),
        ("settled", "performed", False, True, True, "result_published"),
        ("credited", "performed", False, True, True, "result_published"),
        ("credited", "cancelled", False, False, False, "cancelled"),
        ("credited", "pending", False, False, False, "cancelled"),
        ("unbilled", "cancelled", True, True, True, "cancelled"),
    ],
)
def test_order_display_examples(
    billing: str, fulfilment: str, authorized: bool, is_lab: bool, published: bool, shown: str
) -> None:
    assert (
        order_display(
            billing=billing,
            fulfilment=fulfilment,
            authorized=authorized,
            is_lab=is_lab,
            result_published=published,
        )
        == shown
    )


@given(due=amounts, outstanding=amounts, pending=amounts)
def test_invoice_display_is_total(due: Decimal, outstanding: Decimal, pending: Decimal) -> None:
    shown = invoice_display(patient_due=due, outstanding=outstanding, pending_applied=pending)
    assert shown in set(PaymentDisplay)
    if shown == PaymentDisplay.PAID:
        assert outstanding <= 0
        assert pending <= 0
        assert due > 0


@pytest.mark.parametrize(
    ("due", "outstanding", "pending", "shown"),
    [
        ("0.00", "0.00", "0.00", "nothing_due"),
        ("100.00", "100.00", "0.00", "outstanding"),
        ("100.00", "40.00", "60.00", "outstanding"),
        ("100.00", "0.00", "100.00", "under_verification"),
        ("100.00", "0.00", "0.00", "paid"),
    ],
)
def test_invoice_display_examples(due: str, outstanding: str, pending: str, shown: str) -> None:
    assert (
        invoice_display(
            patient_due=Decimal(due),
            outstanding=Decimal(outstanding),
            pending_applied=Decimal(pending),
        )
        == shown
    )


@given(display=st.sampled_from(list(BookingDisplay)))
def test_booking_notice_is_total(display: BookingDisplay) -> None:
    kind = booking_notice(display)
    assert kind is None or kind in set(NoticeKind)
    # Arrival and a missed booking are told in person, not in the inbox.
    assert (kind is None) == (display in (BookingDisplay.RECEIVED, BookingDisplay.MISSED))


@pytest.mark.parametrize(
    ("display", "kind"),
    [
        ("awaiting_approval", "booking_requested"),
        ("confirmed", "booking_confirmed"),
        ("declined", "booking_declined"),
        ("cancelled_by_you", "booking_cancelled"),
        ("cancelled_by_center", "booking_cancelled"),
        ("expired", "booking_expired"),
        ("moved", "booking_rescheduled"),
    ],
)
def test_booking_notice_examples(display: str, kind: str) -> None:
    assert booking_notice(BookingDisplay(display)) == kind


def test_every_appointment_state_has_a_display() -> None:
    # The booking family stays total (Phase 3) and every display has a notice decision.
    for state in AppointmentState:
        shown = booking_display(state, cancel_reason=None, was_request=False)
        assert booking_notice(shown) in {*NoticeKind, None}
