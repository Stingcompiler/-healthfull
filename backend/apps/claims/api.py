"""``/api/claims``: payer receivables, claim batches, payer responses, rejection handling,
payer payments and aging (FEATURES 11.2-11.7, FLOW step 10).

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, schema in/out and
one call into ``apps.claims.queries`` (reads), ``apps.claims.desk`` (commands) or
``apps.claims.export`` (the Excel file). Rules live in ``domain.claims`` and
``apps.claims.services``. Every code is a ``claims.*`` permission: the accountant owns claims
(managers read them); cashiers and doctors hold none (invariant 7 stays with the accountant).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from django.http import HttpRequest, HttpResponse
from ninja import Field, Query, Router, Schema, Status
from ninja.errors import AuthenticationError

from api.pagination import PageParams
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.billing.schemas import ApproverIn
from apps.claims import desk, export, queries
from apps.claims.schemas import (
    ClaimAccruedOut,
    ClaimAgingReportOut,
    ClaimBuildIn,
    ClaimDetailOut,
    ClaimNoteIn,
    ClaimOptionsOut,
    ClaimPayableOut,
    ClaimPayerPaymentIn,
    ClaimPayerPaymentOut,
    ClaimPrintOut,
    ClaimReceivablesOut,
    ClaimResolveIn,
    ClaimResponsesIn,
    ClaimShortfallIn,
    ClaimStatusCode,
    ClaimSummaryOut,
    ClaimVoidIn,
)
from apps.core.models import User
from apps.payments.approvals import ApproverLogin
from domain.money import money

claims_router = Router(tags=["claims"])
add_ping(claims_router, "claims")

_READ = {**ERROR_RESPONSES, 404: ErrorOut}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


def _approver(request: HttpRequest, approver: ApproverIn | None) -> ApproverLogin | None:
    if approver is None:
        return None
    return ApproverLogin(request, approver.username, approver.password)


class ClaimAsOfParams(Schema):
    as_of: date | None = Field(None, description="Age receivables on this day (default today).")


class ClaimAccruedParams(Schema):
    payer_id: int
    period_start: date | None = None
    period_end: date | None = None


class ClaimListParams(PageParams):
    payer_id: int | None = None
    status: ClaimStatusCode | None = None


class ClaimPaymentListParams(PageParams):
    payer_id: int | None = None
    standing: Literal["cheque_pending", "reversed"] | None = None


class ClaimExportParams(Schema):
    language: Literal["ar", "en"] = "en"


# --- reference data, receivables and aging ---------------------------------------------------


@claims_router.get(
    "/options",
    response={200: ClaimOptionsOut, **_READ},
    operation_id="claims_get_options",
    summary="Payers, banks, write-off reasons and the viewer's open shift",
)
@require_perm("claims.view")
def get_options(request: HttpRequest) -> Any:
    return queries.options(_user(request))


@claims_router.get(
    "/receivables",
    response={200: ClaimReceivablesOut, **_READ},
    operation_id="claims_list_receivables",
    summary="Payer receivables by stage: accrued, claimed, accepted unpaid, rejected, collected",
    description="Payer share is a receivable until a payer payment is recorded (invariant 7).",
)
@require_perm("claims.view")
def list_receivables(request: HttpRequest, params: Query[ClaimAsOfParams]) -> Any:
    return queries.receivables(params.as_of)


@claims_router.get(
    "/aging",
    response={200: ClaimAgingReportOut, **_READ},
    operation_id="claims_get_aging",
    summary="Outstanding payer receivable per payer: 0-30, 31-60, 61-90 and over 90 days",
)
@require_perm("claims.view")
def get_aging(request: HttpRequest, params: Query[ClaimAsOfParams]) -> Any:
    return queries.aging(params.as_of)


@claims_router.get(
    "/accrued",
    response={200: ClaimAccruedOut, **_READ},
    operation_id="claims_list_accrued_lines",
    summary="A payer's unclaimed shares of approved invoices, by approval date",
)
@require_perm("claims.view")
def list_accrued(request: HttpRequest, params: Query[ClaimAccruedParams]) -> Any:
    return queries.accrued(params.payer_id, params.period_start, params.period_end)


# --- claim batches ---------------------------------------------------------------------------


@claims_router.get(
    "/batches",
    response={200: Page[ClaimSummaryOut], **_READ},
    operation_id="claims_list_claims",
    summary="Claim batches, newest first, with their collection totals",
)
@require_perm("claims.view")
def list_claims(request: HttpRequest, params: Query[ClaimListParams]) -> Any:
    return queries.claims_page(
        payer_id=params.payer_id,
        status=params.status,
        page=params.page,
        page_size=params.page_size,
    )


@claims_router.post(
    "/batches",
    response={201: ClaimDetailOut, **_READ},
    operation_id="claims_build_claim",
    summary="Build a draft claim of a payer's accrued shares in a period (all or chosen lines)",
    description="409 INVALID_DATE_RANGE, CLAIM_EMPTY, CLAIM_LINE_NOT_ACCRUED.",
)
@require_perm("claims.manage")
def build_claim(request: HttpRequest, payload: ClaimBuildIn) -> Any:
    return Status(
        201,
        desk.build_claim(
            payer_id=payload.payer_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            invoice_line_ids=payload.invoice_line_ids,
            note=payload.note,
            actor=_user(request),
        ),
    )


@claims_router.get(
    "/batches/{claim_id}",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_get_claim",
    summary="One claim batch with its lines, answers, resolutions and payments",
)
@require_perm("claims.view")
def get_claim(request: HttpRequest, claim_id: int) -> Any:
    return queries.claim_detail(claim_id)


@claims_router.delete(
    "/batches/{claim_id}/lines/{line_id}",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_remove_claim_line",
    summary="Take a line off a draft claim (its payer share is claimable again)",
)
@require_perm("claims.manage")
def remove_line(request: HttpRequest, claim_id: int, line_id: int) -> Any:
    return desk.remove_line(claim_id, line_id, actor=_user(request))


@claims_router.post(
    "/batches/{claim_id}/submit",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_submit_claim",
    summary="Mark a draft claim as sent to the payer",
)
@require_perm("claims.manage")
def submit_claim(request: HttpRequest, claim_id: int) -> Any:
    return desk.submit_claim(claim_id, actor=_user(request))


@claims_router.post(
    "/batches/{claim_id}/void",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_void_claim",
    summary="Void a claim the payer has not answered (its lines are claimable again)",
)
@require_perm("claims.manage")
def void_claim(request: HttpRequest, claim_id: int, payload: ClaimVoidIn) -> Any:
    return desk.void_claim(claim_id, actor=_user(request), note=payload.note)


@claims_router.post(
    "/batches/{claim_id}/close",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_close_claim",
    summary="Close a claim once every line is paid or resolved",
)
@require_perm("claims.manage")
def close_claim(request: HttpRequest, claim_id: int) -> Any:
    return desk.close_claim(claim_id, actor=_user(request))


@claims_router.get(
    "/batches/{claim_id}/export",
    response={200: None, **_READ},
    operation_id="claims_export_claim",
    summary="The claim as an Excel workbook in the payer layout (.xlsx attachment)",
)
@require_perm("claims.manage")
def export_claim(
    request: HttpRequest, claim_id: int, params: Query[ClaimExportParams]
) -> HttpResponse:
    name, content = export.claim_workbook(claim_id, params.language)
    response = HttpResponse(content, content_type=_XLSX)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@claims_router.get(
    "/batches/{claim_id}/print",
    response={200: ClaimPrintOut, **_READ},
    operation_id="claims_get_claim_print",
    summary="The claim addressed to its payer, with the center header, for A4 printing",
)
@require_perm("claims.manage")
def print_claim(request: HttpRequest, claim_id: int) -> Any:
    return queries.claim_print(claim_id)


@claims_router.post(
    "/batches/{claim_id}/responses",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_record_responses",
    summary="Record the payer's answer per line: accepted, rejected or partial, with reason",
    description=(
        "409 CLAIM_STATUS_INVALID, CLAIM_LINE_UNKNOWN, CLAIM_LINE_NOT_CLAIMED, "
        "CLAIM_AMOUNT_INVALID, REASON_REQUIRED, DUPLICATE_LINE."
    ),
)
@require_perm("claims.record_response")
def record_responses(request: HttpRequest, claim_id: int, payload: ClaimResponsesIn) -> Any:
    answers = [
        {
            "claim_line_id": r.claim_line_id,
            "outcome": r.outcome,
            "accepted": None if r.accepted is None else money(r.accepted),
            "reason": r.reason,
            "reference": r.reference,
        }
        for r in payload.responses
    ]
    return desk.record_responses(claim_id, answers, actor=_user(request))


@claims_router.post(
    "/batches/{claim_id}/lines/{line_id}/resolve",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_resolve_rejection",
    summary="Rebill a rejected amount to the patient or write it off, with a reason",
    description=(
        "409 CLAIM_NOTHING_REJECTED, REASON_REQUIRED, REASON_UNKNOWN, "
        "SECOND_APPROVER_REQUIRED, APPROVER_NOT_PERMITTED, APPROVER_INVALID."
    ),
)
@require_perm("claims.resolve_rejection")
def resolve_rejection(
    request: HttpRequest, claim_id: int, line_id: int, payload: ClaimResolveIn
) -> Any:
    return desk.resolve_rejection(
        claim_id,
        line_id,
        actor=_user(request),
        resolution=payload.resolution,
        reason=payload.reason,
        note=payload.note,
        approver=_approver(request, payload.approver),
    )


@claims_router.post(
    "/batches/{claim_id}/lines/{line_id}/write-off",
    response={200: ClaimDetailOut, **_READ},
    operation_id="claims_write_off_shortfall",
    summary="Write off accepted money the payer will not pay, with a reason",
    description=(
        "409 CLAIM_NOTHING_UNPAID, CLAIM_AMOUNT_INVALID, INVALID_AMOUNT, "
        "SECOND_APPROVER_REQUIRED, APPROVER_NOT_PERMITTED, APPROVER_INVALID."
    ),
)
@require_perm("claims.resolve_rejection")
def write_off_shortfall(
    request: HttpRequest, claim_id: int, line_id: int, payload: ClaimShortfallIn
) -> Any:
    return desk.write_off_shortfall(
        claim_id,
        line_id,
        actor=_user(request),
        amount=money(payload.amount),
        reason=payload.reason,
        note=payload.note,
        approver=_approver(request, payload.approver),
    )


# --- payer payments --------------------------------------------------------------------------


@claims_router.get(
    "/payers/{payer_id}/payable",
    response={200: list[ClaimPayableOut], **_READ},
    operation_id="claims_list_payable_claims",
    summary="A payer's claims with accepted money still unpaid, oldest first",
)
@require_perm("claims.view")
def list_payable(request: HttpRequest, payer_id: int) -> Any:
    return queries.payable_claims(payer_id)


@claims_router.get(
    "/payer-payments",
    response={200: Page[ClaimPayerPaymentOut], **_READ},
    operation_id="claims_list_payer_payments",
    summary="Payer payments, newest first",
)
@require_perm("claims.view")
def list_payer_payments(request: HttpRequest, params: Query[ClaimPaymentListParams]) -> Any:
    return queries.payer_payments_page(
        payer_id=params.payer_id,
        standing=params.standing,
        page=params.page,
        page_size=params.page_size,
    )


@claims_router.post(
    "/payer-payments",
    response={201: ClaimPayerPaymentOut, **_READ},
    operation_id="claims_record_payer_payment",
    summary="Record money from a payer and allocate it to its claims",
    description=(
        "A transfer goes to the bank, a cheque waits until cleared, cash goes into the "
        "recorder's open shift (409 SHIFT_NOT_OPEN). The allocations must equal the amount "
        "(PAYER_PAYMENT_UNBALANCED); also CLAIM_PAYMENT_EXCEEDS_ACCEPTED, "
        "CLAIM_NOTHING_UNPAID, DUPLICATE_REFERENCE, PAYER_ALLOCATION_CONFLICT."
    ),
)
@require_perm("claims.record_payer_payment")
def record_payer_payment(request: HttpRequest, payload: ClaimPayerPaymentIn) -> Any:
    return Status(
        201,
        desk.record_payer_payment(
            payer_id=payload.payer_id,
            amount=money(payload.amount),
            method=payload.method,
            bank_id=payload.bank_id,
            reference=payload.reference,
            received_on=payload.received_on,
            claims=None
            if payload.claims is None
            else [(a.claim_id, money(a.amount)) for a in payload.claims],
            lines=None
            if payload.lines is None
            else [(a.claim_line_id, money(a.amount)) for a in payload.lines],
            note=payload.note,
            actor=_user(request),
        ),
    )


@claims_router.post(
    "/payer-payments/{payment_id}/clear",
    response={200: ClaimPayerPaymentOut, **_READ},
    operation_id="claims_clear_payer_cheque",
    summary="A payer cheque cleared at the bank",
    description="409 PAYMENT_NOT_PENDING.",
)
@require_perm("claims.record_payer_payment")
def clear_cheque(request: HttpRequest, payment_id: int, payload: ClaimNoteIn) -> Any:
    return desk.clear_cheque(payment_id, actor=_user(request), note=payload.note)


@claims_router.post(
    "/payer-payments/{payment_id}/reverse",
    response={200: ClaimPayerPaymentOut, **_READ},
    operation_id="claims_reverse_payer_payment",
    summary="Reverse a bounced payer transfer or cheque (its allocations owe again)",
    description="409 REASON_REQUIRED, PAYMENT_NOT_REVERSIBLE, CLAIM_FINAL.",
)
@require_perm("claims.record_payer_payment")
def reverse_payment(request: HttpRequest, payment_id: int, payload: ClaimNoteIn) -> Any:
    return desk.reverse_payer_payment(payment_id, actor=_user(request), note=payload.note)
