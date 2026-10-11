"""Read side of the claim screens (FEATURES 11.2-11.7): plain JSON for ``/api/claims``.

Every amount comes from ``apps.claims.services`` (``payer_receivables``, ``accrued_lines``,
``claim_line_state``), which derive the payer receivable from the documents; they equal the
AR_PAYER ledger balance (tested). Nothing here counts a payer share as collected before a
payer payment is allocated to it (invariant 7).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum
from django.utils import timezone

from api.pagination import paginate
from apps.billing.models import InvoiceLine
from apps.catalog.models import Payer
from apps.claims import services as cs
from apps.claims.models import (
    Claim,
    ClaimLine,
    ClaimLineStatus,
    ClaimStatus,
    PayerPayment,
    PayerPaymentAllocation,
    PayerPaymentMethod,
)
from apps.core.models import CenterProfile, Policy, ReasonCode, User
from apps.patients.models import Patient, PatientCoverage
from apps.payments.models import Bank, Shift, ShiftStatus
from domain import claims as dclaims
from domain.money import ZERO

__all__ = [
    "accrued",
    "aging",
    "claim_detail",
    "claim_print",
    "claims_page",
    "options",
    "payable_claims",
    "payer_payment",
    "payer_payments_page",
    "receivables",
]

_AGING_FIELDS = {
    "0_30": "days_0_30",
    "31_60": "days_31_60",
    "61_90": "days_61_90",
    "over_90": "days_over_90",
}


# --- small JSON shapes --------------------------------------------------------------------


def _name(row: Payer | Bank | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


def _payer(row: Payer) -> dict[str, Any]:
    return {
        "id": row.pk,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "kind": row.kind,
        "claim_period": row.claim_period,
        "contract_no": row.contract_no,
        "active": row.active,
    }


def _user(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.pk,
        "username": user.username,
        "full_name_ar": user.full_name_ar,
        "full_name_en": user.full_name_en,
    }


def _reason(reason: ReasonCode | None) -> dict[str, Any] | None:
    if reason is None:
        return None
    return {
        "code": reason.code,
        "label_ar": reason.label_ar,
        "label_en": reason.label_en,
        "requires_note": reason.requires_note,
    }


def _patient(p: Patient) -> dict[str, Any]:
    return {
        "id": p.pk,
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
    }


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _shift(shift: Shift | None) -> dict[str, Any] | None:
    return None if shift is None else {"id": shift.pk, "number": shift.number}


# --- options ------------------------------------------------------------------------------


def options(viewer: User) -> dict[str, Any]:
    """Payers, banks, write-off reasons and the viewer's open shift (for payer cash)."""
    shift = Shift.objects.filter(cashier=viewer, status=ShiftStatus.OPEN).first()
    reasons = ReasonCode.objects.filter(category="writeoff", active=True).order_by(
        "sort_order", "code"
    )
    return {
        "payers": [_payer(p) for p in Payer.objects.order_by("code")],
        "banks": [
            _name(b) for b in Bank.objects.filter(active=True).order_by("sort_order", "code")
        ],
        "write_off_reasons": [_reason(r) for r in reasons],
        "open_shift": _shift(shift),
        "second_approver_required": Policy.load().claims_second_approver,
    }


# --- receivables and aging ----------------------------------------------------------------


def _aging(buckets: dict[str, Decimal]) -> dict[str, Any]:
    out = {field: _m(buckets.get(name, ZERO)) for name, field in _AGING_FIELDS.items()}
    out["total"] = _m(sum(buckets.values(), ZERO))
    return out


def _stages(r: cs.PayerReceivable) -> dict[str, Any]:
    return {
        "accrued": _m(r.accrued),
        "claimed": _m(r.claimed),
        "accepted_unpaid": _m(r.accepted_unpaid),
        "rejected_unresolved": _m(r.rejected_unresolved),
        "receivable": _m(r.receivable),
        "collected": _m(r.collected),
        "rebilled": _m(r.rebilled),
        "written_off": _m(r.written_off),
    }


def _rows(as_of: date) -> list[tuple[Payer, cs.PayerReceivable]]:
    """Every payer with a share on the books, and every active payer, by code."""
    found = cs.payer_receivables(as_of=as_of)
    out = []
    for payer in Payer.objects.order_by("code"):
        row = found.get(payer.pk)
        if row is None and not payer.active:
            continue
        out.append(
            (payer, row or cs.PayerReceivable(payer.pk, aging=dict.fromkeys(_AGING_FIELDS, ZERO)))
        )
    return out


def receivables(as_of: date | None = None) -> dict[str, Any]:
    """Payer receivables by stage (FEATURES 11.2, 12.7), with totals."""
    day = as_of or timezone.localdate()
    rows = _rows(day)
    total = cs.PayerReceivable(0)
    for _, r in rows:
        total.accrued += r.accrued
        total.claimed += r.claimed
        total.accepted_unpaid += r.accepted_unpaid
        total.rejected_unresolved += r.rejected_unresolved
        total.collected += r.collected
        total.rebilled += r.rebilled
        total.written_off += r.written_off
    return {
        "as_of": day,
        "items": [
            {"payer": _payer(p), "stages": _stages(r), "aging": _aging(r.aging)} for p, r in rows
        ],
        "totals": _stages(total),
    }


def aging(as_of: date | None = None) -> dict[str, Any]:
    """The outstanding payer receivable per payer by age since invoice approval (11.7)."""
    day = as_of or timezone.localdate()
    rows = _rows(day)
    totals: dict[str, Decimal] = dict.fromkeys(_AGING_FIELDS, ZERO)
    for _, r in rows:
        for name, value in r.aging.items():
            totals[name] += value
    return {
        "as_of": day,
        "items": [{"payer": _payer(p), "aging": _aging(r.aging)} for p, r in rows],
        "totals": _aging(totals),
    }


# --- invoice line fields shared by accrued and claimed lines ------------------------------


def _cards(lines: Iterable[InvoiceLine]) -> dict[int, str]:
    """The payer card number of each invoice line: the visit's when the line is billed to the
    visit's payer, otherwise the patient's coverage with that payer."""
    out: dict[int, str] = {}
    wanted: dict[tuple[int, int], list[int]] = defaultdict(list)
    for il in lines:
        visit = il.invoice.visit
        if il.payer_id is not None and visit.payer_id == il.payer_id and visit.card_number:
            out[il.pk] = visit.card_number
        elif il.payer_id is not None:
            wanted[(il.invoice.patient_id, il.payer_id)].append(il.pk)
    if wanted:
        rows = PatientCoverage.objects.filter(
            patient_id__in={p for p, _ in wanted}, payer_id__in={y for _, y in wanted}
        ).order_by("-active", "-is_default", "-id")
        for cov in rows:
            for line_id in wanted.pop((cov.patient_id, cov.payer_id), []):
                out[line_id] = cov.card_number
    return out


def _line_fields(il: InvoiceLine, cards: dict[int, str]) -> dict[str, Any]:
    inv = il.invoice
    approved_on = inv.priced_on or timezone.localdate(inv.approved_at or timezone.now())
    return {
        "invoice_line_id": il.pk,
        "invoice_id": inv.pk,
        "invoice_number": inv.number,
        "approved_on": approved_on,
        "patient": _patient(inv.patient),
        "card_number": cards.get(il.pk, ""),
        "service_code": il.service.code,
        "description_ar": il.description_ar,
        "description_en": il.description_en,
        "quantity": il.quantity,
        "gross": _m(il.gross),
        "pre_approval_ref": il.pre_approval_ref,
    }


_IL_RELATED = ("invoice__patient", "invoice__visit", "service")


def accrued(
    payer_id: int, period_start: date | None = None, period_end: date | None = None
) -> dict[str, Any]:
    """The payer's unclaimed shares of approved invoices (by approval date) to build a claim."""
    payer = Payer.objects.get(pk=payer_id)
    found = cs.accrued_lines(payer, period_start=period_start, period_end=period_end)
    ids = [a.invoice_line.pk for a in found]
    lines = {
        il.pk: il for il in InvoiceLine.objects.filter(pk__in=ids).select_related(*_IL_RELATED)
    }
    cards = _cards(lines.values())
    today = timezone.localdate()
    items = []
    for a in found:
        il = lines[a.invoice_line.pk]
        items.append(
            {
                **_line_fields(il, cards),
                "amount": _m(a.amount),
                "age_days": max((today - a.approved_on).days, 0),
            }
        )
    return {
        "payer": _payer(payer),
        "period_start": period_start,
        "period_end": period_end,
        "items": items,
        "total": _m(sum((a.amount for a in found), ZERO)),
    }


# --- claims -------------------------------------------------------------------------------


def _paid_by_line(line_ids: Sequence[int]) -> dict[int, Decimal]:
    rows = (
        PayerPaymentAllocation.objects.filter(claim_line_id__in=list(line_ids))
        .values("claim_line_id")
        .annotate(t=Sum("amount"))
    )
    return {r["claim_line_id"]: r["t"] or ZERO for r in rows}


def _live(lines: Iterable[ClaimLine]) -> list[ClaimLine]:
    return [cl for cl in lines if cl.status != ClaimLineStatus.WITHDRAWN]


def _totals(claim: Claim, states: Sequence[dclaims.ClaimLine]) -> dict[str, Any]:
    return {
        "id": claim.pk,
        "number": claim.number,
        "payer": _name(claim.payer),
        "period_start": claim.period_start,
        "period_end": claim.period_end,
        "status": claim.status,
        "claimed_total": _m(claim.claimed_total),
        "accepted_total": _m(claim.accepted_total),
        "rejected_total": _m(claim.rejected_total),
        "paid_total": _m(sum((s.paid for s in states), ZERO)),
        "unpaid_total": _m(sum((s.unpaid for s in states), ZERO)),
        "receivable": _m(sum((s.receivable for s in states), ZERO)),
        "line_count": len(states),
        "created_at": claim.created_at,
        "submitted_at": claim.submitted_at,
        "response_at": claim.response_at,
        "closed_at": claim.closed_at,
    }


def _states(lines: Sequence[ClaimLine]) -> dict[int, dclaims.ClaimLine]:
    paid = _paid_by_line([cl.pk for cl in lines])
    return {cl.pk: cs.claim_line_state(cl, paid=paid.get(cl.pk, ZERO)) for cl in lines}


def claims_page(
    *, payer_id: int | None, status: str | None, page: int, page_size: int
) -> dict[str, Any]:
    """Claim batches, newest period first, with their collection totals."""
    qs: QuerySet[Claim] = Claim.objects.select_related("payer").order_by("-created_at", "-id")
    if payer_id is not None:
        qs = qs.filter(payer_id=payer_id)
    if status:
        qs = qs.filter(status=status)
    result = paginate(qs, page, page_size)
    claims: list[Claim] = result["items"]
    by_claim: dict[int, list[ClaimLine]] = defaultdict(list)
    for cl in ClaimLine.objects.filter(claim__in=claims).exclude(status=ClaimLineStatus.WITHDRAWN):
        by_claim[cl.claim_id].append(cl)
    every = [cl for rows in by_claim.values() for cl in rows]
    states = _states(every)
    result["items"] = [_totals(c, [states[cl.pk] for cl in by_claim.get(c.pk, [])]) for c in claims]
    return result


def _line_json(cl: ClaimLine, state: dclaims.ClaimLine, cards: dict[int, str]) -> dict[str, Any]:
    return {
        **_line_fields(cl.invoice_line, cards),
        "id": cl.pk,
        "amount_claimed": _m(cl.amount_claimed),
        "status": cl.status,
        "stage": str(state.status),
        "accepted_amount": _m(cl.accepted_amount),
        "rejected_amount": _m(cl.rejected_amount),
        "paid": _m(state.paid),
        "written_off_amount": _m(cl.written_off_amount),
        "unpaid": _m(state.unpaid),
        "unresolved_rejection": _m(state.unresolved_rejection),
        "receivable": _m(state.receivable),
        "payer_reason": cl.payer_reason,
        "payer_reference": cl.payer_reference,
        "responded_at": cl.responded_at,
        "resolution": cl.resolution,
        "resolution_reason": _reason(cl.resolution_reason),
        "resolution_note": cl.resolution_note,
        "resolved_by": _user(cl.resolved_by),
        "resolved_at": cl.resolved_at,
        "written_off_reason": _reason(cl.written_off_reason),
        "written_off_note": cl.written_off_note,
        "withdraw_note": cl.withdraw_note,
    }


def claim_detail(claim_id: int) -> dict[str, Any]:
    """One claim batch with its live lines (withdrawn lines are left out) and payments."""
    claim = Claim.objects.select_related("payer", "created_by", "submitted_by").get(pk=claim_id)
    lines = _live(
        ClaimLine.objects.filter(claim=claim)
        .select_related(
            *(f"invoice_line__{r}" for r in _IL_RELATED),
            "resolution_reason",
            "resolved_by",
            "written_off_reason",
        )
        .order_by("id")
    )
    states = _states(lines)
    cards = _cards(cl.invoice_line for cl in lines)
    payments = (
        PayerPaymentAllocation.objects.filter(claim=claim, reversal_of__isnull=True)
        .values(
            "payer_payment_id",
            "payer_payment__number",
            "payer_payment__received_on",
            "payer_payment__method",
            "payer_payment__reversed_at",
        )
        .annotate(t=Sum("amount"))
        .order_by("payer_payment__received_on", "payer_payment_id")
    )
    return {
        **_totals(claim, [states[cl.pk] for cl in lines]),
        "note": claim.note,
        "created_by": _user(claim.created_by),
        "submitted_by": _user(claim.submitted_by),
        "lines": [_line_json(cl, states[cl.pk], cards) for cl in lines],
        "payments": [
            {
                "id": p["payer_payment_id"],
                "number": p["payer_payment__number"],
                "received_on": p["payer_payment__received_on"],
                "method": p["payer_payment__method"],
                "amount": _m(p["t"] or ZERO),
                "reversed": p["payer_payment__reversed_at"] is not None,
            }
            for p in payments
        ],
    }


def claim_print(claim_id: int) -> dict[str, Any]:
    """A claim batch addressed to its payer, with the center header (FEATURES 11.3)."""
    detail = claim_detail(claim_id)
    payer = Payer.objects.get(pk=detail["payer"]["id"])
    center = CenterProfile.load()
    return {
        "center": {
            "name_ar": center.name_ar,
            "name_en": center.name_en,
            "address": center.address,
            "phone": center.phone,
            "registration_no": center.registration_no,
            "tax_no": center.tax_no,
        },
        "payer": {
            **_payer(payer),
            "address": payer.address,
            "contact_name": payer.contact_name,
            "phone": payer.phone,
            "email": payer.email,
        },
        "claim": detail,
    }


# --- payer payments -----------------------------------------------------------------------


def payable_claims(payer_id: int) -> list[dict[str, Any]]:
    """The payer's claims with accepted money still unpaid, oldest period first."""
    lines = list(
        ClaimLine.objects.filter(
            claim__payer_id=payer_id,
            status__in=[ClaimLineStatus.ACCEPTED, ClaimLineStatus.PARTIAL],
        )
        .exclude(claim__status__in=[ClaimStatus.VOID, ClaimStatus.CLOSED])
        .select_related("claim")
        .order_by("claim__period_end", "claim_id", "id")
    )
    states = _states(lines)
    claims: dict[int, Claim] = {}
    sums: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    for cl in lines:
        claims[cl.claim_id] = cl.claim
        s = states[cl.pk]
        acc = sums[cl.claim_id]
        acc[0] += s.accepted
        acc[1] += s.paid
        acc[2] += s.unpaid
    return [
        {
            "id": c.pk,
            "number": c.number,
            "period_start": c.period_start,
            "period_end": c.period_end,
            "accepted_total": _m(sums[c.pk][0]),
            "paid_total": _m(sums[c.pk][1]),
            "unpaid_total": _m(sums[c.pk][2]),
        }
        for c in claims.values()
        if sums[c.pk][2] > 0
    ]


def _standing(p: PayerPayment) -> str:
    if p.reversed_at is not None:
        return "reversed"
    if p.method == PayerPaymentMethod.CASH:
        return "cash"
    if p.method == PayerPaymentMethod.CHEQUE:
        return "cheque_cleared" if p.cleared_at is not None else "cheque_pending"
    return "bank"


def _payment_json(p: PayerPayment) -> dict[str, Any]:
    rows = [a for a in p.allocations.all() if a.reversal_of_id is None]
    return {
        "id": p.pk,
        "number": p.number,
        "payer": _name(p.payer),
        "amount": _m(p.amount),
        "method": p.method,
        "standing": _standing(p),
        "bank": _name(p.bank),
        "reference": p.reference,
        "received_on": p.received_on,
        "shift": _shift(p.shift),
        "note": p.note,
        "recorded_by": _user(p.recorded_by),
        "recorded_at": p.recorded_at,
        "cleared_at": p.cleared_at,
        "reversed_at": p.reversed_at,
        "reverse_note": p.reverse_note,
        "allocations": [
            {
                "claim_id": a.claim_id,
                "claim_number": a.claim.number,
                "claim_line_id": a.claim_line_id,
                "amount": _m(a.amount),
            }
            for a in sorted(rows, key=lambda a: (a.claim_id, a.claim_line_id or 0))
        ],
    }


def _payments() -> QuerySet[PayerPayment]:
    return PayerPayment.objects.select_related(
        "payer", "bank", "shift", "recorded_by"
    ).prefetch_related("allocations__claim")


def payer_payment(payment_id: int) -> dict[str, Any]:
    return _payment_json(_payments().get(pk=payment_id))


def payer_payments_page(
    *, payer_id: int | None, standing: str | None, page: int, page_size: int
) -> dict[str, Any]:
    """Payer payments, newest first."""
    qs = _payments().order_by("-received_on", "-id")
    if payer_id is not None:
        qs = qs.filter(payer_id=payer_id)
    if standing == "cheque_pending":
        qs = qs.filter(
            method=PayerPaymentMethod.CHEQUE, cleared_at__isnull=True, reversed_at__isnull=True
        )
    elif standing == "reversed":
        qs = qs.filter(reversed_at__isnull=False)
    result = paginate(qs, page, page_size)
    result["items"] = [_payment_json(p) for p in result["items"]]
    return result
