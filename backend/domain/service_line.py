"""The service line state machine (ARCHITECTURE 4.4, FLOW "حالات سطر الخدمة").

A service line carries two orthogonal statuses plus a perform-first flag:

* ``billing``: ``unbilled`` -> ``invoiced`` -> ``settled``; ``credited`` once removed by a
  credit note. ``settled`` <-> ``invoiced`` follows the patient outstanding on the line
  (a payment reversal takes a settled line back to invoiced).
* ``fulfilment``: ``pending`` -> ``in_progress`` (optional) -> ``performed``; or
  ``cancelled``. ``performed`` and ``cancelled`` are terminal.
* ``authorized``: a documented perform-first authorization exists.

The derived display state is ``cancelled`` > ``performed`` > ``paid`` (settled) >
``invoiced`` > ``requested``.

Rules enforced here:

1. Work lists show, and work may start or complete on, only lines with fulfilment
   ``pending``/``in_progress`` that are settled or authorized (invariant 1).
2. A line settles when invoiced with zero patient outstanding (zero patient share settles at
   invoice approval).
3. Cancelling an invoiced or settled line needs a credit note; the line becomes credited.
4. A performed line is never cancelled; it can only be credited.
5. Cancel, credit and authorize take an :class:`~domain.audit.Approval` (invariant 4).

Every transition is a pure function ``LineStatus -> LineStatus`` that raises
:class:`~domain.errors.DomainError` with one of these codes:
``LINE_NOT_BILLABLE``, ``LINE_CANCELLED``, ``LINE_NOT_PAYABLE``, ``LINE_NOT_SETTLED``,
``LINE_NOT_CREDITABLE``, ``LINE_NOT_CREDITED``, ``LINE_ALREADY_SETTLED``,
``LINE_ALREADY_AUTHORIZED``, ``LINE_ALREADY_PERFORMED``, ``LINE_ALREADY_STARTED``,
``LINE_ALREADY_CANCELLED``, ``LINE_NOT_ELIGIBLE``, ``CREDIT_NOTE_REQUIRED``,
``INVALID_LINE_STATUS``, ``INVALID_AMOUNT``, ``REASON_REQUIRED``, ``INVALID_QUANTITY``,
``CREDIT_EXCEEDS_UNGIVEN``, ``LINE_NOT_VOIDABLE``.

Quantities (:func:`open_quantity`, :func:`remainder_to_credit`): units credited by an approved
credit note are never given afterwards, so what may still be performed or dispensed is the
ordered quantity less credited and already given units (invariant 1).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from domain.audit import Approval
from domain.errors import DomainError
from domain.money import require_non_negative

__all__ = [
    "ACTIVE_FULFILMENT",
    "BILLED",
    "TERMINAL_FULFILMENT",
    "BillingStatus",
    "DoctorStatus",
    "FulfilmentStatus",
    "LineState",
    "LineStatus",
    "apply_settlement",
    "authorize",
    "can_authorize",
    "can_enter_worklist",
    "cancel",
    "credit",
    "derived_state",
    "doctor_status",
    "invoice",
    "is_consistent",
    "open_quantity",
    "perform",
    "remainder_to_credit",
    "replacement",
    "settle",
    "start",
    "unsettle",
    "void_in_error",
]


class BillingStatus(StrEnum):
    UNBILLED = "unbilled"
    INVOICED = "invoiced"
    SETTLED = "settled"
    CREDITED = "credited"


class FulfilmentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PERFORMED = "performed"
    CANCELLED = "cancelled"


class LineState(StrEnum):
    """Derived display state (FEATURES 4.1)."""

    REQUESTED = "requested"
    INVOICED = "invoiced"
    PAID = "paid"
    PERFORMED = "performed"
    CANCELLED = "cancelled"


ACTIVE_FULFILMENT = frozenset({FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS})
TERMINAL_FULFILMENT = frozenset({FulfilmentStatus.PERFORMED, FulfilmentStatus.CANCELLED})
#: Billing statuses that sit on an approved invoice line and are not credited.
BILLED = frozenset({BillingStatus.INVOICED, BillingStatus.SETTLED})


def is_consistent(billing: BillingStatus, fulfilment: FulfilmentStatus, authorized: bool) -> bool:
    """Whether the combination can be reached through the transitions of this module.

    * A credited line is never still open (credit cancels an open line).
    * Work on an unbilled line exists only under a perform-first authorization.
    * An invoiced or settled line is cancelled only by crediting it.
    """
    if billing is BillingStatus.CREDITED:
        return fulfilment in TERMINAL_FULFILMENT
    if billing is BillingStatus.UNBILLED:
        return authorized or fulfilment in (FulfilmentStatus.PENDING, FulfilmentStatus.CANCELLED)
    return fulfilment is not FulfilmentStatus.CANCELLED


@dataclass(frozen=True, slots=True)
class LineStatus:
    """Snapshot of a service line's statuses. Construction validates consistency."""

    billing: BillingStatus = BillingStatus.UNBILLED
    fulfilment: FulfilmentStatus = FulfilmentStatus.PENDING
    authorized: bool = False

    def __post_init__(self) -> None:
        if not is_consistent(self.billing, self.fulfilment, self.authorized):
            raise DomainError(
                "INVALID_LINE_STATUS",
                "Inconsistent service line status",
                billing=str(self.billing),
                fulfilment=str(self.fulfilment),
                authorized=self.authorized,
            )

    @property
    def state(self) -> LineState:
        return derived_state(self.billing, self.fulfilment)


def derived_state(billing: BillingStatus, fulfilment: FulfilmentStatus) -> LineState:
    """Display state: cancelled > performed > paid > invoiced > requested."""
    if fulfilment is FulfilmentStatus.CANCELLED:
        return LineState.CANCELLED
    if fulfilment is FulfilmentStatus.PERFORMED:
        return LineState.PERFORMED
    if billing is BillingStatus.SETTLED:
        return LineState.PAID
    if billing is BillingStatus.INVOICED:
        return LineState.INVOICED
    return LineState.REQUESTED


class DoctorStatus(StrEnum):
    """What the ordering doctor sees on a line (FEATURES 3.7): no prices, but progress."""

    REQUESTED = "requested"
    PAID = "paid"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


def doctor_status(
    billing: BillingStatus, fulfilment: FulfilmentStatus, *, authorized: bool = False
) -> DoctorStatus:
    """The doctor's view of a line: cancelled > done > in progress > paid > requested.

    ``paid`` means the department may start (settled, or a perform-first authorization);
    ``in_progress`` keeps the step :func:`derived_state` folds away (sample taken, part of a
    prescription dispensed), so the doctor can tell started work from waiting work.
    """
    if fulfilment is FulfilmentStatus.CANCELLED:
        return DoctorStatus.CANCELLED
    if fulfilment is FulfilmentStatus.PERFORMED:
        return DoctorStatus.DONE
    if fulfilment is FulfilmentStatus.IN_PROGRESS:
        return DoctorStatus.IN_PROGRESS
    if billing is BillingStatus.SETTLED or authorized:
        return DoctorStatus.PAID
    return DoctorStatus.REQUESTED


def can_enter_worklist(status: LineStatus) -> bool:
    """Rule 1: open fulfilment and (settled or perform-first authorized)."""
    return status.fulfilment in ACTIVE_FULFILMENT and (
        status.billing is BillingStatus.SETTLED or status.authorized
    )


def _error(code: str, message: str, status: LineStatus) -> DomainError:
    return DomainError(
        code,
        message,
        billing=str(status.billing),
        fulfilment=str(status.fulfilment),
        authorized=status.authorized,
    )


def _require_open(status: LineStatus, *, cancelled_code: str = "LINE_CANCELLED") -> None:
    if status.fulfilment is FulfilmentStatus.PERFORMED:
        raise _error("LINE_ALREADY_PERFORMED", "The line has already been performed", status)
    if status.fulfilment is FulfilmentStatus.CANCELLED:
        raise _error(cancelled_code, "The line is cancelled", status)


# --- billing edges --------------------------------------------------------------------


def invoice(status: LineStatus, *, patient_due: Decimal) -> LineStatus:
    """Approve the line on an invoice. Zero patient due settles it at once (rule 2).

    Allowed from ``unbilled`` with fulfilment not cancelled (an authorized line that was
    performed first is invoiced afterwards).
    """
    due = require_non_negative(patient_due, "patient_due")
    if status.fulfilment is FulfilmentStatus.CANCELLED:
        raise _error("LINE_CANCELLED", "A cancelled line cannot be invoiced", status)
    if status.billing is not BillingStatus.UNBILLED:
        raise _error("LINE_NOT_BILLABLE", "Only unbilled lines can be invoiced", status)
    billing = BillingStatus.SETTLED if due == 0 else BillingStatus.INVOICED
    return replace(status, billing=billing)


def settle(status: LineStatus) -> LineStatus:
    """The patient outstanding on an invoiced line reached zero."""
    if status.billing is not BillingStatus.INVOICED:
        raise _error("LINE_NOT_PAYABLE", "Only an invoiced line can be settled", status)
    return replace(status, billing=BillingStatus.SETTLED)


def unsettle(status: LineStatus) -> LineStatus:
    """A payment reversal left patient outstanding on a settled line again."""
    if status.billing is not BillingStatus.SETTLED:
        raise _error("LINE_NOT_SETTLED", "Only a settled line can be unsettled", status)
    return replace(status, billing=BillingStatus.INVOICED)


def apply_settlement(status: LineStatus, *, outstanding: Decimal) -> LineStatus:
    """Idempotent sync of ``invoiced``/``settled`` with the line's patient outstanding.

    Lines that are unbilled or credited are returned unchanged.
    """
    remaining = require_non_negative(outstanding, "outstanding")
    if status.billing not in BILLED:
        return status
    billing = BillingStatus.SETTLED if remaining == 0 else BillingStatus.INVOICED
    return replace(status, billing=billing)


def credit(status: LineStatus, approval: Approval, *, fully_credited: bool = True) -> LineStatus:
    """A credit note line was approved against this line.

    A full credit removes the line: billing becomes ``credited`` and an open line is
    cancelled (it can no longer be performed). A performed line stays performed. A partial
    credit (part of the quantity) leaves the statuses unchanged.
    """
    if not isinstance(approval, Approval):
        raise TypeError("credit() needs an Approval")
    if status.billing not in BILLED:
        raise _error(
            "LINE_NOT_CREDITABLE", "Only invoiced or settled lines can be credited", status
        )
    if not fully_credited:
        return status
    fulfilment = (
        FulfilmentStatus.CANCELLED if status.fulfilment in ACTIVE_FULFILMENT else status.fulfilment
    )
    return replace(status, billing=BillingStatus.CREDITED, fulfilment=fulfilment)


# --- fulfilment edges -----------------------------------------------------------------


def can_authorize(status: LineStatus) -> bool:
    """Whether :func:`authorize` accepts the line: open, not settled, not yet authorized.

    Screens show this flag; the rule itself stays in :func:`authorize`, and a test pins the
    two together.
    """
    return (
        status.fulfilment in ACTIVE_FULFILMENT
        and not status.authorized
        and status.billing is not BillingStatus.SETTLED
    )


def authorize(status: LineStatus, approval: Approval) -> LineStatus:
    """Attach a perform-first authorization (FEATURES 4.4) to an open, unpaid line."""
    if not isinstance(approval, Approval):
        raise TypeError("authorize() needs an Approval")
    _require_open(status)
    if status.authorized:
        raise _error("LINE_ALREADY_AUTHORIZED", "The line is already authorized", status)
    if status.billing is BillingStatus.SETTLED:
        raise _error("LINE_ALREADY_SETTLED", "A settled line needs no authorization", status)
    return replace(status, authorized=True)


def start(status: LineStatus) -> LineStatus:
    """``pending`` -> ``in_progress`` (e.g. sample received). Needs eligibility."""
    _require_open(status)
    if status.fulfilment is FulfilmentStatus.IN_PROGRESS:
        raise _error("LINE_ALREADY_STARTED", "The line is already in progress", status)
    if not can_enter_worklist(status):
        raise _error("LINE_NOT_ELIGIBLE", "The line is neither paid nor authorized", status)
    return replace(status, fulfilment=FulfilmentStatus.IN_PROGRESS)


def perform(status: LineStatus) -> LineStatus:
    """Mark the line performed. Needs eligibility (invariant 1)."""
    _require_open(status)
    if not can_enter_worklist(status):
        raise _error("LINE_NOT_ELIGIBLE", "The line is neither paid nor authorized", status)
    return replace(status, fulfilment=FulfilmentStatus.PERFORMED)


def cancel(status: LineStatus, approval: Approval, *, with_credit_note: bool = False) -> LineStatus:
    """Cancel an open line with a reason.

    An unbilled line is simply cancelled. An invoiced or settled line needs a credit note
    (``with_credit_note=True``), which makes it ``credited``; money allocated to it turns
    into patient credit through the invoice position (see :mod:`domain.invoice`).
    """
    if not isinstance(approval, Approval):
        raise TypeError("cancel() needs an Approval")
    _require_open(status, cancelled_code="LINE_ALREADY_CANCELLED")
    if status.billing in BILLED:
        if not with_credit_note:
            raise _error(
                "CREDIT_NOTE_REQUIRED", "Cancelling an invoiced line needs a credit note", status
            )
        return replace(
            status, billing=BillingStatus.CREDITED, fulfilment=FulfilmentStatus.CANCELLED
        )
    return replace(status, fulfilment=FulfilmentStatus.CANCELLED)


def void_in_error(status: LineStatus, approval: Approval) -> LineStatus:
    """Void an unbilled line that was recorded performed under a perform-first authorization
    that was itself made in error (a bed night of an admission made in error, ADR 0018).

    The one exception to "performed is terminal": nothing was billed, so no invoice or
    shift changes (invariants 2 and 3), and the approval records who decided, when and why
    (invariant 4). A billed line is corrected by a credit note; an open line is cancelled.

    Raises:
        DomainError: ``CREDIT_NOTE_REQUIRED`` (invoiced or settled),
            ``LINE_ALREADY_CANCELLED``, ``LINE_NOT_VOIDABLE`` (credited, not performed, or
            performed without an authorization).
    """
    if not isinstance(approval, Approval):
        raise TypeError("void_in_error() needs an Approval")
    if status.billing in BILLED:
        raise _error("CREDIT_NOTE_REQUIRED", "A billed line is corrected by a credit note", status)
    if status.fulfilment is FulfilmentStatus.CANCELLED:
        raise _error("LINE_ALREADY_CANCELLED", "The line is already cancelled", status)
    if (
        status.billing is not BillingStatus.UNBILLED
        or status.fulfilment is not FulfilmentStatus.PERFORMED
        or not status.authorized
    ):
        raise _error(
            "LINE_NOT_VOIDABLE",
            "Only a line performed under a perform-first authorization is voided",
            status,
        )
    return replace(status, fulfilment=FulfilmentStatus.CANCELLED)


def replacement(status: LineStatus, approval: Approval) -> LineStatus:
    """Initial status of a line that re-bills a credited one (a correction).

    A performed original yields an unbilled, performed line authorized by the correction's
    approval (the service was given; it only needs billing). A cancelled original yields a
    fresh requested line.
    """
    if not isinstance(approval, Approval):
        raise TypeError("replacement() needs an Approval")
    if status.billing is not BillingStatus.CREDITED:
        raise _error("LINE_NOT_CREDITED", "Only a credited line can be replaced", status)
    if status.fulfilment is FulfilmentStatus.PERFORMED:
        return LineStatus(BillingStatus.UNBILLED, FulfilmentStatus.PERFORMED, authorized=True)
    return LineStatus()


# --- quantities -----------------------------------------------------------------------


def _units(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DomainError(
            "INVALID_QUANTITY", f"{name} must be a whole number >= 0", **{name: value}
        )
    return value


def open_quantity(ordered: int, *, credited: int = 0, given: int = 0) -> int:
    """Units of a line that may still be performed or dispensed (invariant 1).

    ``ordered`` units are on the line; ``credited`` of them were removed by approved credit
    notes (their money went back to the patient) and ``given`` were already dispensed or
    performed. Credited units are never given, so ``ordered - credited - given`` is left.

    Raises:
        DomainError: ``INVALID_QUANTITY`` for a negative or non-whole input;
            ``CREDIT_EXCEEDS_UNGIVEN`` when credited and given units add up to more than the
            line (a credit took back units the patient already received).
    """
    o, c, g = _units(ordered, "ordered"), _units(credited, "credited"), _units(given, "given")
    if c + g > o:
        raise DomainError(
            "CREDIT_EXCEEDS_UNGIVEN",
            "Credited and given units exceed the line",
            ordered=o,
            credited=c,
            given=g,
        )
    return o - c - g


def remainder_to_credit(ordered: int, *, credited: int = 0, performed: int) -> int:
    """Units to credit when a partly performed line is closed (partial dispense remainder).

    The line keeps ``performed`` units; units an earlier credit note already took back are not
    credited twice. Raises ``LINE_NOTHING_REMAINING`` when nothing is left to credit.
    """
    left = open_quantity(ordered, credited=credited, given=_units(performed, "performed"))
    if left == 0:
        raise DomainError(
            "LINE_NOTHING_REMAINING",
            "Nothing of the line is left to cancel",
            ordered=ordered,
            credited=credited,
            performed=performed,
        )
    return left
