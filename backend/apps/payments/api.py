"""``/api/payments``: shifts, payments and allocation, transfers, refunds and handovers.

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, schema in/out and
one call into ``apps.payments.queries`` (reads) or ``apps.payments.desk`` (commands). Rules
live in ``domain`` and ``apps.payments.services``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Status
from ninja.errors import AuthenticationError

from api.pagination import PageParams
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.billing.schemas import BillingUserRefOut, NameOut
from apps.core.models import User
from apps.payments import desk, queries
from apps.payments.approvals import ApproverLogin
from apps.payments.schemas import (
    AllocateIn,
    AllocationIn,
    CurrentShiftOut,
    DecisionIn,
    HandoverCancelIn,
    HandoverIn,
    HandoverOut,
    OpenShiftRefOut,
    PaymentIn,
    PaymentOut,
    ReceiptCheckOut,
    ReceiptOut,
    RefundIn,
    RefundOut,
    RefundStatusCode,
    RejectIn,
    RejectionOut,
    ShiftCloseIn,
    ShiftListItemOut,
    ShiftOpenIn,
    ShiftReportOut,
    ShiftReviewIn,
    TransferConfirmIn,
    TransferOut,
    VerificationCode,
)
from domain.money import money

payments_router = Router(tags=["payments"])
add_ping(payments_router, "payments")

_READ = {**ERROR_RESPONSES, 404: ErrorOut}
#: Desk approvals may answer 423 (approver locked) or 429 (too many failures from here).
_DESK = {**_READ, 423: ErrorOut, 429: ErrorOut}


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


def _allocations(rows: list[AllocationIn] | None) -> list[tuple[int, Decimal]] | None:
    if rows is None:
        return None
    return [(row.invoice_id, money(row.amount)) for row in rows]


# --- reference lists -------------------------------------------------------------------------


@payments_router.get(
    "/banks",
    response={200: list[NameOut], **_READ},
    operation_id="payments_list_banks",
    summary="Banks for transfer, QR and card payments",
)
@require_perm("payments.view")
def list_banks(request: HttpRequest) -> Any:
    return queries.banks()


@payments_router.get(
    "/tills",
    response={200: list[NameOut], **_READ},
    operation_id="payments_list_tills",
    summary="Active tills (cash drawers)",
)
@require_perm("payments.view")
def list_tills(request: HttpRequest) -> Any:
    return queries.tills()


# --- shifts ----------------------------------------------------------------------------------


@payments_router.get(
    "/shifts/current",
    response={200: CurrentShiftOut, **_READ},
    operation_id="payments_get_current_shift",
    summary="The user's open shift report (or null) and cash handed to them that waits",
)
@require_perm("payments.view")
def current_shift(request: HttpRequest) -> Any:
    return queries.current_shift(_user(request))


@payments_router.post(
    "/shifts",
    response={201: ShiftReportOut, **_READ},
    operation_id="payments_open_shift",
    summary="Open the user's shift with an opening float",
)
@require_perm("payments.open_shift")
def open_shift(request: HttpRequest, payload: ShiftOpenIn) -> Any:
    return Status(
        201,
        desk.open_shift(
            _user(request),
            opening_float=money(payload.opening_float),
            till=payload.till,
            note=payload.note,
        ),
    )


@payments_router.get(
    "/shifts",
    response={200: Page[ShiftListItemOut], **_READ},
    operation_id="payments_list_shifts",
    summary="Shifts, newest first (status=closed&reviewed=false: the review queue)",
)
@require_perm("payments.view_all_shifts")
def list_shifts(
    request: HttpRequest,
    params: Query[PageParams],
    status: str | None = None,
    reviewed: bool | None = None,
) -> Any:
    return queries.shifts(
        status=status, reviewed=reviewed, q=params.q, page=params.page, page_size=params.page_size
    )


@payments_router.get(
    "/shifts/handover-targets",
    response={200: list[OpenShiftRefOut], **_READ},
    operation_id="payments_list_handover_targets",
    summary="Other cashiers' open shifts that can receive a next-shift handover",
)
@require_perm("payments.cash_handover")
def handover_targets(request: HttpRequest) -> Any:
    return queries.open_shifts_for_handover(_user(request))


@payments_router.get(
    "/handover-receivers",
    response={200: list[BillingUserRefOut], **_READ},
    operation_id="payments_list_handover_receivers",
    summary="The supervisors and accountants who can receive cash handed over by the user",
)
@require_perm("payments.cash_handover")
def handover_receivers(request: HttpRequest) -> Any:
    return queries.handover_receivers(_user(request))


@payments_router.get(
    "/shifts/{shift_id}",
    response={200: ShiftReportOut, **_READ},
    operation_id="payments_get_shift",
    summary="A shift's report (own shift, or any with payments.view_all_shifts)",
)
@require_perm("payments.view")
def get_shift(request: HttpRequest, shift_id: int) -> Any:
    return queries.shift_report(shift_id, viewer=_user(request))


@payments_router.post(
    "/shifts/{shift_id}/close",
    response={200: ShiftReportOut, **_READ},
    operation_id="payments_close_shift",
    summary="Close a shift with the counted cash (a variance needs a reason)",
)
@require_perm("payments.close_shift")
def close_shift(request: HttpRequest, shift_id: int, payload: ShiftCloseIn) -> Any:
    return desk.close_shift(
        shift_id,
        actor=_user(request),
        counted=money(payload.counted),
        reason=payload.reason,
        note=payload.note,
    )


@payments_router.post(
    "/shifts/{shift_id}/review",
    response={200: ShiftReportOut, **_READ},
    operation_id="payments_review_shift",
    summary="Sign off (or flag) a closed shift; never one's own",
)
@require_perm("payments.review_shift")
def review_shift(request: HttpRequest, shift_id: int, payload: ShiftReviewIn) -> Any:
    return desk.review_shift(
        shift_id, actor=_user(request), outcome=payload.outcome, note=payload.note
    )


@payments_router.post(
    "/shifts/{shift_id}/handovers",
    response={201: HandoverOut, **_READ},
    operation_id="payments_create_handover",
    summary="Hand cash from the drawer to the next shift, the safe, the bank or a supervisor",
)
@require_perm("payments.cash_handover")
def create_handover(request: HttpRequest, shift_id: int, payload: HandoverIn) -> Any:
    return Status(
        201,
        desk.hand_over(
            shift_id,
            actor=_user(request),
            amount=money(payload.amount),
            destination=payload.destination,
            to_shift_id=payload.to_shift_id,
            to_user_id=payload.to_user_id,
            bank_reference=payload.bank_reference,
            note=payload.note,
        ),
    )


@payments_router.post(
    "/handovers/{handover_id}/receive",
    response={200: HandoverOut, **_READ},
    operation_id="payments_receive_handover",
    summary="Confirm handed-over cash arrived",
)
@require_perm("payments.receive_handover")
def receive_handover(request: HttpRequest, handover_id: int) -> Any:
    return desk.receive_handover(handover_id, actor=_user(request))


@payments_router.post(
    "/handovers/{handover_id}/cancel",
    response={200: HandoverOut, **_READ},
    operation_id="payments_cancel_handover",
    summary="Cancel an unreceived handover while the sending shift is open",
)
@require_perm("payments.cash_handover")
def cancel_handover(request: HttpRequest, handover_id: int, payload: HandoverCancelIn) -> Any:
    return desk.cancel_handover(handover_id, actor=_user(request), note=payload.note)


# --- payments --------------------------------------------------------------------------------


@payments_router.post(
    "/payments",
    response={201: PaymentOut, **_DESK},
    operation_id="payments_record_payment",
    summary="Take a payment into the user's open shift and allocate it",
    description=(
        "Bank transfer, QR and card need `bank` and `reference`; they start pending. A "
        "reference already used for the bank answers 409 DUPLICATE_REFERENCE unless "
        "`override` gives a reason and a supervisor holding payments.override_duplicate "
        "(the user, or `override.approver` credentials: 409 APPROVER_INVALID when wrong)."
    ),
)
@require_perm("payments.take_payment")
def record_payment(request: HttpRequest, payload: PaymentIn) -> Any:
    override = payload.override
    approver = (
        ApproverLogin(request, override.approver.username, override.approver.password)
        if override is not None and override.approver is not None
        else None
    )
    return Status(
        201,
        desk.take_payment(
            _user(request),
            patient_id=payload.patient_id,
            method=payload.method,
            amount=money(payload.amount),
            bank=payload.bank,
            reference=payload.reference,
            transfer_date=payload.transfer_date,
            sender_name=payload.sender_name,
            allocations=_allocations(payload.allocations),
            auto=payload.auto,
            visit_id=payload.visit_id,
            note=payload.note,
            override_reason=override.reason if override is not None else None,
            override_note=override.note if override is not None else "",
            approver=approver,
        ),
    )


@payments_router.get(
    "/receipts/check",
    response={200: ReceiptCheckOut, **_READ},
    operation_id="payments_check_receipt",
    summary="Check a printed receipt: its scanned QR code or its receipt number",
    description=(
        "`code` is the QR text (`number|amount|YYYY-MM-DD`) or a receipt number. 404 when no "
        "payment has that number."
    ),
)
@require_perm("payments.view")
def check_receipt(
    request: HttpRequest, code: str = Query(..., min_length=1, max_length=200)
) -> Any:
    return queries.check_receipt(code)


@payments_router.get(
    "/payments/{payment_id}",
    response={200: PaymentOut, **_READ},
    operation_id="payments_get_payment",
    summary="One payment with its allocations",
)
@require_perm("payments.view")
def get_payment(request: HttpRequest, payment_id: int) -> Any:
    return queries.payment_detail(payment_id)


@payments_router.get(
    "/payments/{payment_id}/receipt",
    response={200: ReceiptOut, **_READ},
    operation_id="payments_get_receipt",
    summary="A payment receipt for 80 mm or A4 printing, with its verification code",
)
@require_perm("payments.view")
def get_receipt(request: HttpRequest, payment_id: int) -> Any:
    return queries.receipt(payment_id)


@payments_router.post(
    "/payments/{payment_id}/allocate",
    response={200: PaymentOut, **_READ},
    operation_id="payments_allocate_payment",
    summary="Allocate a payment's remainder to open invoices",
)
@require_perm("payments.take_payment")
def allocate(request: HttpRequest, payment_id: int, payload: AllocateIn) -> Any:
    return desk.allocate(
        payment_id,
        actor=_user(request),
        allocations=_allocations(payload.allocations),
        auto=payload.auto,
        visit_id=payload.visit_id,
    )


# --- transfers -------------------------------------------------------------------------------


@payments_router.get(
    "/transfers",
    response={200: Page[TransferOut], **_READ},
    operation_id="payments_list_transfers",
    summary="Transfers, QR and card payments by verification state (pending: oldest first)",
)
@require_perm("payments.confirm_transfer")
def list_transfers(
    request: HttpRequest, params: Query[PageParams], verification: VerificationCode = "pending"
) -> Any:
    return queries.transfers(
        viewer=_user(request),
        verification=verification,
        q=params.q,
        page=params.page,
        page_size=params.page_size,
    )


@payments_router.post(
    "/payments/{payment_id}/confirm",
    response={200: PaymentOut, **_READ},
    operation_id="payments_confirm_transfer",
    summary="Confirm a pending transfer, saying what was checked",
)
@require_perm("payments.confirm_transfer")
def confirm_transfer(request: HttpRequest, payment_id: int, payload: TransferConfirmIn) -> Any:
    return desk.confirm_transfer(payment_id, actor=_user(request), note=payload.note)


@payments_router.post(
    "/payments/{payment_id}/reject",
    response={200: RejectionOut, **_READ},
    operation_id="payments_reject_transfer",
    summary="Reject a transfer (after its shift closed: reversal in the user's open shift)",
)
@require_perm("payments.reject_transfer")
def reject_transfer(request: HttpRequest, payment_id: int, payload: RejectIn) -> Any:
    return desk.reject_transfer(
        payment_id, actor=_user(request), reason=payload.reason, note=payload.note
    )


# --- refunds ---------------------------------------------------------------------------------


@payments_router.get(
    "/refunds",
    response={200: Page[RefundOut], **_READ},
    operation_id="payments_list_refunds",
    summary="Refunds, newest first (status=requested: the approval queue)",
)
@require_perm("payments.view")
def list_refunds(
    request: HttpRequest, params: Query[PageParams], status: RefundStatusCode | None = None
) -> Any:
    return queries.refunds(status=status, q=params.q, page=params.page, page_size=params.page_size)


@payments_router.post(
    "/refunds",
    response={201: RefundOut, **_READ},
    operation_id="payments_request_refund",
    summary="Request a refund of credit an approved credit note created",
)
@require_perm("payments.request_refund")
def request_refund(request: HttpRequest, payload: RefundIn) -> Any:
    return Status(
        201,
        desk.request_refund(
            _user(request),
            credit_note_id=payload.credit_note_id,
            patient_id=payload.patient_id,
            amount=money(payload.amount),
            reason=payload.reason,
            note=payload.note,
        ),
    )


@payments_router.post(
    "/refunds/{refund_id}/approve",
    response={200: RefundOut, **_READ},
    operation_id="payments_approve_refund",
    summary="Approve a refund request (never one's own)",
)
@require_perm("payments.approve_refund")
def approve_refund(request: HttpRequest, refund_id: int, payload: DecisionIn) -> Any:
    return desk.approve_refund(refund_id, actor=_user(request), note=payload.note)


@payments_router.post(
    "/refunds/{refund_id}/reject",
    response={200: RefundOut, **_READ},
    operation_id="payments_reject_refund",
    summary="Refuse a refund request; the money stays as patient credit",
)
@require_perm("payments.approve_refund")
def reject_refund(request: HttpRequest, refund_id: int, payload: DecisionIn) -> Any:
    return desk.reject_refund(refund_id, actor=_user(request), note=payload.note)


@payments_router.post(
    "/refunds/{refund_id}/pay",
    response={200: RefundOut, **_READ},
    operation_id="payments_pay_refund",
    summary="Pay an approved refund in cash from the user's open shift",
)
@require_perm("payments.pay_refund")
def pay_refund(request: HttpRequest, refund_id: int) -> Any:
    return desk.pay_refund(refund_id, actor=_user(request))
