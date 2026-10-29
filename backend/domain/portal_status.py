"""What the patient is told about their records (plan section 5; ADR 0029). Pure.

Booking family only for now (Phase 3); visits, orders and payments join in Phase 5. Every
combination maps to a patient-facing status (never "unknown"; Hypothesis-tested). A booking
never says "received", "paid" or "done" on its own beyond ``arrived``: those come from the
visit, payment and order rows.
"""

from __future__ import annotations

from enum import StrEnum

from domain.appointments import AppointmentState

__all__ = ["BookingDisplay", "booking_display"]

#: Reason codes (category ``appointment_cancel``) that tell the patient why a booking ended.
PATIENT_REQUEST = "PATIENT_REQUEST"
ONLINE_REQUEST_EXPIRED = "ONLINE_REQUEST_EXPIRED"
ONLINE_REJECTED = "ONLINE_REJECTED"


class BookingDisplay(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    CONFIRMED = "confirmed"
    RECEIVED = "received"
    MOVED = "moved"
    CANCELLED_BY_YOU = "cancelled_by_you"
    CANCELLED_BY_CENTER = "cancelled_by_center"
    DECLINED = "declined"
    EXPIRED = "expired"
    MISSED = "missed"


def booking_display(
    status: str, *, cancel_reason: str | None, was_request: bool, expired: bool = False
) -> BookingDisplay:
    """The patient-facing status of a booking.

    ``was_request``: it was made as an online request and never approved, so a cancellation by
    the center reads "declined". ``expired``: a request whose expiry passed before the sweep
    cancelled it (still ``requested`` in the row).
    """
    state = AppointmentState(status)
    if state == AppointmentState.REQUESTED:
        return BookingDisplay.EXPIRED if expired else BookingDisplay.AWAITING_APPROVAL
    if state == AppointmentState.BOOKED:
        return BookingDisplay.CONFIRMED
    if state == AppointmentState.ARRIVED:
        return BookingDisplay.RECEIVED
    if state == AppointmentState.RESCHEDULED:
        return BookingDisplay.MOVED
    if state == AppointmentState.NO_SHOW:
        return BookingDisplay.MISSED
    if cancel_reason == ONLINE_REQUEST_EXPIRED:
        return BookingDisplay.EXPIRED
    if cancel_reason == PATIENT_REQUEST:
        return BookingDisplay.CANCELLED_BY_YOU
    if cancel_reason == ONLINE_REJECTED or was_request:
        return BookingDisplay.DECLINED
    return BookingDisplay.CANCELLED_BY_CENTER
