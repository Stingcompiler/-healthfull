"""The cashier desk's billing commands (FLOW step 4, FEATURES 5.3-5.11).

Each command runs one ``apps.billing.services`` (or ``apps.orders.services``) operation and
returns what the screen shows next (``apps.billing.queries``), so a router makes one call.
Rules, locks, ledger postings and audit context stay in the engine services; this module
only resolves the request's references (an invoice line must belong to the invoice in the
path) and the supervisor who approves at the desk (``apps.payments.approvals``, ADR 0007).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from apps.billing import queries
from apps.billing import services as billing
from apps.billing.models import CreditNote, Invoice, InvoiceLine
from apps.catalog.models import Payer
from apps.core.models import User
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.payments.approvals import ApproverLogin, resolve_approver
from apps.visits.models import Visit

__all__ = [
    "approve_credit_note",
    "approve_invoice",
    "cancel_draft_line",
    "create_credit_note",
    "create_invoice",
    "discount_invoice",
    "discount_line",
    "remove_draft_line",
    "set_line_payer",
    "set_preapproval",
    "void_invoice",
]


def _line_of(invoice_id: int, line_id: int) -> InvoiceLine:
    """The invoice line ``line_id`` of invoice ``invoice_id`` (404 when it is another's)."""
    return InvoiceLine.objects.get(pk=line_id, invoice_id=invoice_id)


def create_invoice(visit_id: int, *, actor: User, line_ids: Sequence[int] | None) -> dict[str, Any]:
    """A draft invoice from the visit's unbilled lines (all of them by default)."""
    visit = Visit.objects.get(pk=visit_id)
    invoice = billing.create_draft_invoice(visit, actor, line_ids=line_ids)
    return queries.invoice_detail(invoice.pk)


def remove_draft_line(invoice_id: int, line_id: int, *, actor: User) -> dict[str, Any]:
    """Take a line off a draft; it stays requested and can be invoiced later."""
    billing.remove_draft_line(_line_of(invoice_id, line_id), actor=actor)
    return queries.invoice_detail(invoice_id)


def cancel_draft_line(
    invoice_id: int, line_id: int, *, actor: User, reason: str, note: str
) -> dict[str, Any]:
    """Cancel a draft line's service line with a reason (the patient refuses a test, FLOW 4).

    Only lines of a draft: a billed line is cancelled by a credit note instead.
    """
    billing.cancel_draft_line(_line_of(invoice_id, line_id), reason, actor=actor, note=note)
    return queries.invoice_detail(invoice_id)


def set_preapproval(
    invoice_id: int, line_id: int, *, actor: User, reference: str
) -> dict[str, Any]:
    """Record the payer's pre-approval number on a draft line (FEATURES 5.8)."""
    billing.set_preapproval_ref(_line_of(invoice_id, line_id), reference, actor=actor)
    return queries.invoice_detail(invoice_id)


def set_line_payer(
    service_line_id: int, *, actor: User, payer_id: int | None, note: str
) -> dict[str, Any]:
    """Bill an unbilled line to another payer of the patient, or to cash (FEATURES 5.6)."""
    payer = Payer.objects.get(pk=payer_id) if payer_id is not None else None
    line = orders.set_line_payer(
        ServiceLine.objects.get(pk=service_line_id), payer=payer, actor=actor, note=note
    )
    return queries.visit_billing(line.visit_id)


def discount_line(
    invoice_id: int,
    line_id: int,
    *,
    actor: User,
    reason: str,
    note: str,
    amount: Decimal | None,
    percent: Decimal | None,
    approver: ApproverLogin | None,
) -> dict[str, Any]:
    """Discount one draft line's patient share within the approver's limit (FEATURES 5.9)."""
    chosen = resolve_approver(approver, actor=actor)
    billing.apply_discount(
        _line_of(invoice_id, line_id),
        actor=actor,
        reason=reason,
        amount=amount,
        percent=percent,
        note=note,
        approver=chosen,
    )
    return queries.invoice_detail(invoice_id)


def discount_invoice(
    invoice_id: int,
    *,
    actor: User,
    reason: str,
    note: str,
    amount: Decimal | None,
    percent: Decimal | None,
    approver: ApproverLogin | None,
) -> dict[str, Any]:
    """Spread one discount over a draft's lines in proportion to their patient shares."""
    chosen = resolve_approver(approver, actor=actor)
    billing.apply_invoice_discount(
        Invoice.objects.get(pk=invoice_id),
        actor=actor,
        reason=reason,
        amount=amount,
        percent=percent,
        note=note,
        approver=chosen,
    )
    return queries.invoice_detail(invoice_id)


def approve_invoice(invoice_id: int, *, actor: User) -> dict[str, Any]:
    """Freeze, number and post a draft (invariants 2 and 6)."""
    billing.approve_invoice(Invoice.objects.get(pk=invoice_id), actor=actor)
    return queries.invoice_detail(invoice_id)


def void_invoice(invoice_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """Void a draft with a reason (its lines stay requested)."""
    billing.void_draft(Invoice.objects.get(pk=invoice_id), actor=actor, note=note)
    return queries.invoice_detail(invoice_id)


def create_credit_note(
    invoice_id: int,
    *,
    actor: User,
    lines: Sequence[tuple[int, int]],
    reason: str,
    note: str,
) -> dict[str, Any]:
    """A draft credit note of whole units of approved invoice lines (FEATURES 5.11)."""
    cn = billing.create_credit_note(
        Invoice.objects.get(pk=invoice_id),
        [(line_id, qty) for line_id, qty in lines],
        actor=actor,
        reason=reason,
        note=note,
    )
    return queries.credit_note_detail(cn.pk)


def approve_credit_note(
    credit_note_id: int, *, actor: User, rebill: bool, open_refund: bool
) -> dict[str, Any]:
    """Approve a draft credit note; its released patient money may open a refund request.

    The refund request is opened in the approver's own name (ADR 0007): the approver is the
    person who asked for the money to go back, so invariant 4 names them, and a different
    holder of ``payments.approve_refund`` must approve the refund (SELF_APPROVAL_NOT_ALLOWED).
    One person never decides both the credit and the cash leaving the drawer.
    """
    cn = CreditNote.objects.get(pk=credit_note_id)
    outcome = billing.approve_credit_note(
        cn,
        actor=actor,
        rebill=rebill,
        open_refund=open_refund,
        refund_requested_by=actor,
    )
    return queries.credit_outcome_json(outcome)
