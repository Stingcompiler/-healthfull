"""Read services of the cashier's money screens (FEATURES 6.x, 7.x).

Each function returns plain dicts shaped like ``apps.payments.schemas``. Reports come from
``apps.payments.services.shift_summary`` (a closed shift's report is its snapshot, never
recomputed, invariant 3); balances and positions from the engine services.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from api.errors import PermissionRequired
from api.pagination import paginate
from apps.billing import queries as bq
from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.core.models import ReasonCode, User
from apps.core.services import holds_permission
from apps.payments import services as pay
from apps.payments.models import (
    Allocation,
    Bank,
    CashHandover,
    Payment,
    Refund,
    Shift,
    ShiftReview,
    ShiftStatus,
    Till,
    Verification,
)
from domain import payments as dp
from domain.money import ZERO, money

__all__ = [
    "banks",
    "check_receipt",
    "current_shift",
    "handover_json",
    "handover_receivers",
    "open_shifts_for_handover",
    "payment_detail",
    "payment_json",
    "receipt",
    "refund_detail",
    "refund_json",
    "refunds",
    "rejection_json",
    "shift_report",
    "shifts",
    "tills",
    "transfers",
]


def _m(value: Decimal) -> str:
    return str(money(value))


def _reasons(category: str, codes: Iterable[str]) -> dict[str, ReasonCode]:
    return {r.code: r for r in ReasonCode.objects.filter(category=category, code__in=set(codes))}


# --- shifts ----------------------------------------------------------------------------------


def _review_json(shift: Shift) -> dict[str, Any] | None:
    review = ShiftReview.objects.select_related("reviewed_by").filter(shift=shift).first()
    if review is None:
        return None
    return {
        "outcome": review.outcome,
        "note": review.note,
        "reviewed_by": bq.user_json(review.reviewed_by),
        "reviewed_at": review.reviewed_at,
    }


def shift_json(s: Shift) -> dict[str, Any]:
    expected = s.expected_cash if s.status == ShiftStatus.CLOSED else pay.expected_cash(s)
    return {
        "id": s.pk,
        "number": s.number,
        "status": s.status,
        "cashier": bq.user_json(s.cashier),
        "till": bq.name_json(s.till),
        "opened_at": s.opened_at,
        "opening_float": _m(s.opening_float),
        "closed_at": s.closed_at,
        "closed_by": bq.user_json(s.closed_by),
        "expected_cash": _m(expected or ZERO),
        "counted_cash": bq.money_str(s.counted_cash),
        "variance": bq.money_str(s.variance),
        "variance_reason": bq.reason_json(s.variance_reason),
        "variance_note": s.variance_note,
        "review": _review_json(s),
    }


def handover_json(h: CashHandover) -> dict[str, Any]:
    return {
        "id": h.pk,
        "number": h.number,
        "shift_id": h.shift_id,
        "shift_number": h.shift.number,
        "destination": h.destination,
        "to_shift_id": h.to_shift_id,
        "to_shift_number": h.to_shift.number if h.to_shift is not None else None,
        "to_user": bq.user_json(h.to_user),
        "amount": _m(h.amount),
        "bank_reference": h.bank_reference,
        "handed_by": bq.user_json(h.handed_by),
        "handed_at": h.handed_at,
        "received_by": bq.user_json(h.received_by),
        "received_at": h.received_at,
        "cancelled_by": bq.user_json(h.cancelled_by),
        "cancelled_at": h.cancelled_at,
        "cancel_note": h.cancel_note,
        "note": h.note,
    }


def _handovers() -> QuerySet[CashHandover]:
    return CashHandover.objects.select_related(
        "shift", "to_shift", "to_user", "handed_by", "received_by", "cancelled_by"
    ).order_by("id")


def _transfer_rows(
    rows: Iterable[tuple[int, str, Decimal, int | None]],
) -> list[dict[str, Any]]:
    rows = list(rows)
    info = {
        pk: (bank or "", reference)
        for pk, bank, reference in Payment.objects.filter(pk__in=[r[0] for r in rows]).values_list(
            "id", "bank__code", "reference"
        )
    }
    return [
        {
            "payment_id": pk,
            "number": number,
            "amount": _m(amount),
            "bank": info.get(pk, ("", ""))[0],
            "reference": info.get(pk, ("", ""))[1],
            "age_days": age,
        }
        for pk, number, amount, age in rows
    ]


def _reason_totals(category: str, rows: Iterable[Any]) -> list[dict[str, Any]]:
    rows = list(rows)
    found = _reasons(category, (r.reason for r in rows))
    return [
        {
            "reason": bq.reason_json(found.get(r.reason)),
            "code": r.reason or "",
            "count": r.count,
            "amount": _m(r.amount),
        }
        for r in rows
    ]


def _reason_counts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    rows = list(rows)
    found = _reasons("line_cancel", (r.reason for r in rows))
    return [
        {"reason": bq.reason_json(found.get(r.reason)), "code": r.reason or "", "count": r.count}
        for r in rows
    ]


def report_json(shift: Shift) -> dict[str, Any]:
    """The report of one shift: live while open, the snapshot taken at close once closed."""
    summary = pay.shift_summary(shift)
    users = User.objects.in_bulk([d.user_id for d in summary.discounts])
    m, c = summary.movements, summary.collection
    return {
        "shift": shift_json(shift),
        "frozen": summary.frozen,
        "movements": {
            "opening_float": _m(m.opening_float),
            "cash_in": _m(m.cash_in),
            "cash_refunds": _m(m.cash_refunds),
            "handovers_out": _m(m.handovers_out),
            "handovers_in": _m(m.handovers_in),
        },
        "expected_cash": _m(summary.expected_cash),
        "counted_cash": bq.money_str(summary.counted_cash),
        "variance": bq.money_str(summary.variance),
        "collection": {
            "cash_confirmed": _m(c.cash_confirmed),
            "bank_confirmed": _m(c.bank_confirmed),
            "bank_pending": _m(c.bank_pending),
            "bank_rejected": _m(c.bank_rejected),
            "credit_used": _m(c.credit_used),
            "confirmed_total": _m(c.confirmed_collection),
        },
        "pending": _transfer_rows(
            (p.payment_id, p.number, p.amount, p.age_days) for p in summary.pending
        ),
        "confirmed_transfers": _transfer_rows(
            (t.payment_id, t.number, t.amount, None) for t in summary.confirmed_transfers
        ),
        "late_reversals": _m(summary.late_reversals),
        "late_confirmations": _m(summary.late_confirmations),
        "refunds_paid": _m(summary.refunds_paid),
        "refunds": _reason_totals("refund", summary.refunds),
        "discounts": [
            {"user": bq.user_json(users.get(d.user_id)), "amount": _m(d.amount)}
            for d in summary.discounts
        ],
        "credit_notes": _m(summary.credit_notes),
        "cancellations": _reason_totals("credit_note", summary.cancellations),
        "credit_from_cancellations": _m(summary.credit_from_cancellations),
        "credit_unallocated": _m(summary.credit_unallocated),
        "line_cancellations": _reason_counts(summary.line_cancellations),
        "voided_drafts": [
            {"invoice_id": v.invoice_id, "amount": _m(v.amount), "note": v.note}
            for v in summary.voided_drafts
        ],
        "handovers": [
            handover_json(h) for h in _handovers().filter(Q(shift=shift) | Q(to_shift=shift))
        ],
    }


def _shift(shift_id: int) -> Shift:
    return Shift.objects.select_related("cashier", "till", "closed_by", "variance_reason").get(
        pk=shift_id
    )


def shift_report(shift_id: int, *, viewer: User) -> dict[str, Any]:
    """A shift's report for its cashier, or for a holder of ``payments.view_all_shifts``.

    Raises:
        PermissionRequired: another cashier's shift without ``payments.view_all_shifts``.
    """
    shift = _shift(shift_id)
    if shift.cashier_id != viewer.pk and not holds_permission(viewer, "payments.view_all_shifts"):
        raise PermissionRequired("payments.view_all_shifts")
    return report_json(shift)


def _incoming(user: User) -> list[dict[str, Any]]:
    """Cash waiting for ``user``: handed to them or their shift, and, for a supervisor or an
    accountant, cash sent to the safe or the bank that nobody has confirmed yet (7.6)."""
    mine = Q(to_user=user) | Q(to_user__isnull=True, to_shift__cashier=user)
    if pay.can_receive_for_the_center(user):
        mine |= Q(to_user__isnull=True, to_shift__isnull=True)
    rows = (
        _handovers()
        .filter(mine, received_at__isnull=True, cancelled_at__isnull=True)
        .exclude(shift__cashier=user)
        .exclude(handed_by=user)
    )
    return [handover_json(h) for h in rows]


def handover_receivers(user: User) -> list[dict[str, Any]]:
    """Active people other than ``user`` who can confirm cash for the center (7.6)."""
    return [
        {
            "id": u.pk,
            "username": u.username,
            "full_name_ar": u.full_name_ar,
            "full_name_en": u.full_name_en,
        }
        for u in pay.center_receivers(exclude=user)
    ]


def current_shift(user: User) -> dict[str, Any]:
    """The user's open shift report (or none) and cash handed to them that waits."""
    shift = pay.current_shift(user)
    return {
        "report": report_json(_shift(shift.pk)) if shift is not None else None,
        "incoming_handovers": _incoming(user),
    }


def shifts(
    *,
    status: str | None = None,
    reviewed: bool | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Shifts newest first, for supervisors and managers (review queue: closed, unreviewed)."""
    qs = (
        Shift.objects.select_related("cashier", "till", "closed_by", "variance_reason")
        .annotate(
            pending_n=Count(
                "payments",
                filter=Q(
                    payments__verification=Verification.PENDING,
                    payments__reversal_of__isnull=True,
                ),
            ),
            pending_sum=Sum(
                "payments__amount",
                filter=Q(
                    payments__verification=Verification.PENDING,
                    payments__reversal_of__isnull=True,
                ),
            ),
        )
        .order_by("-opened_at", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    if reviewed is not None:
        qs = qs.filter(review__isnull=not reviewed)
    if q:
        term = q.strip()
        qs = qs.filter(
            Q(number__iexact=term)
            | Q(cashier__username__icontains=term)
            | Q(cashier__full_name_ar__icontains=term)
            | Q(cashier__full_name_en__icontains=term)
        )
    data = paginate(qs, page, page_size)
    data["items"] = [
        {
            "shift": shift_json(s),
            "pending_count": int(getattr(s, "pending_n", 0)),
            "pending_amount": _m(getattr(s, "pending_sum", None) or ZERO),
        }
        for s in data["items"]
    ]
    return data


def open_shifts_for_handover(user: User) -> list[dict[str, Any]]:
    """Other cashiers' open shifts, the possible receivers of a next-shift handover."""
    rows = (
        Shift.objects.filter(status=ShiftStatus.OPEN)
        .exclude(cashier=user)
        .select_related("cashier")
        .order_by("opened_at", "id")
    )
    return [
        {
            "id": s.pk,
            "number": s.number,
            "cashier": bq.user_json(s.cashier),
            "opened_at": s.opened_at,
        }
        for s in rows
    ]


def banks() -> list[dict[str, Any]]:
    return [
        x
        for x in (bq.name_json(b) for b in Bank.objects.filter(active=True).order_by("sort_order"))
        if x is not None
    ]


def tills() -> list[dict[str, Any]]:
    return [x for x in (bq.name_json(t) for t in Till.objects.filter(active=True)) if x]


# --- payments --------------------------------------------------------------------------------


def _payments() -> QuerySet[Payment]:
    return Payment.objects.select_related(
        "shift",
        "patient",
        "bank",
        "verified_by",
        "rejection_reason",
        "duplicate_of",
        "override_by",
        "override_reason",
        "reversal_of",
        "created_by",
    )


def _age_days(p: Payment) -> int:
    received = timezone.localdate(p.created_at)
    return dp.pending_age_days(received, max(received, timezone.localdate()))


def payment_json(p: Payment) -> dict[str, Any]:
    rows = list(p.allocations.select_related("invoice").order_by("id"))
    net = sum((a.amount for a in rows), ZERO)
    reversal = Payment.objects.filter(reversal_of=p).values_list("number", flat=True).first()
    unallocated = (
        p.amount - net if p.amount > 0 and p.verification != Verification.REJECTED else ZERO
    )
    return {
        "id": p.pk,
        "number": p.number,
        "shift_id": p.shift_id,
        "shift_number": p.shift.number,
        "shift_status": p.shift.status,
        "patient": bq.patient_json(p.patient),
        "method": p.method,
        "amount": _m(p.amount),
        "bank": bq.name_json(p.bank),
        "reference": p.reference,
        "transfer_date": p.transfer_date,
        "sender_name": p.sender_name,
        "verification": p.verification,
        "verified_by": bq.user_json(p.verified_by),
        "verified_at": p.verified_at,
        "rejection_reason": bq.reason_json(p.rejection_reason),
        "rejection_note": p.rejection_note,
        "duplicate_override": p.duplicate_override,
        "duplicate_of_number": p.duplicate_of.number if p.duplicate_of is not None else None,
        "override_by": bq.user_json(p.override_by),
        "override_reason": bq.reason_json(p.override_reason),
        "override_note": p.override_note,
        "reversal_of_number": p.reversal_of.number if p.reversal_of is not None else None,
        "reversal_number": reversal,
        "note": p.note,
        "created_by": bq.user_json(p.created_by),
        "created_at": p.created_at,
        "age_days": _age_days(p),
        "allocations": [
            {
                "id": a.pk,
                "invoice_id": a.invoice_id,
                "invoice_number": a.invoice.number,
                "kind": a.kind,
                "amount": _m(a.amount),
                "created_at": a.created_at,
            }
            for a in rows
        ],
        "unallocated": _m(max(unallocated, ZERO)),
    }


def payment_detail(payment_id: int) -> dict[str, Any]:
    return payment_json(_payments().get(pk=payment_id))


def rejection_json(rejection: pay.Rejection) -> dict[str, Any]:
    return {
        "payment": payment_detail(rejection.payment.pk),
        "reversal": (
            payment_detail(rejection.reversal.pk) if rejection.reversal is not None else None
        ),
        "uncovered": _m(rejection.uncovered),
    }


def _verify_code(p: Payment) -> str:
    """What a receipt's QR carries: number, amount and day, checked against the system."""
    return dp.receipt_code(p.number, money(p.amount), timezone.localdate(p.created_at))


def check_receipt(code: str) -> dict[str, Any]:
    """Check a scanned receipt QR or a typed receipt number against the system (6.9, 15.1).

    Raises:
        Payment.DoesNotExist: no payment has that number (404).
    """
    parsed = dp.parse_receipt_code(code)
    p = _payments().get(number__iexact=parsed.number)
    day = timezone.localdate(p.created_at)
    standing = dp.receipt_standing(
        parsed,
        amount=p.amount,
        day=day,
        verification=dp.Verification(p.verification),
        reversed_=Payment.objects.filter(reversal_of=p).exists(),
        is_reversal=p.reversal_of_id is not None,
    )
    return {
        "standing": str(standing),
        "code_amount": _m(parsed.amount) if parsed.amount is not None else None,
        "code_day": parsed.day,
        "day": day,
        "payment": payment_json(p),
    }


def receipt(payment_id: int) -> dict[str, Any]:
    """A payment receipt (thermal 80 mm or A4, FEATURES 6.9): what was paid for, and the
    code its QR carries so a printed receipt can be checked against the system."""
    p = _payments().get(pk=payment_id)
    per_invoice: dict[int, Decimal] = {}
    for inv_id, amount in Allocation.objects.filter(payment=p).values_list("invoice_id", "amount"):
        per_invoice[inv_id] = per_invoice.get(inv_id, ZERO) + amount
    invoices = []
    for inv in Invoice.objects.filter(
        pk__in=[k for k, v in per_invoice.items() if v != 0]
    ).order_by("id"):
        invoices.append(
            {
                "id": inv.pk,
                "number": inv.number,
                "amount": _m(per_invoice[inv.pk]),
                "outstanding": _m(billing.invoice_position(inv).outstanding),
                "lines": [
                    {
                        "description_ar": il.description_ar,
                        "description_en": il.description_en,
                        "quantity": int(il.quantity),
                        "patient_share": _m(il.patient_share),
                    }
                    for il in inv.lines.order_by("line_no")
                ],
            }
        )
    return {
        "center": bq.center_json(),
        "payment": payment_json(p),
        "invoices": invoices,
        "cashier": bq.user_json(p.created_by),
        "verify_code": _verify_code(p),
    }


def transfers(
    *,
    viewer: User,
    verification: str = Verification.PENDING,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Bank, QR and card payments by verification state, oldest pending first (FEATURES 6.4).

    Each row says what stops ``viewer`` (ADR 0008): ``self_recorded`` (they took it or it is
    their shift's, so another checker confirms it) and ``reject_needs_open_shift`` (its shift
    is closed and the viewer has no open shift for the reversal, FEATURES 6.8).
    """
    viewer_open = pay.current_shift(viewer) is not None
    qs = _payments().filter(
        method__in=[str(x) for x in dp.REFERENCE_METHODS],
        reversal_of__isnull=True,
        verification=verification,
    )
    qs = (
        qs.order_by("created_at", "id")
        if verification == Verification.PENDING
        else qs.order_by("-verified_at", "-id")
    )
    if q:
        term = q.strip()
        norm = dp.normalize_reference(term) if term else ""
        qs = qs.filter(
            Q(number__iexact=term)
            | Q(reference_norm=norm)
            | Q(patient__file_no__iexact=term)
            | Q(shift__number__iexact=term)
        )
    data = paginate(qs, page, page_size)
    data["items"] = [
        {
            "payment": payment_json(p),
            "cashier": bq.user_json(p.created_by),
            "self_recorded": viewer.pk in (p.created_by_id, p.shift.cashier_id),
            "reject_needs_open_shift": p.shift.status == ShiftStatus.CLOSED and not viewer_open,
        }
        for p in data["items"]
    ]
    return data


# --- refunds ---------------------------------------------------------------------------------


def refund_json(r: Refund) -> dict[str, Any]:
    return {
        "id": r.pk,
        "number": r.number,
        "patient": bq.patient_json(r.patient),
        "amount": _m(r.amount),
        "method": r.method,
        "credit_note_id": r.credit_note_id,
        "credit_note_number": r.credit_note.number if r.credit_note is not None else None,
        "reason": bq.reason_json(r.reason_code),
        "reason_note": r.reason_note,
        "status": r.status,
        "requested_by": bq.user_json(r.requested_by),
        "requested_at": r.requested_at,
        "decided_by": bq.user_json(r.decided_by),
        "decided_at": r.decided_at,
        "decision_note": r.decision_note,
        "shift_number": r.shift.number if r.shift is not None else None,
        "paid_by": bq.user_json(r.paid_by),
        "paid_at": r.paid_at,
    }


def _refunds() -> QuerySet[Refund]:
    return Refund.objects.select_related(
        "patient", "credit_note", "reason_code", "requested_by", "decided_by", "shift", "paid_by"
    )


def refund_detail(refund_id: int) -> dict[str, Any]:
    return refund_json(_refunds().get(pk=refund_id))


def refunds(
    *, status: str | None = None, q: str | None = None, page: int = 1, page_size: int = 25
) -> dict[str, Any]:
    """Refund documents, newest first (status=requested: the approval queue)."""
    qs = _refunds().order_by("-requested_at", "-id")
    if status:
        qs = qs.filter(status=status)
    if q:
        term = q.strip()
        qs = qs.filter(
            Q(number__iexact=term)
            | Q(patient__file_no__iexact=term)
            | Q(credit_note__number__iexact=term)
        )
    data = paginate(qs, page, page_size)
    data["items"] = [refund_json(r) for r in data["items"]]
    return data
