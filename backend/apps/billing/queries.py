"""Read services of the cashier's billing screens (FLOW step 4, FEATURES 5.3-5.11).

Each function loads what one screen shows and returns plain dicts shaped like
``apps.billing.schemas``. No rule is decided here: positions, states and balances come from
``apps.billing.services``, ``apps.orders.services`` and ``apps.payments.services``.
"""

from __future__ import annotations

import importlib
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import CreditNote, DocumentStatus, Invoice, InvoiceLine
from apps.catalog import services as catalog
from apps.catalog.models import Payer, Service
from apps.core.models import CenterProfile, Department, ReasonCode, User
from apps.orders import services as orders
from apps.orders.models import BillingStatus, FulfilmentStatus, ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.visits.models import Visit, VisitStatus
from domain.money import ZERO, money

__all__ = [
    "REASON_CATEGORIES",
    "balance_json",
    "credit_note_detail",
    "credit_note_json",
    "credit_notes",
    "credit_outcome_json",
    "invoice_detail",
    "invoice_json",
    "invoice_print",
    "lookup",
    "money_str",
    "name_json",
    "patient_json",
    "reason_json",
    "reasons",
    "unbilled",
    "user_json",
    "visit_billing",
]

#: Reason lists the cashier screens use (``ReasonCode.category``).
REASON_CATEGORIES = (
    "discount",
    "credit_note",
    "line_cancel",
    "override",
    "variance",
    "refund",
    "transfer_reject",
    "perform_first",
)

#: How far back the lookup lists a patient's visits that have nothing left to bill or pay.
RECENT_VISIT_DAYS = 7
#: Visits listed per patient in the lookup.
VISITS_PER_PATIENT = 5

_VISIT_NO = re.compile(r"^VIS-", re.IGNORECASE)


def _payments() -> ModuleType:
    return importlib.import_module("apps.payments.services")


def _payment_models() -> ModuleType:
    return importlib.import_module("apps.payments.models")


# --- small shapes ----------------------------------------------------------------------------


def money_str(value: Decimal | None) -> str | None:
    return None if value is None else str(money(value))


def _m(value: Decimal) -> str:
    return str(money(value))


def name_json(row: Payer | Department | Service | Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


def service_json(row: Service) -> dict[str, Any]:
    return {**(name_json(row) or {}), "kind": row.kind}


def user_json(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.pk,
        "username": user.username,
        "full_name_ar": user.full_name_ar,
        "full_name_en": user.full_name_en,
    }


def reason_json(reason: ReasonCode | None) -> dict[str, Any] | None:
    if reason is None:
        return None
    return {
        "code": reason.code,
        "label_ar": reason.label_ar,
        "label_en": reason.label_en,
        "requires_note": reason.requires_note,
    }


def patient_json(p: Patient) -> dict[str, Any]:
    return {
        "id": p.pk,
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
        "phone": p.phone,
        "is_incomplete": p.is_incomplete,
        "merged_into_id": p.merged_into_id,
    }


def balance_json(patient: Patient) -> dict[str, Any]:
    bal = _payments().patient_balance(patient)
    return {
        "credit": _m(bal.credit),
        "spendable": _m(bal.spendable),
        "pending": _m(bal.pending),
        "outstanding": _m(bal.outstanding),
    }


def _open_invoices_json(patient: Patient) -> list[dict[str, Any]]:
    return [
        {
            "id": inv.pk,
            "number": inv.number or "",
            "visit_id": inv.visit_id,
            "outstanding": _m(pos.outstanding),
        }
        for inv, pos in billing.open_invoices(patient)
    ]


# --- lookup ----------------------------------------------------------------------------------


def _find_patients(query: str, limit: int) -> list[Patient]:
    term = query.strip()
    if _VISIT_NO.match(term):
        visit = Visit.objects.select_related("patient").filter(number__iexact=term).first()
        return [visit.patient] if visit is not None else []
    return patients.search_patients(term, limit=limit)


def _visit_rows(patient_ids: Sequence[int]) -> dict[int, list[Visit]]:
    """Visits worth showing per patient: open ones, recent ones, newest first."""
    since = timezone.now() - timedelta(days=RECENT_VISIT_DAYS)
    qs = (
        Visit.objects.filter(patient_id__in=patient_ids)
        .filter(Q(status=VisitStatus.OPEN) | Q(created_at__gte=since))
        .select_related("department", "doctor__user", "payer")
        .annotate(
            unbilled=Count(
                "lines",
                filter=Q(lines__billing_status=BillingStatus.UNBILLED)
                & ~Q(lines__fulfilment_status=FulfilmentStatus.CANCELLED),
                distinct=True,
            ),
            drafts=Count(
                "invoices", filter=Q(invoices__status=DocumentStatus.DRAFT), distinct=True
            ),
        )
        .order_by("-created_at", "-id")
    )
    out: dict[int, list[Visit]] = defaultdict(list)
    for v in qs:
        if len(out[v.patient_id]) < VISITS_PER_PATIENT:
            out[v.patient_id].append(v)
    return out


def _visit_outstanding(visit: Visit) -> Decimal:
    total = ZERO
    for inv in Invoice.objects.filter(visit=visit, status=DocumentStatus.APPROVED):
        total += billing.invoice_position(inv).outstanding
    return total


def visit_ref_json(v: Visit) -> dict[str, Any]:
    return {
        "id": v.pk,
        "number": v.number,
        "visit_type": v.visit_type,
        "status": v.status,
        "created_at": v.created_at,
        "department": name_json(v.department),
        "doctor": user_json(v.doctor.user) if v.doctor is not None else None,
        "payer": name_json(v.payer),
        "card_number": v.card_number,
    }


def lookup(query: str, *, limit: int = 10) -> dict[str, Any]:
    """Patients by file number, visit number, phone or name (FEATURES 0.9), each with the
    visits the cashier may bill or collect for and the person's balance."""
    found = _find_patients(query, limit)
    by_patient = _visit_rows([p.pk for p in found])
    items = []
    for p in found:
        visits = []
        for v in by_patient.get(p.pk, []):
            ref = visit_ref_json(v)
            ref.pop("card_number")
            visits.append(
                {
                    **ref,
                    "unbilled_count": int(getattr(v, "unbilled", 0)),
                    "draft_invoice_count": int(getattr(v, "drafts", 0)),
                    "outstanding": _m(_visit_outstanding(v)),
                }
            )
        items.append({"patient": patient_json(p), "visits": visits, "balance": balance_json(p)})
    return {"items": items}


# --- lines and invoices ----------------------------------------------------------------------


def _draft_holders(line_ids: Iterable[int]) -> dict[int, int]:
    return dict(
        InvoiceLine.objects.filter(
            service_line_id__in=list(line_ids), invoice__status=DocumentStatus.DRAFT
        ).values_list("service_line_id", "invoice_id")
    )


def _line_json(sl: ServiceLine, holders: dict[int, int]) -> dict[str, Any]:
    return {
        "id": sl.pk,
        "service": service_json(sl.service),
        "quantity": orders.whole_quantity(sl.quantity),
        "state": str(orders.line_state(sl)),
        "billing_status": sl.billing_status,
        "fulfilment_status": sl.fulfilment_status,
        "payer": name_json(sl.payer),
        "authorized": orders.line_status(sl).authorized,
        "order_source": sl.order_source,
        "ordered_at": sl.ordered_at,
        "pre_approval_ref": sl.pre_approval_ref,
        "draft_invoice_id": holders.get(sl.pk),
    }


def _unbilled_rows(visit: Visit) -> list[dict[str, Any]]:
    rows = list(billing.unbilled_lines(visit).select_related("service", "payer", "authorization"))
    holders = _draft_holders(sl.pk for sl in rows)
    return [_line_json(sl, holders) for sl in rows]


def unbilled(visit_id: int) -> list[dict[str, Any]]:
    """The visit's requested lines the cashier can invoice (FLOW step 4)."""
    return _unbilled_rows(Visit.objects.get(pk=visit_id))


def _requires_preapproval(il: InvoiceLine) -> bool:
    if il.payer is None or il.excluded:
        return False
    return catalog.resolve_coverage(il.payer, il.service).requires_preapproval


def _credited_by_line(invoice: Invoice) -> dict[int, int]:
    rows = (
        InvoiceLine.objects.filter(invoice=invoice)
        .filter(credit_lines__credit_note__status=DocumentStatus.APPROVED)
        .values("id")
        .annotate(units=Sum("credit_lines__quantity"))
    )
    return {r["id"]: int(r["units"] or 0) for r in rows}


def _payments_on(invoice: Invoice) -> list[dict[str, Any]]:
    pm = _payment_models()
    rows = (
        pm.Allocation.objects.filter(invoice=invoice)
        .values("payment_id", "payment__number", "payment__method", "payment__verification")
        .annotate(total=Sum("amount"))
        .order_by("payment_id")
    )
    return [
        {
            "payment_id": r["payment_id"],
            "number": r["payment__number"],
            "method": r["payment__method"],
            "verification": r["payment__verification"],
            "amount": _m(r["total"]),
        }
        for r in rows
        if r["total"] != 0
    ]


def invoice_json(inv: Invoice) -> dict[str, Any]:
    """One invoice with its lines, positions, payments and credit notes."""
    lines = list(
        inv.lines.select_related(
            "service",
            "payer",
            "discount_reason",
            "discount_approved_by",
            "service_line__service",
            "service_line__authorization",
        ).order_by("line_no")
    )
    position = None
    if inv.status == DocumentStatus.APPROVED:
        position = billing.invoice_position(inv)
    outstanding_by_line = (
        {lp.position: lp.outstanding for lp in position.lines} if position is not None else {}
    )
    credited = _credited_by_line(inv) if inv.status == DocumentStatus.APPROVED else {}
    line_rows = []
    for il in lines:
        line_rows.append(
            {
                "id": il.pk,
                "line_no": il.line_no,
                "service_line_id": il.service_line_id,
                "service": service_json(il.service),
                "description_ar": il.description_ar,
                "description_en": il.description_en,
                "quantity": orders.whole_quantity(il.quantity),
                "unit_price": _m(il.unit_price),
                "gross": _m(il.gross),
                "discount": _m(il.discount),
                "discount_percent": (
                    None if il.discount_percent is None else str(il.discount_percent.normalize())
                ),
                "discount_reason": reason_json(il.discount_reason),
                "discount_note": il.discount_note,
                "discount_approved_by": user_json(il.discount_approved_by),
                "payer": name_json(il.payer),
                "payer_share": _m(il.payer_share),
                "patient_share": _m(il.patient_share),
                "excluded": il.excluded,
                "pre_approval_ref": il.pre_approval_ref,
                "requires_pre_approval": _requires_preapproval(il),
                "state": str(orders.line_state(il.service_line)),
                "credited_quantity": credited.get(il.pk, 0),
                "outstanding": money_str(outstanding_by_line.get(il.line_no)),
            }
        )
    notes = inv.credit_notes.exclude(status=DocumentStatus.VOID).order_by("id")
    return {
        "id": inv.pk,
        "number": inv.number,
        "status": inv.status,
        "visit_id": inv.visit_id,
        "visit_number": inv.visit.number,
        "patient": patient_json(inv.patient),
        "priced_on": inv.priced_on,
        "created_at": inv.created_at,
        "created_by": user_json(inv.created_by),
        "approved_at": inv.approved_at,
        "approved_by": user_json(inv.approved_by),
        "gross_total": _m(inv.gross_total),
        "discount_total": _m(inv.discount_total),
        "payer_total": _m(inv.payer_total),
        "patient_total": _m(inv.patient_total),
        "outstanding": money_str(position.outstanding) if position is not None else None,
        "paid": money_str(position.applied) if position is not None else None,
        "lines": line_rows,
        "payments": _payments_on(inv) if position is not None else [],
        "credit_notes": [
            {
                "id": cn.pk,
                "number": cn.number,
                "status": cn.status,
                "gross_total": _m(cn.gross_total),
                "patient_total": _m(cn.patient_total),
                "created_at": cn.created_at,
            }
            for cn in notes
        ],
    }


def _invoices(qs: QuerySet[Invoice]) -> list[Invoice]:
    return list(qs.select_related("visit", "patient", "created_by", "approved_by").order_by("id"))


def invoice_detail(invoice_id: int) -> dict[str, Any]:
    """One invoice (draft, approved or void) with its lines, payments and credit notes."""
    inv = Invoice.objects.select_related("visit", "patient", "created_by", "approved_by").get(
        pk=invoice_id
    )
    return invoice_json(inv)


def center_json() -> dict[str, Any]:
    c = CenterProfile.load()
    return {
        "name_ar": c.name_ar,
        "name_en": c.name_en,
        "address": c.address,
        "phone": c.phone,
        "registration_no": c.registration_no,
        "tax_no": c.tax_no,
    }


def invoice_print(invoice_id: int) -> dict[str, Any]:
    """An invoice for printing (A4 or 80 mm, FEATURES 0.10): the document and the header."""
    return {"center": center_json(), "invoice": invoice_detail(invoice_id)}


def visit_billing(visit_id: int) -> dict[str, Any]:
    """Everything the billing panel shows for one visit (FLOW step 4)."""
    visit = Visit.objects.select_related(
        "patient", "department", "doctor__user", "payer", "coverage"
    ).get(pk=visit_id)
    patient = visit.patient
    on = timezone.localdate(visit.created_at)
    payers = {c.payer_id: c.payer for c in patients.coverages_valid_on(patient, on)}
    invoices = _invoices(Invoice.objects.filter(visit=visit).exclude(status=DocumentStatus.VOID))
    return {
        "patient": patient_json(patient),
        "visit": visit_ref_json(visit),
        "payers": [name_json(p) for p in payers.values() if p.active],
        "unbilled": _unbilled_rows(visit),
        "drafts": [invoice_json(i) for i in invoices if i.status == DocumentStatus.DRAFT],
        "invoices": [invoice_json(i) for i in invoices if i.status == DocumentStatus.APPROVED],
        "balance": balance_json(patient),
        "open_invoices": _open_invoices_json(patient),
    }


# --- credit notes ----------------------------------------------------------------------------


def _released(cn: CreditNote) -> Decimal:
    pm = _payment_models()
    total = pm.Allocation.objects.filter(credit_note=cn).aggregate(s=Sum("amount"))["s"]
    return -(total or ZERO)


def credit_note_json(cn: CreditNote) -> dict[str, Any]:
    pm = _payment_models()
    refunds = list(pm.Refund.objects.filter(credit_note=cn).order_by("id"))
    released = _released(cn)
    used = sum((r.amount for r in refunds if r.status != pm.RefundStatus.REJECTED), ZERO)
    return {
        "id": cn.pk,
        "number": cn.number,
        "status": cn.status,
        "invoice_id": cn.invoice_id,
        "invoice_number": cn.invoice.number,
        "patient": patient_json(cn.patient),
        "reason": reason_json(cn.reason_code),
        "reason_note": cn.reason_note,
        "created_by": user_json(cn.created_by),
        "created_at": cn.created_at,
        "approved_by": user_json(cn.approved_by),
        "approved_at": cn.approved_at,
        "gross_total": _m(cn.gross_total),
        "discount_total": _m(cn.discount_total),
        "payer_total": _m(cn.payer_total),
        "patient_total": _m(cn.patient_total),
        "released": _m(released),
        "refundable": _m(max(released - used, ZERO)),
        "lines": [
            {
                "id": cl.pk,
                "line_no": cl.line_no,
                "invoice_line_id": cl.invoice_line_id,
                "service": service_json(cl.invoice_line.service),
                "quantity": orders.whole_quantity(cl.quantity),
                "gross": _m(cl.gross),
                "discount": _m(cl.discount),
                "payer_share": _m(cl.payer_share),
                "patient_share": _m(cl.patient_share),
                "cancels_service_line": cl.cancels_service_line,
            }
            for cl in cn.lines.select_related("invoice_line__service").order_by("line_no")
        ],
        "refunds": [
            {"id": r.pk, "number": r.number, "status": r.status, "amount": _m(r.amount)}
            for r in refunds
        ],
    }


def _notes() -> QuerySet[CreditNote]:
    return CreditNote.objects.select_related(
        "invoice", "patient", "reason_code", "created_by", "approved_by"
    )


def credit_note_detail(credit_note_id: int) -> dict[str, Any]:
    return credit_note_json(_notes().get(pk=credit_note_id))


def credit_notes(
    *,
    status: str | None = None,
    invoice_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Credit notes, newest first: the supervisor's approval queue with ``status=draft``."""
    from api.pagination import paginate

    qs = _notes().order_by("-created_at", "-id")
    if status:
        qs = qs.filter(status=status)
    if invoice_id is not None:
        qs = qs.filter(invoice_id=invoice_id)
    if q:
        term = q.strip()
        qs = qs.filter(
            Q(number__iexact=term)
            | Q(invoice__number__iexact=term)
            | Q(patient__file_no__iexact=term)
        )
    page_data = paginate(qs, page, page_size)
    page_data["items"] = [credit_note_json(cn) for cn in page_data["items"]]
    return page_data


def credit_outcome_json(outcome: billing.CreditOutcome) -> dict[str, Any]:
    refund = outcome.refund
    return {
        "credit_note": credit_note_detail(outcome.credit_note.pk),
        "deallocated": _m(outcome.deallocated),
        "refund": (
            {
                "id": refund.pk,
                "number": refund.number,
                "status": refund.status,
                "amount": _m(refund.amount),
            }
            if refund is not None
            else None
        ),
        "replacement_line_ids": [ln.pk for ln in outcome.replacements],
    }


# --- reasons ---------------------------------------------------------------------------------


def reasons(category: str) -> list[dict[str, Any]]:
    """The active reasons of one cashier list (FEATURES 13.5), in display order."""
    if category not in REASON_CATEGORIES:
        return []
    rows = ReasonCode.objects.filter(category=category, active=True).order_by("sort_order", "code")
    return [r for r in (reason_json(x) for x in rows) if r is not None]
