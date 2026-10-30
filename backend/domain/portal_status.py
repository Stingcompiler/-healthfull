"""What the patient is told about their records (plan section 5; ADR 0029). Pure.

Four families kept distinct: booking (Phase 3), visit, order (``ServiceLine``) and payment
(Phase 5, the visit timeline), plus which booking change becomes a portal notice. Every
combination maps to a patient-facing status (never "unknown"; Hypothesis-tested). A booking
never says "received", "paid" or "done" on its own beyond ``arrived``: those come from the
visit, payment and order rows.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from domain.appointments import AppointmentState
from domain.service_line import BillingStatus, FulfilmentStatus

__all__ = [
    "BookingDisplay",
    "NoticeKind",
    "OrderDisplay",
    "PaymentDisplay",
    "VisitDisplay",
    "VisitState",
    "booking_display",
    "booking_notice",
    "invoice_display",
    "order_display",
    "visit_display",
]

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


# --- visit, order and payment families (Phase 5: the visit timeline) ----------------------


class VisitState(StrEnum):
    """``visits.VisitStatus``, repeated here so the mapping stays pure."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class VisitDisplay(StrEnum):
    AT_CENTER = "at_center"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def visit_display(status: str) -> VisitDisplay:
    """ "At the center today" / "completed" / "cancelled".

    Raises: ValueError for a status that is not a visit status.
    """
    state = VisitState(status)
    if state == VisitState.OPEN:
        return VisitDisplay.AT_CENTER
    if state == VisitState.CLOSED:
        return VisitDisplay.COMPLETED
    return VisitDisplay.CANCELLED


class OrderDisplay(StrEnum):
    PAY_AT_RECEPTION = "pay_at_reception"
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    RESULT_PUBLISHED = "result_published"
    CANCELLED = "cancelled"


def order_display(
    *,
    billing: str,
    fulfilment: str,
    authorized: bool,
    is_lab: bool,
    result_published: bool,
) -> OrderDisplay:
    """What a service line means for the patient (ARCHITECTURE 4.4 seen from outside).

    ``authorized``: an unrevoked perform-first authorization covers the line (it may be
    served before payment, invariant 1). ``result_published``: a lab line has an approved
    result version the portal shows. A lab line reads "result published" only then; other
    performed lines read "done". A credited line that was never given is cancelled (4.4
    rule 5); a performed line stays done whatever its money did afterwards.
    """
    bill = BillingStatus(billing)
    work = FulfilmentStatus(fulfilment)
    if work == FulfilmentStatus.CANCELLED:
        return OrderDisplay.CANCELLED
    if work == FulfilmentStatus.PERFORMED:
        if is_lab and result_published:
            return OrderDisplay.RESULT_PUBLISHED
        return OrderDisplay.DONE
    if work == FulfilmentStatus.IN_PROGRESS:
        return OrderDisplay.IN_PROGRESS
    if bill == BillingStatus.CREDITED:
        return OrderDisplay.CANCELLED
    if bill == BillingStatus.SETTLED or authorized:
        return OrderDisplay.WAITING
    return OrderDisplay.PAY_AT_RECEPTION


class PaymentDisplay(StrEnum):
    NOTHING_DUE = "nothing_due"
    OUTSTANDING = "outstanding"
    UNDER_VERIFICATION = "under_verification"
    PAID = "paid"


def invoice_display(
    *, patient_due: Decimal, outstanding: Decimal, pending_applied: Decimal
) -> PaymentDisplay:
    """An approved invoice from the patient's side: nothing to pay (the payer covers it all),
    still owed, paid with money the bank has not confirmed yet, or paid (invariant 7: the
    payer's share is never shown as the patient's)."""
    if patient_due <= 0:
        return PaymentDisplay.NOTHING_DUE
    if outstanding > 0:
        return PaymentDisplay.OUTSTANDING
    if pending_applied > 0:
        return PaymentDisplay.UNDER_VERIFICATION
    return PaymentDisplay.PAID


# --- portal notices (Phase 5) -------------------------------------------------------------


class NoticeKind(StrEnum):
    """``portal.PatientNotice.kind``: what the patient's inbox says."""

    BOOKING_REQUESTED = "booking_requested"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_DECLINED = "booking_declined"
    BOOKING_CANCELLED = "booking_cancelled"
    BOOKING_RESCHEDULED = "booking_rescheduled"
    BOOKING_EXPIRED = "booking_expired"
    RESULT_PUBLISHED = "result_published"


_BOOKING_NOTICE: dict[BookingDisplay, NoticeKind | None] = {
    BookingDisplay.AWAITING_APPROVAL: NoticeKind.BOOKING_REQUESTED,
    BookingDisplay.CONFIRMED: NoticeKind.BOOKING_CONFIRMED,
    BookingDisplay.DECLINED: NoticeKind.BOOKING_DECLINED,
    BookingDisplay.CANCELLED_BY_YOU: NoticeKind.BOOKING_CANCELLED,
    BookingDisplay.CANCELLED_BY_CENTER: NoticeKind.BOOKING_CANCELLED,
    BookingDisplay.EXPIRED: NoticeKind.BOOKING_EXPIRED,
    BookingDisplay.MOVED: NoticeKind.BOOKING_RESCHEDULED,
    # The patient is at the desk (arrival) or the time has passed (missed): no notice.
    BookingDisplay.RECEIVED: None,
    BookingDisplay.MISSED: None,
}


def booking_notice(display: BookingDisplay) -> NoticeKind | None:
    """The notice a booking change writes, from the booking's new patient-facing status."""
    return _BOOKING_NOTICE[display]
