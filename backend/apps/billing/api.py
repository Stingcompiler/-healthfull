"""``/api/billing``: the cashier's lookup, invoices, discounts and credit notes.

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, schema in/out and
one call into ``apps.billing.queries`` (reads) or ``apps.billing.desk`` (commands). Rules live
in ``domain`` and ``apps.billing.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Status
from ninja.errors import AuthenticationError

from api.pagination import PageParams
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.billing import desk, queries
from apps.billing.schemas import (
    BillingReasonOut,
    CreditNoteApproveIn,
    CreditNoteIn,
    CreditNoteOut,
    CreditOutcomeOut,
    DiscountIn,
    DocStatus,
    InvoiceCreateIn,
    InvoiceOut,
    InvoicePrintOut,
    LineCancelIn,
    LinePayerIn,
    LookupOut,
    PreApprovalIn,
    ReasonCategoryCode,
    ServiceLineOut,
    VisitBillingOut,
    VoidIn,
)
from apps.core.models import User
from apps.payments.approvals import ApproverLogin
from domain.money import money

billing_router = Router(tags=["billing"])
add_ping(billing_router, "billing")

_READ = {**ERROR_RESPONSES, 404: ErrorOut}


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


def _amount(value: str | None) -> Any:
    return None if value is None else money(value)


def _approver(request: HttpRequest, payload: DiscountIn) -> ApproverLogin | None:
    if payload.approver is None:
        return None
    return ApproverLogin(request, payload.approver.username, payload.approver.password)


# --- lookup and visits -----------------------------------------------------------------------


@billing_router.get(
    "/lookup",
    response={200: LookupOut, **_READ},
    operation_id="billing_lookup_patients",
    summary="Find patients and their billable visits by file number, visit number, phone or name",
)
@require_perm("billing.view")
def lookup(request: HttpRequest, q: str = Query(..., min_length=1, max_length=200)) -> Any:
    return queries.lookup(q)


@billing_router.get(
    "/visits/{visit_id}",
    response={200: VisitBillingOut, **_READ},
    operation_id="billing_get_visit_billing",
    summary="A visit's unbilled lines, invoices, payers and the patient's balance",
)
@require_perm("billing.view")
def visit_billing(request: HttpRequest, visit_id: int) -> Any:
    return queries.visit_billing(visit_id)


@billing_router.get(
    "/visits/{visit_id}/unbilled-lines",
    response={200: list[ServiceLineOut], **_READ},
    operation_id="billing_list_unbilled_lines",
    summary="The visit's requested lines that can be invoiced",
)
@require_perm("billing.view")
def unbilled_lines(request: HttpRequest, visit_id: int) -> Any:
    return queries.unbilled(visit_id)


@billing_router.post(
    "/lines/{service_line_id}/payer",
    response={200: VisitBillingOut, **_READ},
    operation_id="billing_set_line_payer",
    summary="Bill an unbilled line to another payer of the patient, or to cash",
)
@require_perm("billing.create_invoice")
def set_line_payer(request: HttpRequest, service_line_id: int, payload: LinePayerIn) -> Any:
    return desk.set_line_payer(
        service_line_id, actor=_user(request), payer_id=payload.payer_id, note=payload.note
    )


@billing_router.get(
    "/reasons",
    response={200: list[BillingReasonOut], **_READ},
    operation_id="billing_list_reasons",
    summary="Active reasons of one cashier list (discount, credit note, variance, ...)",
)
@require_perm("billing.view")
def reasons(request: HttpRequest, category: ReasonCategoryCode) -> Any:
    return queries.reasons(category)


# --- invoices --------------------------------------------------------------------------------


@billing_router.post(
    "/invoices",
    response={201: InvoiceOut, **_READ},
    operation_id="billing_create_invoice",
    summary="Draft an invoice from the visit's unbilled lines",
)
@require_perm("billing.create_invoice")
def create_invoice(request: HttpRequest, payload: InvoiceCreateIn) -> Any:
    return Status(
        201, desk.create_invoice(payload.visit_id, actor=_user(request), line_ids=payload.line_ids)
    )


@billing_router.get(
    "/invoices/{invoice_id}",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_get_invoice",
    summary="One invoice with lines, coverage split, payments and credit notes",
)
@require_perm("billing.view")
def get_invoice(request: HttpRequest, invoice_id: int) -> Any:
    return queries.invoice_detail(invoice_id)


@billing_router.get(
    "/invoices/{invoice_id}/print",
    response={200: InvoicePrintOut, **_READ},
    operation_id="billing_get_invoice_print",
    summary="An invoice with the center header, for A4 or 80 mm printing",
)
@require_perm("billing.view")
def print_invoice(request: HttpRequest, invoice_id: int) -> Any:
    return queries.invoice_print(invoice_id)


@billing_router.delete(
    "/invoices/{invoice_id}/lines/{line_id}",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_remove_draft_line",
    summary="Take a line off a draft (it stays requested)",
)
@require_perm("billing.create_invoice")
def remove_line(request: HttpRequest, invoice_id: int, line_id: int) -> Any:
    return desk.remove_draft_line(invoice_id, line_id, actor=_user(request))


@billing_router.post(
    "/invoices/{invoice_id}/lines/{line_id}/cancel",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_cancel_draft_line",
    summary="Cancel a draft line's service with a reason (e.g. the patient refused it)",
    description=(
        "Needs billing.create_invoice (the router) and orders.cancel_line (the service): "
        "roles outside the cashier's desk never see the invoice this returns."
    ),
)
@require_perm("billing.create_invoice")
def cancel_line(request: HttpRequest, invoice_id: int, line_id: int, payload: LineCancelIn) -> Any:
    return desk.cancel_draft_line(
        invoice_id, line_id, actor=_user(request), reason=payload.reason, note=payload.note
    )


@billing_router.post(
    "/invoices/{invoice_id}/lines/{line_id}/pre-approval",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_set_preapproval_ref",
    summary="Record the payer's pre-approval reference on a draft line",
)
@require_perm("billing.create_invoice")
def set_preapproval(
    request: HttpRequest, invoice_id: int, line_id: int, payload: PreApprovalIn
) -> Any:
    return desk.set_preapproval(
        invoice_id, line_id, actor=_user(request), reference=payload.reference
    )


@billing_router.post(
    "/invoices/{invoice_id}/lines/{line_id}/discount",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_discount_line",
    summary="Discount one draft line's patient share (reason; supervisor above the limit)",
    description=(
        "Give `amount` or `percent`. Above the cashier's role limit a supervisor holding "
        "billing.override_discount_limit approves by typing their credentials into `approver` "
        "(409 APPROVER_INVALID on wrong credentials). A zero amount removes the discount."
    ),
)
@require_perm("billing.apply_discount")
def discount_line(request: HttpRequest, invoice_id: int, line_id: int, payload: DiscountIn) -> Any:
    return desk.discount_line(
        invoice_id,
        line_id,
        actor=_user(request),
        reason=payload.reason,
        note=payload.note,
        amount=_amount(payload.amount),
        percent=_amount(payload.percent),
        approver=_approver(request, payload),
    )


@billing_router.post(
    "/invoices/{invoice_id}/discount",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_discount_invoice",
    summary="Spread one discount over a draft's lines by patient share",
)
@require_perm("billing.apply_discount")
def discount_invoice(request: HttpRequest, invoice_id: int, payload: DiscountIn) -> Any:
    return desk.discount_invoice(
        invoice_id,
        actor=_user(request),
        reason=payload.reason,
        note=payload.note,
        amount=_amount(payload.amount),
        percent=_amount(payload.percent),
        approver=_approver(request, payload),
    )


@billing_router.post(
    "/invoices/{invoice_id}/approve",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_approve_invoice",
    summary="Approve a draft: prices freeze from today's list and the invoice is numbered",
)
@require_perm("billing.approve_invoice")
def approve_invoice(request: HttpRequest, invoice_id: int) -> Any:
    return desk.approve_invoice(invoice_id, actor=_user(request))


@billing_router.post(
    "/invoices/{invoice_id}/void",
    response={200: InvoiceOut, **_READ},
    operation_id="billing_void_invoice",
    summary="Void a draft invoice with a reason",
)
@require_perm("billing.void_draft")
def void_invoice(request: HttpRequest, invoice_id: int, payload: VoidIn) -> Any:
    return desk.void_invoice(invoice_id, actor=_user(request), note=payload.note)


# --- credit notes ----------------------------------------------------------------------------


@billing_router.post(
    "/invoices/{invoice_id}/credit-notes",
    response={201: CreditNoteOut, **_READ},
    operation_id="billing_create_credit_note",
    summary="Draft a credit note of whole units of approved invoice lines",
)
@require_perm("billing.create_credit_note")
def create_credit_note(request: HttpRequest, invoice_id: int, payload: CreditNoteIn) -> Any:
    return Status(
        201,
        desk.create_credit_note(
            invoice_id,
            actor=_user(request),
            lines=[(ln.invoice_line_id, ln.quantity) for ln in payload.lines],
            reason=payload.reason,
            note=payload.note,
        ),
    )


@billing_router.get(
    "/credit-notes",
    response={200: Page[CreditNoteOut], **_READ},
    operation_id="billing_list_credit_notes",
    summary="Credit notes, newest first (status=draft: the approval queue)",
)
@require_perm("billing.view")
def list_credit_notes(
    request: HttpRequest,
    params: Query[PageParams],
    status: DocStatus | None = None,
    invoice_id: int | None = None,
) -> Any:
    return queries.credit_notes(
        status=status,
        invoice_id=invoice_id,
        q=params.q,
        page=params.page,
        page_size=params.page_size,
    )


@billing_router.get(
    "/credit-notes/{credit_note_id}",
    response={200: CreditNoteOut, **_READ},
    operation_id="billing_get_credit_note",
    summary="One credit note with its lines and refunds",
)
@require_perm("billing.view")
def get_credit_note(request: HttpRequest, credit_note_id: int) -> Any:
    return queries.credit_note_detail(credit_note_id)


@billing_router.post(
    "/credit-notes/{credit_note_id}/approve",
    response={200: CreditOutcomeOut, **_READ},
    operation_id="billing_approve_credit_note",
    summary="Approve a credit note (supervisor); released money may open a refund request",
)
@require_perm("billing.approve_credit_note")
def approve_credit_note(
    request: HttpRequest, credit_note_id: int, payload: CreditNoteApproveIn
) -> Any:
    return desk.approve_credit_note(
        credit_note_id,
        actor=_user(request),
        rebill=payload.rebill,
        open_refund=payload.open_refund,
    )
