"""Minimal inpatient rules (FEATURES 10.5): cancelling an admission made in error (ADR 0018).

An admission made in error (wrong patient, never admitted, recorded twice) is cancelled with
a reason and a second person's approval (invariant 4). Its bed nights were given under the
admission's perform-first authorization and recorded performed (invariant 1); those still
unbilled are voided with it. A night already on an approved invoice is never touched here:
the invoice is frozen (invariant 2), so the cashier credits it first and the admission is
cancelled afterwards. Credited and already cancelled nights stay as they are.

Error codes: ``ADMISSION_NIGHTS_INVOICED``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from domain.errors import DomainError
from domain.service_line import BILLED, BillingStatus, FulfilmentStatus

__all__ = ["AdmissionCancelPlan", "NightLine", "plan_admission_cancel"]


@dataclass(frozen=True, slots=True)
class NightLine:
    """One bed night line of the admission, as stored."""

    line_id: int
    billing: BillingStatus
    fulfilment: FulfilmentStatus


@dataclass(frozen=True, slots=True)
class AdmissionCancelPlan:
    """The night lines to void (unbilled and performed), in id order."""

    void: tuple[int, ...]


def plan_admission_cancel(nights: Iterable[NightLine]) -> AdmissionCancelPlan:
    """What cancelling the admission does to its bed nights.

    Raises:
        DomainError: ``ADMISSION_NIGHTS_INVOICED`` (with ``line_ids`` and ``count``) when a
            night is invoiced or settled and not yet credited.
    """
    rows = list(nights)
    billed = sorted(n.line_id for n in rows if n.billing in BILLED)
    if billed:
        raise DomainError(
            "ADMISSION_NIGHTS_INVOICED",
            "Some bed nights are invoiced: credit them at the cashier first",
            line_ids=billed,
            count=len(billed),
        )
    return AdmissionCancelPlan(
        void=tuple(
            sorted(
                n.line_id
                for n in rows
                if n.billing is BillingStatus.UNBILLED
                and n.fulfilment is FulfilmentStatus.PERFORMED
            )
        )
    )
