"""Read services of the pharmacy screens (FEATURES 8.1-8.10, 5.12).

Each function loads what one screen shows and returns plain dicts shaped like
``apps.pharmacy.schemas``. No rule is decided here: eligibility (invariant 1), FEFO, open
units, variances and reorder suggestions come from ``apps.pharmacy.services``,
``apps.orders.services`` and ``domain.stock``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Prefetch, Q, QuerySet, Sum
from django.utils import timezone

from api.pagination import paginate
from apps.billing.models import CreditNoteLine, DocumentStatus, Invoice
from apps.catalog import services as catalog
from apps.catalog.models import Service
from apps.core.models import Policy, ReasonCode, User
from apps.orders.models import PrescriptionDetail, ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.pharmacy import services as ps
from apps.pharmacy.models import (
    Dispense,
    DispenseLine,
    DispenseReturn,
    GoodsReceipt,
    Item,
    StockAdjustment,
    StockBalance,
    StockCount,
    StockTransfer,
    Store,
    Supplier,
    UnitConversion,
)
from apps.visits.models import Visit
from domain import stock as ds
from domain.errors import DomainError
from domain.money import q as money_q

__all__ = [
    "adjustment_detail",
    "adjustments",
    "count_detail",
    "counts",
    "dispense_detail",
    "dispense_visit",
    "expiry",
    "item_detail",
    "items",
    "low_stock",
    "options",
    "queue",
    "receipt_detail",
    "receipts",
    "returnable_dispense",
    "returnable_dispenses",
    "sale_customers",
    "sale_services",
    "scan",
    "stock_card",
    "stock_services",
    "store_batches",
    "suppliers",
    "transfer_detail",
    "transfers",
]

#: Visits listed in the dispense queue at most (oldest orders first).
QUEUE_LIMIT = 100
#: Rows of a picker list (sale services, customers, batches).
PICKER_LIMIT = 30
#: Most recent moves shown on a stock card (balances still count the whole history).
STOCK_CARD_LIMIT = 500


# --- shapes -----------------------------------------------------------------------------------


def _name(row: Any) -> dict[str, Any]:
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


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


def _store(store: Store) -> dict[str, Any]:
    return {**_name(store), "kind": store.kind, "allows_dispense": store.allows_dispense}


def _supplier(s: Supplier) -> dict[str, Any]:
    return {**_name(s), "contact_name": s.contact_name, "phone": s.phone}


def _unit(u: UnitConversion) -> dict[str, Any]:
    return {
        "id": u.pk,
        "unit_code": u.unit_code,
        "name_ar": u.name_ar,
        "name_en": u.name_en,
        "factor": int(u.factor),
        "barcode": u.barcode,
        "is_dispensable": u.is_dispensable,
        "is_purchase_unit": u.is_purchase_unit,
    }


def _item_name(item: Item) -> str:
    return " ".join(p for p in (item.generic_name, item.strength) if p)


def _item_name_ar(item: Item) -> str:
    """The Arabic screens' name: the Arabic generic name when set, else the Latin one."""
    return " ".join(p for p in (item.generic_name_ar or item.generic_name, item.strength) if p)


def _cost(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'))}"


def _money(value: Decimal) -> str:
    return f"{money_q(value)}"


def _batch_row(balance: StockBalance, today: date) -> dict[str, Any]:
    batch = balance.batch
    return {
        "batch_id": batch.pk,
        "batch_no": batch.batch_no,
        "expiry_date": batch.expiry_date,
        "unit_cost": _cost(batch.unit_cost),
        "store_id": balance.store_id,
        "on_hand": int(balance.qty_base),
        "expired": not ds.is_usable(batch.expiry_date, today),
        "days_left": (batch.expiry_date - today).days,
    }


def _items_qs() -> QuerySet[Item]:
    return (
        Item.objects.select_related("service")
        .prefetch_related(Prefetch("units", queryset=UnitConversion.objects.order_by("factor")))
        .annotate(total=Sum("balances__qty_base"))
    )


def _item_row(item: Item) -> dict[str, Any]:
    total = int(getattr(item, "total", None) or 0)
    return {
        "id": item.pk,
        "service": _name(item.service),
        "generic_name": item.generic_name,
        "generic_name_ar": item.generic_name_ar,
        "brand_name": item.brand_name,
        "form": item.form,
        "strength": item.strength,
        "base_unit_code": item.base_unit_code,
        "base_unit_name_ar": item.base_unit_name_ar,
        "base_unit_name_en": item.base_unit_name_en,
        "barcode": item.barcode,
        "min_stock": int(item.min_stock),
        "reorder_qty": int(item.reorder_qty),
        "storage": item.storage,
        "is_controlled": item.is_controlled,
        "active": item.active,
        "on_hand": total,
        "low": item.min_stock > 0 and ds.is_low_stock(total, int(item.min_stock)),
        "units": [_unit(u) for u in item.units.all()],
    }


def _patient(p: Patient) -> dict[str, Any]:
    return {
        "id": p.pk,
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
    }


# --- reference --------------------------------------------------------------------------------


def _reasons(category: str) -> list[dict[str, Any]]:
    rows = ReasonCode.objects.filter(category=category, active=True).order_by("sort_order", "code")
    return [r for r in (_reason(x) for x in rows) if r is not None]


def options() -> dict[str, Any]:
    stores = list(Store.objects.filter(active=True).order_by("code"))
    default = next((s.pk for s in stores if s.allows_dispense), None)
    return {
        "stores": [_store(s) for s in stores],
        "suppliers": suppliers(),
        "reasons_override": _reasons("override"),
        "reasons_stock_adjust": _reasons("stock_adjust"),
        "reasons_line_cancel": _reasons("line_cancel"),
        "partial_dispense_remainder": Policy.load().partial_dispense_remainder,
        "default_store_id": default,
    }


def suppliers() -> list[dict[str, Any]]:
    return [_supplier(s) for s in Supplier.objects.filter(active=True).order_by("code")]


# --- items ------------------------------------------------------------------------------------


def items(
    *,
    q: str | None,
    page: int,
    page_size: int,
    low_only: bool = False,
    active: bool | None = None,
) -> dict[str, Any]:
    """Stock items by name, brand, service code or barcode (exact, items and pack units)."""
    qs = _items_qs().order_by("generic_name", "id")
    term = (q or "").strip()
    if term:
        # Match in a subquery: joining the pack units next to the on-hand Sum would count each
        # balance once per unit.
        matching = Item.objects.filter(
            Q(generic_name__icontains=term)
            | Q(generic_name_ar__icontains=term)
            | Q(brand_name__icontains=term)
            | Q(service__code__iexact=term)
            | Q(barcode=term)
            | Q(units__barcode=term)
        ).values("pk")
        qs = qs.filter(pk__in=matching)
    if active is not None:
        qs = qs.filter(active=active)
    rows = [_item_row(it) for it in qs]
    if low_only:
        rows = [r for r in rows if r["low"]]
    return paginate(rows, page, page_size)


def item_detail(item_id: int, *, today: date | None = None) -> dict[str, Any]:
    on = today or timezone.localdate()
    item = _items_qs().get(pk=item_id)
    balances = (
        StockBalance.objects.filter(item=item, qty_base__gt=0)
        .select_related("batch")
        .order_by("batch__expiry_date", "batch_id", "store_id")
    )
    return {**_item_row(item), "batches": [_batch_row(b, on) for b in balances]}


def stock_services() -> list[dict[str, Any]]:
    """Drug and consumable services without a stock item (for a new item)."""
    rows = Service.objects.filter(
        kind__in=ps.DISPENSABLE_KINDS, active=True, stock_item__isnull=True
    ).order_by("code")
    return [{**_name(s), "kind": s.kind} for s in rows]


def scan(code: str) -> dict[str, Any]:
    """The item a barcode names (``BARCODE_UNKNOWN`` otherwise)."""
    found = ps.find_by_barcode(code)
    if found is None:
        raise DomainError("BARCODE_UNKNOWN", "No item or unit has this barcode", barcode=code)
    item, unit = found
    return {
        "item": _item_row(_items_qs().get(pk=item.pk)),
        "unit_code": unit.unit_code if unit is not None else None,
    }


def stock_card(item_id: int, *, store_id: int | None) -> dict[str, Any]:
    item = _items_qs().get(pk=item_id)
    store = Store.objects.get(pk=store_id) if store_id is not None else None
    rows = ps.stock_card(item, store=store)
    return {
        "item": _item_row(item),
        "store_id": store_id,
        "rows": [
            {
                "id": r.move.pk,
                "moved_at": r.move.moved_at,
                "kind": r.move.kind,
                "qty_base": int(r.move.qty_base),
                "balance": r.balance,
                "batch_balance": r.batch_balance,
                "batch_no": r.move.batch.batch_no,
                "expiry_date": r.move.batch.expiry_date,
                "store": _name(r.move.store),
                "source_type": r.move.source_type,
                "source_id": r.move.source_id,
                "note": r.move.note,
                "created_by": _user(r.move.created_by),
            }
            for r in list(reversed(rows))[:STOCK_CARD_LIMIT]  # newest first on screen
        ],
    }


def store_batches(
    *, store_id: int, q: str | None = None, item_id: int | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    """Batches with stock in a store (pickers of adjustments, transfers and counts)."""
    on = today or timezone.localdate()
    qs = (
        StockBalance.objects.filter(store_id=store_id, qty_base__gt=0)
        .select_related("batch", "item")
        .order_by("item__generic_name", "batch__expiry_date", "batch_id")
    )
    if item_id is not None:
        qs = qs.filter(item_id=item_id)
    term = (q or "").strip()
    if term:
        qs = qs.filter(
            Q(item__generic_name__icontains=term)
            | Q(item__generic_name_ar__icontains=term)
            | Q(item__brand_name__icontains=term)
            | Q(batch__batch_no__iexact=term)
            | Q(item__barcode=term)
            | Q(item__units__barcode=term)
        ).distinct()
    return [
        {
            **_batch_row(bl, on),
            "item_id": bl.item_id,
            "item_name": _item_name(bl.item),
            "item_name_ar": _item_name_ar(bl.item),
            "base_unit_name_ar": bl.item.base_unit_name_ar,
            "base_unit_name_en": bl.item.base_unit_name_en,
        }
        for bl in qs[:200]
    ]


# --- dispensing -------------------------------------------------------------------------------


def _prescription(line: ServiceLine) -> dict[str, Any] | None:
    try:
        rx: PrescriptionDetail = line.prescription
    except PrescriptionDetail.DoesNotExist:
        return None
    return {
        "dose": rx.dose,
        "route": rx.route,
        "frequency_code": rx.frequency_code,
        "frequency_per_day": None if rx.frequency_per_day is None else str(rx.frequency_per_day),
        "duration_days": rx.duration_days,
        "as_needed": rx.as_needed,
        "instructions": rx.instructions,
    }


def _queue_line(line: ServiceLine, item: Item | None) -> dict[str, Any]:
    return {
        "id": line.pk,
        "service": _name(line.service),
        "kind": line.kind,
        "item_id": item.pk if item is not None else None,
        "base_unit_name_ar": item.base_unit_name_ar if item is not None else "",
        "base_unit_name_en": item.base_unit_name_en if item is not None else "",
        "quantity": int(line.quantity),
        "dispensed": int(getattr(line, "dispensed", 0)),
        "remaining": max(int(getattr(line, "remaining", 0)), 0),
        "authorized": line.billing_status != "settled",
        "started": line.fulfilment_status == "in_progress",
        "ordered_at": line.ordered_at,
        "note": line.order_note,
        "prescription": _prescription(line),
    }


def _search_visits(qs: QuerySet[ServiceLine], term: str) -> QuerySet[ServiceLine]:
    """Lines of visits matching a typed or scanned term: visit, file, invoice number, phone
    or name (a barcode scanner types the number and Enter)."""
    invoice_visits = Invoice.objects.filter(number__iexact=term).values("visit_id")
    phone = patients.normalize_phone(term)
    match = (
        Q(visit__number__iexact=term)
        | Q(visit__patient__file_no__iexact=term)
        | Q(visit_id__in=invoice_visits)
        | Q(visit__patient__full_name_ar__icontains=term)
        | Q(visit__patient__full_name_en__icontains=term)
    )
    if len(phone) >= 6:
        match |= Q(visit__patient__phone_norm__contains=phone)
    return qs.filter(match)


def queue(*, q: str | None = None) -> list[dict[str, Any]]:
    """Visits with drug and consumable lines that may be dispensed now (FEATURES 8.3).

    Only paid or perform-first authorized open lines (``services.dispense_worklist``,
    invariant 1), grouped by visit, oldest order first. Lines with nothing left to give
    (every open unit credited) are left out.
    """
    lines = ps.dispense_worklist().select_related("prescription")
    term = (q or "").strip()
    if term:
        lines = _search_visits(lines, term)
    by_visit: dict[int, list[ServiceLine]] = defaultdict(list)
    order: list[int] = []
    for line in lines:
        if int(line.remaining) <= 0:  # type: ignore[attr-defined]
            continue
        if line.visit_id not in by_visit:
            order.append(line.visit_id)
        by_visit[line.visit_id].append(line)
    order = order[:QUEUE_LIMIT]
    stock_items = {
        it.service_id: it
        for it in Item.objects.filter(
            service_id__in={ln.service_id for v in order for ln in by_visit[v]}
        )
    }
    out = []
    for visit_id in order:
        group = by_visit[visit_id]
        visit = group[0].visit
        out.append(
            {
                "visit_id": visit.pk,
                "visit_number": visit.number,
                "visit_type": visit.visit_type,
                "created_at": visit.created_at,
                "patient": _patient(visit.patient),
                "lines": [_queue_line(ln, stock_items.get(ln.service_id)) for ln in group],
            }
        )
    return out


def _dispense_store(store_id: int | None) -> Store:
    if store_id is not None:
        return Store.objects.get(pk=store_id)
    found = Store.objects.filter(active=True, allows_dispense=True).order_by("code").first()
    if found is None:
        raise DomainError("STORE_CANNOT_DISPENSE", "No store dispenses")
    return found


def dispense_visit(
    visit_id: int, *, store_id: int | None, today: date | None = None
) -> dict[str, Any]:
    """A visit's dispensable lines with units, the store's batches and the FEFO suggestion."""
    on = today or timezone.localdate()
    visit = Visit.objects.select_related("patient").get(pk=visit_id)
    store = _dispense_store(store_id)
    lines = [
        ln
        for ln in ps.dispense_worklist(visit=visit).select_related("prescription")
        if int(ln.remaining) > 0  # type: ignore[attr-defined]
    ]
    stock_items = {
        it.service_id: it
        for it in Item.objects.filter(
            service_id__in={ln.service_id for ln in lines}
        ).prefetch_related(Prefetch("units", queryset=UnitConversion.objects.order_by("factor")))
    }
    balances: dict[int, list[StockBalance]] = defaultdict(list)
    for bl in (
        StockBalance.objects.filter(
            store=store, item_id__in=[it.pk for it in stock_items.values()], qty_base__gt=0
        )
        .select_related("batch")
        .order_by("batch__expiry_date", "batch_id")
    ):
        balances[bl.item_id].append(bl)
    out_lines = []
    for line in lines:
        item = stock_items.get(line.service_id)
        row = _queue_line(line, item)
        rows = balances.get(item.pk, []) if item is not None else []
        stock = [ds.BatchStock(bl.batch_id, bl.batch.expiry_date, int(bl.qty_base)) for bl in rows]
        available = sum(b.on_hand for b in ds.fefo_order(stock, on))
        fefo = None
        if item is not None and row["remaining"] > 0:
            try:
                picks = ds.select_batches(stock, row["remaining"], on)
                fefo = [{"batch_id": p.batch_id, "quantity": p.quantity} for p in picks]
            except DomainError:
                fefo = None
        out_lines.append(
            {
                **row,
                "units": [_unit(u) for u in item.units.all()] if item is not None else [],
                "batches": [_batch_row(bl, on) for bl in rows],
                "fefo": fefo,
                "available": available,
            }
        )
    return {
        "visit_id": visit.pk,
        "visit_number": visit.number,
        "visit_type": visit.visit_type,
        "created_at": visit.created_at,
        "patient": _patient(visit.patient),
        "store": _store(store),
        "lines": out_lines,
    }


def dispense_detail(dispense_id: int) -> dict[str, Any]:
    d = Dispense.objects.select_related("visit", "store", "dispensed_by").get(pk=dispense_id)
    lines = d.lines.select_related(
        "service_line__service", "batch", "unit", "override_reason"
    ).order_by("id")
    return {
        "id": d.pk,
        "number": d.number,
        "visit_id": d.visit_id,
        "visit_number": d.visit.number,
        "store": _store(d.store),
        "dispensed_by": _user(d.dispensed_by),
        "dispensed_at": d.dispensed_at,
        "lines": [
            {
                "id": ln.pk,
                "service_line_id": ln.service_line_id,
                "service": _name(ln.service_line.service),
                "batch_no": ln.batch.batch_no,
                "expiry_date": ln.batch.expiry_date,
                "unit_code": ln.unit.unit_code if ln.unit is not None else None,
                "quantity_units": int(ln.quantity_units),
                "qty_base": int(ln.qty_base),
                "batch_override": ln.batch_override,
                "override_reason": ln.override_reason.code if ln.override_reason else None,
            }
            for ln in lines
        ],
    }


# --- returns (ADR 0018) -----------------------------------------------------------------------

#: Dispenses older than this are not offered for returns on the screen (searchable by number).
RETURN_WINDOW_DAYS = 30


def _returnable_qs() -> QuerySet[Dispense]:
    return Dispense.objects.select_related("visit__patient", "store", "dispensed_by").order_by(
        "-dispensed_at", "-id"
    )


def returnable_dispense(dispense_id: int) -> dict[str, Any]:
    """One dispense for the returns screen: per line what was given, what came back, what may
    still come back, whether a second person must approve (a billed line) and the approved
    credit notes that credit the line (to link the return to the refund)."""
    d = _returnable_qs().get(pk=dispense_id)
    return _returnable_rows([d])[0]


def returnable_dispenses(*, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    """Recent dispenses (last ``RETURN_WINDOW_DAYS`` days), newest first; ``q`` matches the
    dispense or visit number, the patient's file number or name (any age)."""
    qs = _returnable_qs()
    term = (q or "").strip()
    if term:
        qs = qs.filter(
            Q(number__icontains=term)
            | Q(visit__number__icontains=term)
            | Q(visit__patient__file_no__icontains=term)
            | Q(visit__patient__full_name_ar__icontains=term)
            | Q(visit__patient__full_name_en__icontains=term)
        )
    else:
        since = timezone.now() - timedelta(days=RETURN_WINDOW_DAYS)
        qs = qs.filter(dispensed_at__gte=since)
    result = paginate(qs, page, page_size)
    result["items"] = _returnable_rows(list(result["items"]))
    return result


def _returnable_rows(dispenses: Sequence[Dispense]) -> list[dict[str, Any]]:
    ids = [d.pk for d in dispenses]
    lines = list(
        DispenseLine.objects.filter(dispense_id__in=ids)
        .select_related("service_line__service", "batch", "unit")
        .order_by("id")
    )
    returns: dict[int, list[DispenseReturn]] = defaultdict(list)
    for r in (
        DispenseReturn.objects.filter(dispense_line__in=lines)
        .select_related("reason_code", "returned_by", "approved_by", "credit_note")
        .order_by("returned_at", "id")
    ):
        returns[r.dispense_line_id].append(r)
    notes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for line_id, cn_id, cn_number in (
        CreditNoteLine.objects.filter(
            invoice_line__service_line_id__in={ln.service_line_id for ln in lines},
            credit_note__status=DocumentStatus.APPROVED,
        )
        .order_by("credit_note_id")
        .values_list("invoice_line__service_line_id", "credit_note_id", "credit_note__number")
    ):
        if (line_id, cn_id) not in seen:
            seen.add((line_id, cn_id))
            notes[line_id].append({"id": cn_id, "number": cn_number})
    by_dispense: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ln in lines:
        back = returns.get(ln.pk, [])
        returned = sum(int(r.qty_base) for r in back)
        sl = ln.service_line
        by_dispense[ln.dispense_id].append(
            {
                "id": ln.pk,
                "service_line_id": ln.service_line_id,
                "service": _name(sl.service),
                "batch_no": ln.batch.batch_no,
                "expiry_date": ln.batch.expiry_date,
                "unit_code": ln.unit.unit_code if ln.unit is not None else None,
                "qty_base": int(ln.qty_base),
                "returned": returned,
                "returnable": max(int(ln.qty_base) - returned, 0),
                "billing_status": sl.billing_status,
                "needs_approver": sl.billing_status != "unbilled",
                "credit_notes": notes.get(ln.service_line_id, []),
                "returns": [
                    {
                        "number": r.number,
                        "qty_base": int(r.qty_base),
                        "reason": _reason(r.reason_code),
                        "note": r.note,
                        "returned_by": _user(r.returned_by),
                        "approved_by": _user(r.approved_by),
                        "returned_at": r.returned_at,
                        "credit_note_number": r.credit_note.number if r.credit_note else None,
                    }
                    for r in back
                ],
            }
        )
    return [
        {
            "id": d.pk,
            "number": d.number,
            "visit_id": d.visit_id,
            "visit_number": d.visit.number,
            "patient": _patient(d.visit.patient),
            "store": _store(d.store),
            "dispensed_by": _user(d.dispensed_by),
            "dispensed_at": d.dispensed_at,
            "lines": by_dispense.get(d.pk, []),
        }
        for d in dispenses
    ]


# --- documents --------------------------------------------------------------------------------


def _filtered[M: Any](qs: QuerySet[M], status: str | None, term: str | None) -> QuerySet[M]:
    if status:
        qs = qs.filter(status=status)
    if term and term.strip():
        qs = qs.filter(number__icontains=term.strip())
    return qs


def _item_names(ids: Iterable[int]) -> dict[int, Item]:
    return {it.pk: it for it in Item.objects.filter(pk__in=set(ids))}


def receipt_detail(receipt_id: int) -> dict[str, Any]:
    r = GoodsReceipt.objects.select_related("supplier", "store", "created_by", "posted_by").get(
        pk=receipt_id
    )
    lines = list(r.lines.select_related("item", "unit").order_by("id"))
    return {
        "id": r.pk,
        "number": r.number,
        "status": r.status,
        "supplier": _name(r.supplier),
        "store": _store(r.store),
        "supplier_invoice_no": r.supplier_invoice_no,
        "supplier_invoice_date": r.supplier_invoice_date,
        "note": r.note,
        "total_cost": _money(
            r.total_cost
            if r.status == "posted"
            else sum((ln.line_total for ln in lines), Decimal(0))
        ),
        "created_by": _user(r.created_by),
        "created_at": r.created_at,
        "posted_by": _user(r.posted_by),
        "posted_at": r.posted_at,
        "lines": [
            {
                "id": ln.pk,
                "item_id": ln.item_id,
                "item_name": _item_name(ln.item),
                "item_name_ar": _item_name_ar(ln.item),
                "batch_no": ln.batch_no,
                "expiry_date": ln.expiry_date,
                "unit_code": ln.unit.unit_code if ln.unit is not None else None,
                "quantity_units": int(ln.quantity_units),
                "qty_base": int(ln.qty_base),
                "unit_cost": _cost(ln.unit_cost),
                "line_total": _money(ln.line_total),
            }
            for ln in lines
        ],
    }


def receipts(*, status: str | None, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    qs = _filtered(GoodsReceipt.objects.order_by("-created_at", "-id"), status, q)
    result = paginate(qs, page, page_size)
    result["items"] = [receipt_detail(r.pk) for r in result["items"]]
    return result


def adjustment_detail(adjustment_id: int) -> dict[str, Any]:
    a = StockAdjustment.objects.select_related(
        "store", "reason_code", "requested_by", "decided_by"
    ).get(pk=adjustment_id)
    lines = list(a.lines.select_related("item", "batch").order_by("id"))
    return {
        "id": a.pk,
        "number": a.number,
        "status": a.status,
        "store": _store(a.store),
        "reason": _reason(a.reason_code),
        "note": a.note,
        "requested_by": _user(a.requested_by),
        "requested_at": a.requested_at,
        "decided_by": _user(a.decided_by),
        "decided_at": a.decided_at,
        "decision_note": a.decision_note,
        "lines": [
            {
                "id": ln.pk,
                "item_id": ln.item_id,
                "item_name": _item_name(ln.item),
                "item_name_ar": _item_name_ar(ln.item),
                "batch_id": ln.batch_id,
                "batch_no": ln.batch.batch_no,
                "expiry_date": ln.batch.expiry_date,
                "qty_base": int(ln.qty_base),
                "note": ln.note,
            }
            for ln in lines
        ],
    }


def adjustments(*, status: str | None, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    qs = _filtered(StockAdjustment.objects.order_by("-requested_at", "-id"), status, q)
    result = paginate(qs, page, page_size)
    result["items"] = [adjustment_detail(a.pk) for a in result["items"]]
    return result


def count_detail(count_id: int) -> dict[str, Any]:
    c = StockCount.objects.select_related("store", "started_by", "posted_by").get(pk=count_id)
    variances = {v.line.pk: v for v in ps.count_variances(c)}
    lines = list(
        c.lines.select_related("item", "batch", "counted_by").order_by(
            "item__generic_name", "batch__expiry_date", "id"
        )
    )
    total_value = sum((v.value for v in variances.values()), Decimal(0))
    return {
        "id": c.pk,
        "number": c.number,
        "status": c.status,
        "store": _store(c.store),
        "note": c.note,
        "started_by": _user(c.started_by),
        "started_at": c.started_at,
        "posted_by": _user(c.posted_by),
        "posted_at": c.posted_at,
        "counted": sum(1 for ln in lines if ln.counted_qty is not None),
        "total": len(lines),
        "variance_value": _money(total_value),
        "lines": [
            {
                "id": ln.pk,
                "item_id": ln.item_id,
                "item_name": _item_name(ln.item),
                "item_name_ar": _item_name_ar(ln.item),
                "base_unit_name_ar": ln.item.base_unit_name_ar,
                "base_unit_name_en": ln.item.base_unit_name_en,
                "batch_id": ln.batch_id,
                "batch_no": ln.batch.batch_no,
                "expiry_date": ln.batch.expiry_date,
                "book_qty": int(ln.book_qty),
                "counted_qty": None if ln.counted_qty is None else int(ln.counted_qty),
                "variance": variances[ln.pk].variance if ln.pk in variances else None,
                "variance_value": _money(variances[ln.pk].value) if ln.pk in variances else None,
                "counted_by": _user(ln.counted_by),
                "counted_at": ln.counted_at,
                "note": ln.note,
            }
            for ln in lines
        ],
    }


def counts(*, status: str | None, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    qs = _filtered(StockCount.objects.order_by("-started_at", "-id"), status, q)
    result = paginate(qs, page, page_size)
    result["items"] = [count_detail(c.pk) for c in result["items"]]
    return result


def transfer_detail(transfer_id: int) -> dict[str, Any]:
    t = StockTransfer.objects.select_related(
        "from_store",
        "to_store",
        "created_by",
        "sent_by",
        "received_by",
        "shortage_reason",
        "shortage_approved_by",
        "cancelled_by",
    ).get(pk=transfer_id)
    lines = list(t.lines.select_related("item", "batch").order_by("id"))
    return {
        "id": t.pk,
        "number": t.number,
        "status": t.status,
        "from_store": _store(t.from_store),
        "to_store": _store(t.to_store),
        "note": t.note,
        "created_by": _user(t.created_by),
        "created_at": t.created_at,
        "sent_by": _user(t.sent_by),
        "sent_at": t.sent_at,
        "received_by": _user(t.received_by),
        "received_at": t.received_at,
        "shortage_reason": _reason(t.shortage_reason),
        "shortage_note": t.shortage_note,
        "shortage_approved_by": _user(t.shortage_approved_by),
        "cancelled_by": _user(t.cancelled_by),
        "cancelled_at": t.cancelled_at,
        "cancel_note": t.cancel_note,
        "lines": [
            {
                "id": ln.pk,
                "item_id": ln.item_id,
                "item_name": _item_name(ln.item),
                "item_name_ar": _item_name_ar(ln.item),
                "batch_id": ln.batch_id,
                "batch_no": ln.batch.batch_no,
                "expiry_date": ln.batch.expiry_date,
                "qty_base": int(ln.qty_base),
            }
            for ln in lines
        ],
    }


def transfers(*, status: str | None, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    qs = _filtered(StockTransfer.objects.order_by("-created_at", "-id"), status, q)
    result = paginate(qs, page, page_size)
    result["items"] = [transfer_detail(t.pk) for t in result["items"]]
    return result


# --- reports ----------------------------------------------------------------------------------


def expiry(*, days: int, store_id: int | None, today: date | None = None) -> list[dict[str, Any]]:
    """Batches with stock expiring within ``days`` (expired included), soonest first (8.8)."""
    on = today or timezone.localdate()
    store = Store.objects.get(pk=store_id) if store_id is not None else None
    hits = ps.expiring_batches(days=days, store=store, today=on)
    stores = {s.pk: s for s in Store.objects.filter(pk__in={h.store_id for h in hits})}
    names = _item_names(h.batch.item_id for h in hits)
    return [
        {
            "batch_id": h.batch.pk,
            "batch_no": h.batch.batch_no,
            "expiry_date": h.batch.expiry_date,
            "days_left": h.days_left,
            "expired": h.days_left < 0,
            "item_id": h.batch.item_id,
            "item_name": _item_name(names[h.batch.item_id]),
            "item_name_ar": _item_name_ar(names[h.batch.item_id]),
            "base_unit_name_ar": names[h.batch.item_id].base_unit_name_ar,
            "base_unit_name_en": names[h.batch.item_id].base_unit_name_en,
            "store": _name(stores[h.store_id]),
            "on_hand": h.on_hand,
            "value": _money(h.batch.unit_cost * h.on_hand),
        }
        for h in hits
    ]


def low_stock(*, store_id: int | None) -> list[dict[str, Any]]:
    """Items at or below their minimum with the reorder suggestion (FEATURES 8.9)."""
    store = Store.objects.get(pk=store_id) if store_id is not None else None
    rows = ps.low_stock(store=store)
    services = dict(
        Service.objects.filter(pk__in={r.item.service_id for r in rows}).values_list("id", "code")
    )
    return [
        {
            "item_id": r.item.pk,
            "item_name": _item_name(r.item),
            "item_name_ar": _item_name_ar(r.item),
            "service_code": services.get(r.item.service_id, ""),
            "base_unit_name_ar": r.item.base_unit_name_ar,
            "base_unit_name_en": r.item.base_unit_name_en,
            "on_hand": r.on_hand,
            "min_stock": r.min_stock,
            "reorder_qty": int(r.item.reorder_qty),
            "suggested_order": r.suggested_order,
        }
        for r in rows
    ]


# --- walk-in sale -----------------------------------------------------------------------------


def sale_customers(q: str) -> list[dict[str, Any]]:
    """Existing files a walk-in sale may be billed to (the patient search of FEATURES 0.9)."""
    return [
        {
            "id": p.pk,
            "file_no": p.file_no,
            "full_name_ar": p.full_name_ar,
            "full_name_en": p.full_name_en,
            "phone": p.phone,
            "sex": p.sex,
        }
        for p in patients.search_patients(q, limit=PICKER_LIMIT)
    ]


def sale_services(q: str | None, *, today: date | None = None) -> list[dict[str, Any]]:
    """Drugs and consumables for sale with today's cash price and on-hand (FEATURES 5.12)."""
    on = today or timezone.localdate()
    qs = Service.objects.filter(kind__in=ps.DISPENSABLE_KINDS, active=True).order_by("code")
    term = (q or "").strip()
    if term:
        qs = qs.filter(
            Q(code__iexact=term)
            | Q(name_ar__icontains=term)
            | Q(name_en__icontains=term)
            | Q(stock_item__generic_name__icontains=term)
            | Q(stock_item__brand_name__icontains=term)
            | Q(stock_item__barcode=term)
            | Q(stock_item__units__barcode=term)
        ).distinct()
    services: Sequence[Service] = list(qs[:PICKER_LIMIT])
    try:
        version = catalog.effective_version(catalog.default_price_list(), on)
        prices = catalog.version_prices(version)
    except DomainError:  # no cash list effective today: nothing has a price
        prices = {}
    stock_items = {it.service_id: it for it in Item.objects.filter(service__in=services)}
    totals = dict(
        StockBalance.objects.filter(item__in=stock_items.values())
        .values("item_id")
        .annotate(t=Sum("qty_base"))
        .values_list("item_id", "t")
    )
    out = []
    for svc in services:
        item = stock_items.get(svc.pk)
        unit_price = prices.get(svc.pk)
        out.append(
            {
                "service_id": svc.pk,
                "code": svc.code,
                "name_ar": svc.name_ar,
                "name_en": svc.name_en,
                "kind": svc.kind,
                "unit_price": None if unit_price is None else _money(unit_price),
                "item_id": item.pk if item is not None else None,
                "base_unit_name_ar": item.base_unit_name_ar if item is not None else "",
                "base_unit_name_en": item.base_unit_name_en if item is not None else "",
                "on_hand": int(totals.get(item.pk, 0) or 0) if item is not None else 0,
            }
        )
    return out
