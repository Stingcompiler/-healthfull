"""Invoices, credit notes and the patient position of an invoice (ARCHITECTURE 4.5, 4.6).

* Lines come only from the visit's unbilled service lines; there are no free-amount lines.
* At approval each line freezes the unit price of the price-list version effective that day
  (invariant 6), the quantity, gross, discount, payer and the payer/patient split
  (:mod:`domain.coverage`). An approved invoice never changes (invariant 2).
* Corrections are credit note lines linked to the original line. A credit line credits a
  number of units of one invoice line. Partial credits use cumulative rounding so that each
  component of the credits is non-negative, never exceeds the original, and the credits of
  the whole quantity add up to the original exactly.
* :func:`invoice_position` derives, from the immutable documents (lines, credit lines,
  rebills of rejected payer share, signed allocations), each line's patient due, paid and
  outstanding amounts. Money allocated to the invoice is applied to lines in line order; a
  line is settled when it is not fully credited and its outstanding is zero. Money above
  the invoice's due is the over-allocation that must be de-allocated into patient credit.
* When a credit note takes back (part of) a line that held patient money, that money becomes
  patient credit (ARCHITECTURE 4.4 rule 3): :func:`credit_release` measures it, so that the
  money does not drift onto the invoice's other lines.

Error codes: ``INVOICE_NOT_DRAFT``, ``INVOICE_FROZEN``, ``INVOICE_EMPTY``,
``DUPLICATE_LINE``, ``INVALID_QUANTITY``, ``COVERAGE_WITHOUT_PAYER``,
``INVALID_INVOICE_LINE``, ``UNKNOWN_INVOICE_LINE``, ``CREDIT_EXCEEDS_LINE``,
``REBILL_EXCEEDS_PAYER_SHARE``, ``ALLOCATION_NEGATIVE``, plus those of
:mod:`domain.service_line`, :mod:`domain.pricing` and :mod:`domain.coverage`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum

from domain.audit import Approval
from domain.coverage import CoverageRule, check_preapproval, split_line
from domain.errors import DomainError
from domain.money import ZERO, q, require_money, require_non_negative
from domain.pricing import ItemKey, PriceVersion, effective_version, unit_price
from domain.service_line import LineStatus
from domain.service_line import invoice as invoice_service_line

__all__ = [
    "BillableLine",
    "CreditLineDraft",
    "InvoiceLineDraft",
    "InvoicePosition",
    "InvoiceStatus",
    "InvoiceTotals",
    "LinePosition",
    "Rebill",
    "approve",
    "build_credit_line",
    "build_invoice_lines",
    "credit_release",
    "credited_quantity",
    "invoice_position",
    "invoice_totals",
    "payer_totals",
    "require_editable",
    "void",
]


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    VOID = "void"


def approve(status: InvoiceStatus) -> InvoiceStatus:
    """``draft`` -> ``approved`` (credit notes follow the same edge)."""
    if status is not InvoiceStatus.DRAFT:
        raise DomainError("INVOICE_NOT_DRAFT", "Only a draft can be approved", status=str(status))
    return InvoiceStatus.APPROVED


def void(status: InvoiceStatus, approval: Approval) -> InvoiceStatus:
    """``draft`` -> ``void``. Approved documents are corrected by credit notes instead."""
    if not isinstance(approval, Approval):
        raise TypeError("void() needs an Approval")
    require_editable(status)
    if status is not InvoiceStatus.DRAFT:
        raise DomainError("INVOICE_NOT_DRAFT", "Only a draft can be voided", status=str(status))
    return InvoiceStatus.VOID


def require_editable(status: InvoiceStatus) -> None:
    """Refuse any change to an approved document (invariant 2)."""
    if status is InvoiceStatus.APPROVED:
        raise DomainError("INVOICE_FROZEN", "An approved document cannot change")


# --- lines -------------------------------------------------------------------------------


def _quantity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DomainError(
            "INVALID_QUANTITY", "Quantity must be a whole number >= 1", quantity=value
        )
    return value


@dataclass(frozen=True, slots=True)
class BillableLine:
    """A service line offered for invoicing, with what is needed to freeze it.

    ``price_versions`` are the versions of the price list that applies to the line (the
    payer's list, or the cash list). ``discount`` is an amount on the patient side, already
    checked against the approver's limit with :func:`domain.coverage.check_discount`.
    """

    service_line_id: int
    item: ItemKey
    quantity: int
    status: LineStatus
    price_versions: Sequence[PriceVersion]
    payer_id: int | None = None
    coverage: CoverageRule | None = None
    excluded: bool = False
    discount: Decimal = ZERO
    preapproval_ref: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceLineDraft:
    """A frozen invoice line. ``gross == discount + payer_share + patient_share``."""

    position: int
    service_line_id: int
    item: ItemKey
    quantity: int
    unit_price: Decimal
    price_version_id: int
    gross: Decimal
    discount: Decimal
    payer_id: int | None
    payer_share: Decimal
    patient_share: Decimal
    preapproval_ref: str | None = None

    def __post_init__(self) -> None:
        _quantity(self.quantity)
        for name in ("unit_price", "gross", "discount", "payer_share", "patient_share"):
            require_non_negative(getattr(self, name), name)
        if (
            self.gross != self.discount + self.payer_share + self.patient_share
            or self.gross != self.unit_price * self.quantity
            or (self.payer_id is None and self.payer_share != 0)
        ):
            raise DomainError(
                "INVALID_INVOICE_LINE",
                "Invoice line amounts are inconsistent",
                position=self.position,
            )


def build_invoice_lines(lines: Sequence[BillableLine], on: date) -> tuple[InvoiceLineDraft, ...]:
    """Freeze billable service lines into invoice lines priced as of ``on``.

    Positions are 1-based in the given order (the order money is applied in).
    """
    if not lines:
        raise DomainError("INVOICE_EMPTY", "An invoice needs at least one line")
    seen: set[int] = set()
    out: list[InvoiceLineDraft] = []
    for position, line in enumerate(lines, start=1):
        if line.service_line_id in seen:
            raise DomainError(
                "DUPLICATE_LINE",
                "A service line appears twice",
                service_line_id=line.service_line_id,
            )
        seen.add(line.service_line_id)
        quantity = _quantity(line.quantity)
        if line.coverage is not None and line.payer_id is None:
            raise DomainError(
                "COVERAGE_WITHOUT_PAYER",
                "A coverage rule needs a payer",
                service_line_id=line.service_line_id,
            )
        ref = check_preapproval(line.coverage, line.preapproval_ref, excluded=line.excluded)
        version = effective_version(line.price_versions, on)
        price = unit_price(line.price_versions, line.item, on)
        split = split_line(price * quantity, line.discount, line.coverage, excluded=line.excluded)
        # Validates the service-line edge (unbilled, not cancelled) before anything is frozen.
        invoice_service_line(line.status, patient_due=split.patient_share)
        out.append(
            InvoiceLineDraft(
                position=position,
                service_line_id=line.service_line_id,
                item=line.item,
                quantity=quantity,
                unit_price=price,
                price_version_id=version.version_id,
                gross=split.gross,
                discount=split.discount,
                payer_id=line.payer_id,
                payer_share=split.payer_share,
                patient_share=split.patient_share,
                preapproval_ref=ref,
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class InvoiceTotals:
    gross: Decimal
    discount: Decimal
    payer_share: Decimal
    patient_share: Decimal


def invoice_totals(lines: Iterable[InvoiceLineDraft | CreditLineDraft]) -> InvoiceTotals:
    """Exact sums of the line components (works for invoice and credit note lines)."""
    gross = discount = payer = patient = ZERO
    for ln in lines:
        gross += ln.gross
        discount += ln.discount
        payer += ln.payer_share
        patient += ln.patient_share
    return InvoiceTotals(gross=gross, discount=discount, payer_share=payer, patient_share=patient)


def payer_totals(lines: Iterable[InvoiceLineDraft | CreditLineDraft]) -> dict[int, Decimal]:
    """Payer share per payer id (only payers with a non-zero share)."""
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        if ln.payer_id is not None and ln.payer_share:
            out[ln.payer_id] += ln.payer_share
    return dict(out)


# --- credit notes ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreditLineDraft:
    """Credit of ``quantity`` units of the invoice line at ``position``."""

    position: int
    quantity: int
    gross: Decimal
    discount: Decimal
    payer_id: int | None
    payer_share: Decimal
    patient_share: Decimal

    def __post_init__(self) -> None:
        _quantity(self.quantity)
        for name in ("gross", "discount", "payer_share", "patient_share"):
            require_non_negative(getattr(self, name), name)
        if self.gross != self.discount + self.payer_share + self.patient_share:
            raise DomainError(
                "INVALID_INVOICE_LINE",
                "Credit line amounts are inconsistent",
                position=self.position,
            )


def credited_quantity(position: int, credit_lines: Iterable[CreditLineDraft]) -> int:
    """Units of the line at ``position`` already credited."""
    return sum(c.quantity for c in credit_lines if c.position == position)


def _portion(amount: Decimal, units: int, of: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return q(amount * units / of)


def build_credit_line(
    line: InvoiceLineDraft, quantity: int, existing: Iterable[CreditLineDraft] = ()
) -> CreditLineDraft:
    """Credit ``quantity`` more units of ``line`` given its ``existing`` credit lines.

    Each component is ``portion(after) - portion(before)`` where ``portion`` rounds the
    component's cumulative share half-up; the gross is the sum of the components.
    """
    qty = _quantity(quantity)
    before = credited_quantity(line.position, existing)
    after = before + qty
    if after > line.quantity:
        raise DomainError(
            "CREDIT_EXCEEDS_LINE",
            "Cannot credit more units than the line has left",
            position=line.position,
            remaining=line.quantity - before,
            requested=qty,
        )

    def part(amount: Decimal) -> Decimal:
        return _portion(amount, after, line.quantity) - _portion(amount, before, line.quantity)

    discount = part(line.discount)
    payer = part(line.payer_share)
    patient = part(line.patient_share)
    return CreditLineDraft(
        position=line.position,
        quantity=qty,
        gross=discount + payer + patient,
        discount=discount,
        payer_id=line.payer_id,
        payer_share=payer,
        patient_share=patient,
    )


# --- position --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rebill:
    """Rejected payer share moved onto the patient for the line at ``position``."""

    position: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class LinePosition:
    position: int
    service_line_id: int
    patient_share: Decimal
    credited_patient: Decimal
    rebilled: Decimal
    patient_due: Decimal
    patient_paid: Decimal
    outstanding: Decimal
    fully_credited: bool
    settled: bool


@dataclass(frozen=True, slots=True)
class InvoicePosition:
    lines: tuple[LinePosition, ...]
    patient_due: Decimal
    allocated: Decimal
    applied: Decimal
    outstanding: Decimal
    over_allocation: Decimal

    @property
    def settled_positions(self) -> frozenset[int]:
        return frozenset(lp.position for lp in self.lines if lp.settled)

    def line(self, position: int) -> LinePosition:
        for lp in self.lines:
            if lp.position == position:
                return lp
        raise DomainError("UNKNOWN_INVOICE_LINE", "No such invoice line", position=position)


def invoice_position(
    lines: Sequence[InvoiceLineDraft],
    credit_lines: Iterable[CreditLineDraft] = (),
    allocations: Iterable[Decimal] = (),
    rebills: Iterable[Rebill] = (),
) -> InvoicePosition:
    """Patient position of one approved invoice from its documents.

    Args:
        lines: The invoice lines.
        credit_lines: Credit note lines against this invoice (approved notes only).
        allocations: Signed allocation amounts to this invoice (reversals are negative).
        rebills: Payer share moved to the patient after a payer rejection.
    """
    by_pos = {ln.position: ln for ln in lines}
    if len(by_pos) != len(lines):
        raise DomainError("DUPLICATE_LINE", "Invoice line positions must be unique")

    credited: dict[int, list[CreditLineDraft]] = defaultdict(list)
    for c in credit_lines:
        if c.position not in by_pos:
            raise DomainError(
                "UNKNOWN_INVOICE_LINE", "Credit for an unknown line", position=c.position
            )
        credited[c.position].append(c)
    rebilled: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for r in rebills:
        if r.position not in by_pos:
            raise DomainError(
                "UNKNOWN_INVOICE_LINE", "Rebill for an unknown line", position=r.position
            )
        rebilled[r.position] += require_non_negative(r.amount, "rebill")

    allocated = ZERO
    for a in allocations:
        allocated += require_money(a, "allocation")
    if allocated < 0:
        raise DomainError(
            "ALLOCATION_NEGATIVE",
            "Allocations to an invoice cannot net below zero",
            net=str(allocated),
        )

    remaining = allocated
    out: list[LinePosition] = []
    total_due = ZERO
    for pos in sorted(by_pos):
        ln = by_pos[pos]
        cs = credited[pos]
        totals = invoice_totals(cs)
        qty = sum(c.quantity for c in cs)
        if (
            qty > ln.quantity
            or totals.gross > ln.gross
            or totals.discount > ln.discount
            or totals.payer_share > ln.payer_share
            or totals.patient_share > ln.patient_share
        ):
            raise DomainError(
                "CREDIT_EXCEEDS_LINE", "Credits exceed the invoice line", position=pos
            )
        if rebilled[pos] > ln.payer_share - totals.payer_share:
            raise DomainError(
                "REBILL_EXCEEDS_PAYER_SHARE",
                "Cannot move more than the remaining payer share to the patient",
                position=pos,
            )
        due = ln.patient_share - totals.patient_share + rebilled[pos]
        paid = min(remaining, due)
        remaining -= paid
        total_due += due
        fully_credited = qty == ln.quantity
        out.append(
            LinePosition(
                position=pos,
                service_line_id=ln.service_line_id,
                patient_share=ln.patient_share,
                credited_patient=totals.patient_share,
                rebilled=rebilled[pos],
                patient_due=due,
                patient_paid=paid,
                outstanding=due - paid,
                fully_credited=fully_credited,
                settled=not fully_credited and due == paid,
            )
        )
    applied = allocated - remaining
    return InvoicePosition(
        lines=tuple(out),
        patient_due=total_due,
        allocated=allocated,
        applied=applied,
        outstanding=total_due - applied,
        over_allocation=remaining,
    )


def credit_release(before: InvoicePosition, after: InvoicePosition) -> Decimal:
    """Patient money a credit note frees: what credited lines held above their new due.

    ``before`` and ``after`` are positions of the same invoice with the same allocations,
    before and after the credit. A line keeps at most its new due of what it held; the rest
    must leave the invoice as patient credit (ARCHITECTURE 4.4 rule 3). De-allocating exactly
    this amount leaves every other line's paid amount (and so its settlement) unchanged.

    Raises ``UNKNOWN_INVOICE_LINE`` when the positions do not have the same lines.
    """
    if {lp.position for lp in before.lines} != {lp.position for lp in after.lines}:
        raise DomainError("UNKNOWN_INVOICE_LINE", "The positions are of different invoices")
    released = ZERO
    for old in before.lines:
        new = after.line(old.position)
        if old.patient_paid > new.patient_due:
            released += old.patient_paid - new.patient_due
    return released
