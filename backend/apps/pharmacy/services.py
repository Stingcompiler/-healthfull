"""Pharmacy and inventory services: the stock engine (ARCHITECTURE 4.8, FEATURES 8).

Rules come from ``domain.stock`` (units, FEFO, never-negative, counts); this module loads
rows, locks them, calls the rule and writes ``StockMove`` rows. Invariant 5:

* Stock decrements only at dispense (and approved adjustments, count corrections and
  transfers), never at invoicing.
* Stock never goes negative. Every write locks the ``StockBalance`` rows it reads with
  ``SELECT ... FOR UPDATE`` (always in id order, so concurrent writers queue instead of
  deadlocking), checks the whole set of moves with ``domain.stock.apply_moves`` and only then
  inserts the moves. The ``stock_balance`` trigger and the ``qty_base >= 0`` CHECK on
  ``StockBalance`` are the database backstop.

Dispensing (FEATURES 8.3): only drug/consumable lines that are settled or under an unrevoked
perform-first authorization (invariant 1), FEFO batches by default; another batch needs a
reason (``override`` reason code) and ``pharmacy.override_batch``. A line can be dispensed in
parts: the remainder stays open (deferred) until dispensed, or ``complete=True`` closes the
line with what was given (the remainder goes back through ``orders.services`` for the credit
note and refund). A fully dispensed line is performed through ``orders.services.perform_line``.

Quantities are whole base units (e.g. tablets): ``UnitConversion.factor`` says how many base
units one pack unit holds.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import ModuleType

import pghistory
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, Exists, F, OuterRef, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import ServiceKind
from apps.core.models import ReasonCode, User
from apps.core.permissions import effective_permissions
from apps.core.services import next_number
from apps.orders.models import BillingStatus, FulfilmentStatus, PerformAuthorization, ServiceLine
from apps.pharmacy.models import (
    AdjustmentStatus,
    Batch,
    CountStatus,
    Dispense,
    DispenseLine,
    GoodsReceipt,
    GoodsReceiptLine,
    Item,
    ReceiptStatus,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockCount,
    StockCountLine,
    StockMove,
    StockTransfer,
    StockTransferLine,
    Store,
    Supplier,
    TransferStatus,
    UnitConversion,
)
from apps.visits.models import Visit
from domain import service_line as dsl
from domain import stock as ds
from domain.audit import Approval
from domain.errors import DomainError
from domain.money import q

__all__ = [
    "BatchPick",
    "DispenseRequest",
    "ExpiringBatch",
    "LowStockItem",
    "add_count_line",
    "add_receipt_line",
    "approve_adjustment",
    "batch_stock",
    "cancel_count",
    "cancel_receipt",
    "cancel_transfer",
    "count_variances",
    "create_receipt",
    "create_transfer",
    "dispense",
    "dispense_worklist",
    "dispensed_quantity",
    "expiring_batches",
    "item_factors",
    "low_stock",
    "on_hand",
    "post_count",
    "post_receipt",
    "receive_transfer",
    "record_count",
    "reject_adjustment",
    "request_adjustment",
    "send_transfer",
    "start_count",
    "suggest_batches",
    "to_base_units",
]

DISPENSABLE_KINDS = (ServiceKind.DRUG, ServiceKind.CONSUMABLE)


# --- helpers ------------------------------------------------------------------------------


def _orders() -> ModuleType:
    """``apps.orders.services`` (the write path for service line states)."""
    return importlib.import_module("apps.orders.services")


def _require_perm(actor: User, code: str) -> None:
    if code not in effective_permissions(actor):
        raise PermissionDenied(code)


def _reason(category: str, code: str | None, note: str) -> ReasonCode:
    if not code:
        raise DomainError("REASON_REQUIRED", "A reason is required for this action")
    reason = ReasonCode.objects.filter(category=category, code=code, active=True).first()
    if reason is None:
        raise DomainError(
            "REASON_UNKNOWN", "Unknown reason code", category=category, reason_code=code
        )
    if reason.requires_note and not note.strip():
        raise DomainError(
            "REASON_NOTE_REQUIRED", "This reason needs an explanation", reason_code=code
        )
    return reason


def _whole(value: Decimal | int, name: str = "quantity", *, minimum: int = 1) -> int:
    """A whole number of units (stock is counted in whole base units)."""
    if isinstance(value, bool):
        raise DomainError("INVALID_QUANTITY", f"{name} must be a whole number")
    dec = Decimal(value)
    if not dec.is_finite() or dec != dec.to_integral_value() or dec < minimum:
        raise DomainError(
            "INVALID_QUANTITY", f"{name} must be a whole number >= {minimum}", **{name: str(value)}
        )
    return int(dec)


def item_factors(item: Item) -> dict[str, int]:
    """Base units per unit of ``item``: ``{"tablet": 1, "strip": 10, "box": 30}``."""
    factors = {item.base_unit_code: 1}
    for unit_code, factor in UnitConversion.objects.filter(item=item).values_list(
        "unit_code", "factor"
    ):
        if factor != factor.to_integral_value() or factor < 1:
            raise DomainError(
                "INVALID_CONVERSION", "Unit factors are whole numbers >= 1", unit=unit_code
            )
        if unit_code == item.base_unit_code:
            if factor != 1:
                raise DomainError(
                    "INVALID_CONVERSION", "The base unit's factor is 1", unit=unit_code
                )
            continue
        factors[unit_code] = int(factor)
    return factors


def to_base_units(
    item: Item, quantity: Decimal | int, unit_code: str | None = None, *, dispensing: bool = False
) -> tuple[int, UnitConversion | None]:
    """``quantity`` of ``unit_code`` (base unit when None) in base units, and the unit row."""
    qty = _whole(quantity)
    if unit_code is None or unit_code == item.base_unit_code:
        return qty, None
    unit = UnitConversion.objects.filter(item=item, unit_code=unit_code).first()
    if unit is None:
        raise DomainError("UNIT_UNKNOWN", "Unknown unit for this item", unit=unit_code)
    if dispensing and not unit.is_dispensable:
        raise DomainError("UNIT_NOT_DISPENSABLE", "This unit is not dispensed", unit=unit_code)
    return ds.to_base(qty, unit_code, item_factors(item)), unit


def _lock_balances(store_ids: Iterable[int], item_ids: Iterable[int]) -> list[StockBalance]:
    return list(
        StockBalance.objects.select_for_update()
        .filter(store_id__in=list(store_ids), item_id__in=list(item_ids))
        .select_related("batch")
        .order_by("id")
    )


def _current(balances: Iterable[StockBalance]) -> dict[ds.StockKey, int]:
    return {(bl.item_id, bl.batch_id, bl.store_id): int(bl.qty_base) for bl in balances}


def _batch_stock(
    item_id: int, store_id: int, current: Mapping[ds.StockKey, int], expiry: Mapping[int, date]
) -> list[ds.BatchStock]:
    return [
        ds.BatchStock(batch_id, expiry[batch_id], qty)
        for (i, batch_id, s), qty in current.items()
        if i == item_id and s == store_id
    ]


def _write_moves(
    moves: Sequence[ds.StockMoveDraft],
    *,
    actor: User,
    source_type: str,
    source_id: int | None,
    note: str = "",
) -> list[StockMove]:
    costs = dict(
        Batch.objects.filter(pk__in={m.batch_id for m in moves}).values_list("pk", "unit_cost")
    )
    return [
        StockMove.objects.create(
            item_id=m.item_id,
            batch_id=m.batch_id,
            store_id=m.store_id,
            qty_base=Decimal(m.quantity),
            kind=str(m.kind),
            source_type=source_type,
            source_id=source_id,
            unit_cost=costs[m.batch_id],
            note=note[:300],
            created_by=actor,
        )
        for m in moves
    ]


def _apply(
    moves: Sequence[ds.StockMoveDraft],
    *,
    actor: User,
    source_type: str,
    source_id: int | None,
    note: str = "",
) -> list[StockMove]:
    """Lock, check (never negative) and write a set of moves atomically."""
    if not moves:
        return []
    balances = _lock_balances({m.store_id for m in moves}, {m.item_id for m in moves})
    ds.apply_moves(_current(balances), moves)
    return _write_moves(moves, actor=actor, source_type=source_type, source_id=source_id, note=note)


# --- queries --------------------------------------------------------------------------------


def on_hand(item: Item, store: Store | None = None) -> int:
    """Total on-hand of ``item`` in base units (one store or all)."""
    qs = StockBalance.objects.filter(item=item)
    if store is not None:
        qs = qs.filter(store=store)
    total = qs.aggregate(t=Sum("qty_base"))["t"]
    return int(total or 0)


def batch_stock(item: Item, store: Store) -> list[ds.BatchStock]:
    """Batches of ``item`` in ``store`` with their on-hand, FEFO order not applied."""
    return [
        ds.BatchStock(bl.batch_id, bl.batch.expiry_date, int(bl.qty_base))
        for bl in StockBalance.objects.filter(item=item, store=store).select_related("batch")
    ]


def suggest_batches(
    item: Item, store: Store, quantity: int, *, today: date | None = None
) -> tuple[ds.Pick, ...]:
    """The FEFO suggestion for dispensing ``quantity`` base units (FEATURES 8.2)."""
    return ds.select_batches(batch_stock(item, store), quantity, today or timezone.localdate())


@dataclass(frozen=True, slots=True)
class ExpiringBatch:
    batch: Batch
    store_id: int
    on_hand: int
    days_left: int


def expiring_batches(
    *, days: int, store: Store | None = None, today: date | None = None
) -> list[ExpiringBatch]:
    """Batches with stock expiring within ``days`` (expired included), soonest first (8.8)."""
    on = today or timezone.localdate()
    qs = StockBalance.objects.filter(qty_base__gt=0).select_related("batch", "batch__item")
    if store is not None:
        qs = qs.filter(store=store)
    rows = {(bl.batch_id, bl.store_id): bl for bl in qs}
    hits = ds.expiring_within(
        [
            ds.BatchStock(bl.batch_id, bl.batch.expiry_date, int(bl.qty_base))
            for bl in rows.values()
        ],
        on,
        days,
    )
    by_batch: dict[int, list[StockBalance]] = defaultdict(list)
    for bl in rows.values():
        by_batch[bl.batch_id].append(bl)
    out: list[ExpiringBatch] = []
    seen: set[tuple[int, int]] = set()
    for hit in hits:
        for bl in by_batch[hit.batch_id]:
            key = (bl.batch_id, bl.store_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ExpiringBatch(
                    bl.batch, bl.store_id, int(bl.qty_base), (bl.batch.expiry_date - on).days
                )
            )
    return out


@dataclass(frozen=True, slots=True)
class LowStockItem:
    item: Item
    on_hand: int
    min_stock: int
    suggested_order: int


def low_stock(*, store: Store | None = None) -> list[LowStockItem]:
    """Active items at or below their minimum, with a reorder suggestion (FEATURES 8.9).

    The suggestion is the item's ``reorder_qty`` when set, otherwise enough to reach twice
    the minimum.
    """
    balance_filter = Q(balances__store=store) if store is not None else Q()
    items = (
        Item.objects.filter(active=True, min_stock__gt=0)
        .annotate(
            total=Coalesce(
                Sum("balances__qty_base", filter=balance_filter),
                Value(Decimal(0)),
                output_field=DecimalField(),
            )
        )
        .order_by("generic_name", "id")
    )
    out: list[LowStockItem] = []
    for it in items:
        total = int(it.total)
        minimum = int(it.min_stock)
        if not ds.is_low_stock(total, minimum):
            continue
        reorder = int(it.reorder_qty) or max(2 * minimum - total, 0)
        out.append(LowStockItem(it, total, minimum, reorder))
    return out


def dispensed_quantity(line: ServiceLine) -> int:
    total = DispenseLine.objects.filter(service_line=line).aggregate(t=Sum("qty_base"))["t"]
    return int(total or 0)


def _active_authorization() -> Exists:
    return Exists(
        PerformAuthorization.objects.filter(
            pk=OuterRef("authorization_id"), revoked_at__isnull=True
        )
    )


def dispense_worklist(*, visit: Visit | None = None) -> QuerySet[ServiceLine]:
    """Drug and consumable lines that may be dispensed now (FEATURES 4.3, 8.3).

    Paid (settled) or perform-first authorized, not yet performed or cancelled, with
    ``dispensed`` (base units already given) and ``remaining`` annotated.
    """
    qs = (
        ServiceLine.objects.filter(
            kind__in=DISPENSABLE_KINDS,
            fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        )
        .filter(Q(billing_status=BillingStatus.SETTLED) | _active_authorization())
        .annotate(
            dispensed=Coalesce(
                Sum("dispense_lines__qty_base"), Value(Decimal(0)), output_field=DecimalField()
            )
        )
        .annotate(remaining=F("quantity") - F("dispensed"))
        .select_related("visit", "visit__patient", "service")
        .order_by("ordered_at", "id")
    )
    if visit is not None:
        qs = qs.filter(visit=visit)
    return qs


# --- goods receipts -------------------------------------------------------------------------


def create_receipt(
    *,
    supplier: Supplier,
    store: Store,
    actor: User,
    supplier_invoice_no: str = "",
    supplier_invoice_date: date | None = None,
    note: str = "",
) -> GoodsReceipt:
    """A draft goods receipt (FEATURES 8.5)."""
    if not store.active:
        raise DomainError("STORE_INACTIVE", "The store is inactive")
    try:
        with transaction.atomic(), pghistory.context(user=actor.pk, reason="goods receipt"):
            return GoodsReceipt.objects.create(
                number=next_number("GRN"),
                supplier=supplier,
                store=store,
                supplier_invoice_no=supplier_invoice_no.strip(),
                supplier_invoice_date=supplier_invoice_date,
                note=note[:500],
                created_by=actor,
            )
    except IntegrityError as exc:
        if "pharmacy_receipt_supplier_invoice_once" in str(exc):
            raise DomainError(
                "SUPPLIER_INVOICE_DUPLICATE", "This supplier invoice was already received"
            ) from exc
        raise


def add_receipt_line(
    receipt: GoodsReceipt,
    *,
    item: Item,
    batch_no: str,
    expiry_date: date,
    quantity: Decimal | int,
    unit_cost: Decimal,
    unit_code: str | None = None,
    actor: User,
    today: date | None = None,
) -> GoodsReceiptLine:
    """Add a line: ``quantity`` of ``unit_code`` at ``unit_cost`` per that unit.

    Raises:
        DomainError: ``DOCUMENT_FINAL`` (receipt not draft), ``BATCH_EXPIRED``,
            ``INVALID_QUANTITY``, ``UNIT_UNKNOWN``, ``INVALID_COST``, ``BATCH_NO_REQUIRED``.
    """
    if not batch_no.strip():
        raise DomainError("BATCH_NO_REQUIRED", "A batch number is required")
    if expiry_date < (today or timezone.localdate()):
        raise DomainError("BATCH_EXPIRED", "Expired goods cannot be received")
    if not isinstance(unit_cost, Decimal) or not unit_cost.is_finite() or unit_cost < 0:
        raise DomainError("INVALID_COST", "Unit cost must be a non-negative amount")
    qty_base, unit = to_base_units(item, quantity, unit_code)
    qty_units = _whole(quantity)
    factor = Decimal(qty_base // qty_units)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="goods receipt line"):
        locked = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
        if locked.status != ReceiptStatus.DRAFT:
            raise DomainError("DOCUMENT_FINAL", "Only a draft receipt can change")
        return GoodsReceiptLine.objects.create(
            receipt=locked,
            item=item,
            batch_no=batch_no.strip(),
            expiry_date=expiry_date,
            unit=unit,
            quantity_units=Decimal(qty_units),
            qty_base=Decimal(qty_base),
            unit_cost=(unit_cost / factor).quantize(Decimal("0.0001")),
            line_total=q(unit_cost * qty_units),
        )


def post_receipt(receipt: GoodsReceipt, *, actor: User, today: date | None = None) -> GoodsReceipt:
    """Post a draft receipt: batches are found or created and stock is received."""
    on = today or timezone.localdate()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="post receipt"):
        locked = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
        if locked.status != ReceiptStatus.DRAFT:
            raise DomainError("DOCUMENT_FINAL", "Only a draft receipt can be posted")
        lines = list(locked.lines.select_for_update().order_by("id"))
        if not lines:
            raise DomainError("RECEIPT_EMPTY", "The receipt has no lines")
        moves: list[tuple[GoodsReceiptLine, ds.StockMoveDraft]] = []
        for line in lines:
            batch, _ = Batch.objects.get_or_create(
                item_id=line.item_id,
                batch_no=line.batch_no,
                expiry_date=line.expiry_date,
                defaults={
                    "unit_cost": line.unit_cost,
                    "supplier_id": locked.supplier_id,
                    "received_on": on,
                },
            )
            line.batch = batch
            line.save(update_fields=["batch"])
            moves.append(
                (
                    line,
                    ds.StockMoveDraft(
                        line.item_id,
                        batch.pk,
                        locked.store_id,
                        _whole(line.qty_base),
                        ds.MoveKind.RECEIPT,
                    ),
                )
            )
        for line, move in moves:
            _write_moves([move], actor=actor, source_type="receipt_line", source_id=line.pk)
        locked.total_cost = q(sum((ln.line_total for ln in lines), Decimal(0)))
        locked.status = ReceiptStatus.POSTED
        locked.posted_by = actor
        locked.posted_at = timezone.now()
        locked.save(update_fields=["total_cost", "status", "posted_by", "posted_at"])
    return locked


def cancel_receipt(receipt: GoodsReceipt, *, actor: User) -> GoodsReceipt:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cancel receipt"):
        locked = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
        if locked.status != ReceiptStatus.DRAFT:
            raise DomainError("DOCUMENT_FINAL", "Only a draft receipt can be cancelled")
        locked.status = ReceiptStatus.CANCELLED
        locked.save(update_fields=["status"])
    return locked


# --- dispensing -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchPick:
    """``quantity`` base units from ``batch_id`` (a pharmacist's batch choice)."""

    batch_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class DispenseRequest:
    """Dispense ``quantity`` of ``unit_code`` (base unit when None) for one service line.

    ``batches`` overrides the FEFO suggestion (needs ``override_reason_code``).
    ``complete`` closes the line with what has been dispensed so far plus this quantity;
    the rest is cancelled and refunded (out of stock). Without it a partial dispense leaves
    the remainder open (deferred).
    """

    service_line_id: int
    quantity: Decimal | int
    unit_code: str | None = None
    batches: Sequence[BatchPick] | None = None
    override_reason_code: str | None = None
    override_note: str = ""
    complete: bool = False
    complete_reason_code: str = "OUT_OF_STOCK"


@dataclass(slots=True)
class _Planned:
    request: DispenseRequest
    line: ServiceLine
    item: Item
    unit: UnitConversion | None
    picks: tuple[ds.Pick, ...]
    fefo: tuple[ds.Pick, ...] | None
    override_reason: ReasonCode | None
    qty_base: int


def _line_status(line: ServiceLine) -> dsl.LineStatus:
    authorized = (
        line.authorization_id is not None
        and PerformAuthorization.objects.filter(
            pk=line.authorization_id, revoked_at__isnull=True
        ).exists()
    )
    return dsl.LineStatus(
        dsl.BillingStatus(line.billing_status),
        dsl.FulfilmentStatus(line.fulfilment_status),
        authorized=authorized,
    )


def dispense(
    *,
    visit: Visit,
    store: Store,
    actor: User,
    requests: Sequence[DispenseRequest],
    note: str = "",
    today: date | None = None,
) -> Dispense:
    """Dispense paid (or authorized) drug lines of one visit from ``store`` (FEATURES 8.2-8.4).

    All requests succeed or none does. Raises:
        DomainError: ``STORE_CANNOT_DISPENSE``, ``DISPENSE_EMPTY``, ``DUPLICATE_LINE``,
            ``LINE_NOT_ON_VISIT``, ``LINE_NOT_DISPENSABLE``, ``ITEM_NOT_STOCKED``,
            ``LINE_NOT_ELIGIBLE`` (not paid nor authorized, or already performed/cancelled),
            ``DISPENSE_EXCEEDS_LINE``, ``STOCK_INSUFFICIENT``, ``BATCH_EXPIRED``,
            ``BATCH_UNKNOWN``, ``OVERRIDE_QUANTITY_MISMATCH``, ``REASON_REQUIRED``,
            ``UNIT_UNKNOWN``, ``UNIT_NOT_DISPENSABLE``, ``INVALID_QUANTITY``.
        PermissionDenied: a batch override without ``pharmacy.override_batch``.
    """
    if not requests:
        raise DomainError("DISPENSE_EMPTY", "Nothing to dispense")
    line_ids = [r.service_line_id for r in requests]
    if len(set(line_ids)) != len(line_ids):
        raise DomainError("DUPLICATE_LINE", "A line appears twice in one dispense")
    on = today or timezone.localdate()
    now = timezone.now()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="dispense"):
        st = Store.objects.get(pk=store.pk)
        if not st.active or not st.allows_dispense:
            raise DomainError("STORE_CANNOT_DISPENSE", "This store does not dispense")
        lines = {
            ln.pk: ln
            for ln in ServiceLine.objects.select_for_update().filter(pk__in=line_ids).order_by("id")
        }
        items: dict[int, Item] = {}
        for line_id in line_ids:
            line = lines.get(line_id)
            if line is None or line.visit_id != visit.pk:
                raise DomainError(
                    "LINE_NOT_ON_VISIT", "The line is not on this visit", line_id=line_id
                )
            if line.kind not in DISPENSABLE_KINDS:
                raise DomainError(
                    "LINE_NOT_DISPENSABLE", "Only drug and consumable lines are dispensed"
                )
            item = Item.objects.filter(service_id=line.service_id).first()
            if item is None:
                raise DomainError(
                    "ITEM_NOT_STOCKED", "The service has no stock item", line_id=line_id
                )
            if not dsl.can_enter_worklist(_line_status(line)):
                raise DomainError(
                    "LINE_NOT_ELIGIBLE",
                    "The line is not paid nor authorized, or is already closed",
                    line_id=line_id,
                    billing=line.billing_status,
                    fulfilment=line.fulfilment_status,
                )
            items[line_id] = item

        balances = _lock_balances([st.pk], {it.pk for it in items.values()})
        current = _current(balances)
        expiry = {bl.batch_id: bl.batch.expiry_date for bl in balances}
        already = {ln_id: dispensed_quantity(lines[ln_id]) for ln_id in line_ids}

        planned: list[_Planned] = []
        for req in sorted(requests, key=lambda r: r.service_line_id):
            line, item = lines[req.service_line_id], items[req.service_line_id]
            qty_base, unit = to_base_units(item, req.quantity, req.unit_code, dispensing=True)
            ordered = _whole(line.quantity, "line quantity")
            remaining = ordered - already[line.pk]
            if qty_base > remaining:
                raise DomainError(
                    "DISPENSE_EXCEEDS_LINE",
                    "More than the line still needs",
                    line_id=line.pk,
                    remaining=remaining,
                    requested=qty_base,
                )
            batches = _batch_stock(item.pk, st.pk, current, expiry)
            try:
                fefo: tuple[ds.Pick, ...] | None = ds.select_batches(batches, qty_base, on)
            except DomainError:
                fefo = None
            override = (
                [ds.Pick(p.batch_id, p.quantity) for p in req.batches]
                if req.batches is not None
                else None
            )
            reason: ReasonCode | None = None
            approval: Approval | None = None
            if override is not None and tuple(override) != fefo:
                _require_perm(actor, "pharmacy.override_batch")
                reason = _reason("override", req.override_reason_code, req.override_note)
                approval = Approval(actor.pk, now, req.override_note, reason.code)
            picks = ds.select_batches(batches, qty_base, on, override=override, approval=approval)
            current = ds.apply_moves(current, ds.dispense_moves(item.pk, st.pk, picks))
            planned.append(_Planned(req, line, item, unit, picks, fefo, reason, qty_base))

        record = Dispense.objects.create(
            number=next_number("DSP"), visit=visit, store=st, dispensed_by=actor, note=note[:500]
        )
        for p in planned:
            factor = int(p.unit.factor) if p.unit is not None else 1
            moves = _write_moves(
                ds.dispense_moves(p.item.pk, st.pk, p.picks),
                actor=actor,
                source_type="dispense",
                source_id=record.pk,
            )
            for pick, move in zip(p.picks, moves, strict=True):
                whole_units = pick.quantity % factor == 0
                DispenseLine.objects.create(
                    dispense=record,
                    service_line=p.line,
                    item=p.item,
                    batch_id=pick.batch_id,
                    unit=p.unit if whole_units else None,
                    quantity_units=Decimal(
                        pick.quantity // factor if whole_units else pick.quantity
                    ),
                    qty_base=Decimal(pick.quantity),
                    batch_override=p.override_reason is not None,
                    override_reason=p.override_reason,
                    override_note=p.request.override_note[:300] if p.override_reason else "",
                    stock_move=move,
                )

        for p in planned:
            given = already[p.line.pk] + p.qty_base
            ordered = _whole(p.line.quantity, "line quantity")
            if given == ordered:
                _orders().perform_line(p.line, actor)
            elif p.request.complete:
                _close_partially(
                    p.line,
                    actor=actor,
                    given=given,
                    reason_code=p.request.complete_reason_code,
                    note=p.request.override_note or note,
                )
    return record


def _close_partially(
    line: ServiceLine, *, actor: User, given: int, reason_code: str, note: str
) -> None:
    """A partial dispense that will not be completed: perform what was given, cancel the rest.

    The remainder's credit note and refund are the financial engine's (``orders.services``).
    """
    reason = _reason("line_cancel", reason_code, note)
    _orders().perform_line(line, actor, performed_quantity=Decimal(given), note=note)
    _orders().cancel_line_remainder(line, reason, actor, note=note)


# --- adjustments ----------------------------------------------------------------------------


def request_adjustment(
    *,
    store: Store,
    reason_code: str,
    lines: Sequence[tuple[int, int, str]],
    actor: User,
    note: str = "",
) -> StockAdjustment:
    """Request a stock correction (FEATURES 8.6): ``lines`` of (batch id, signed base qty,
    note). Nothing moves until a supervisor approves it.
    """
    reason = _reason("stock_adjust", reason_code, note)
    if not lines:
        raise DomainError("ADJUSTMENT_EMPTY", "The adjustment has no lines")
    seen: set[int] = set()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="request adjustment"):
        adj = StockAdjustment.objects.create(
            number=next_number("ADJ"),
            store=store,
            reason_code=reason,
            note=note,
            requested_by=actor,
        )
        for batch_id, qty, line_note in lines:
            if batch_id in seen:
                raise DomainError("DUPLICATE_BATCH", "A batch appears twice", batch_id=batch_id)
            seen.add(batch_id)
            ds.validate_move(ds.MoveKind.ADJUSTMENT, qty)
            batch = Batch.objects.filter(pk=batch_id).first()
            if batch is None:
                raise DomainError("BATCH_UNKNOWN", "Unknown batch", batch_id=batch_id)
            StockAdjustmentLine.objects.create(
                adjustment=adj,
                item_id=batch.item_id,
                batch=batch,
                qty_base=Decimal(qty),
                note=line_note[:300],
            )
    return adj


def _decide(adjustment: StockAdjustment, actor: User) -> StockAdjustment:
    _require_perm(actor, "pharmacy.approve_adjustment")
    locked = StockAdjustment.objects.select_for_update().get(pk=adjustment.pk)
    if locked.status != AdjustmentStatus.DRAFT:
        raise DomainError("DOCUMENT_FINAL", "The adjustment was already decided")
    if locked.requested_by_id == actor.pk:
        raise DomainError("SELF_APPROVAL", "Another user must approve this adjustment")
    return locked


def approve_adjustment(
    adjustment: StockAdjustment, *, actor: User, note: str = ""
) -> StockAdjustment:
    """Supervisor approval posts the adjustment moves (never below zero)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="approve adjustment"):
        locked = _decide(adjustment, actor)
        reason = locked.reason_code
        approval = Approval(actor.pk, timezone.now(), note or locked.note, reason.code)
        lines = list(locked.lines.order_by("id"))
        balances = _lock_balances([locked.store_id], {ln.item_id for ln in lines})
        current = _current(balances)
        moves = []
        for ln in lines:
            key = (ln.item_id, ln.batch_id, locked.store_id)
            move = ds.adjustment_move(
                ln.item_id,
                ln.batch_id,
                locked.store_id,
                _whole(ln.qty_base, "qty_base", minimum=-(10**12)),
                available=current.get(key, 0),
                approval=approval,
            )
            current = ds.apply_moves(current, [move])
            moves.append(move)
        _write_moves(
            moves, actor=actor, source_type="adjustment", source_id=locked.pk, note=reason.code
        )
        locked.status = AdjustmentStatus.APPROVED
        locked.decided_by = actor
        locked.decided_at = approval.at
        locked.decision_note = note
        locked.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    return locked


def reject_adjustment(adjustment: StockAdjustment, *, actor: User, note: str) -> StockAdjustment:
    if not note.strip():
        raise DomainError("REASON_REQUIRED", "A rejection needs a reason")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="reject adjustment"):
        locked = _decide(adjustment, actor)
        locked.status = AdjustmentStatus.REJECTED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        locked.decision_note = note.strip()
        locked.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    return locked


# --- stock counts ---------------------------------------------------------------------------


def start_count(
    store: Store, *, actor: User, items: Iterable[Item] | None = None, note: str = ""
) -> StockCount:
    """Open a count session: the book quantity of every batch in the store is snapshotted.

    Stock should not move in the store while counting; corrections are ``counted - book``.
    """
    try:
        with transaction.atomic(), pghistory.context(user=actor.pk, reason="start count"):
            count = StockCount.objects.create(
                number=next_number("CNT"), store=store, note=note, started_by=actor
            )
            balances = StockBalance.objects.filter(store=store).order_by("item_id", "batch_id")
            if items is not None:
                balances = balances.filter(item__in=list(items))
            StockCountLine.objects.bulk_create(
                [
                    StockCountLine(
                        count=count, item_id=bl.item_id, batch_id=bl.batch_id, book_qty=bl.qty_base
                    )
                    for bl in balances
                    if bl.qty_base > 0 or items is not None
                ]
            )
    except IntegrityError as exc:
        if "pharmacy_count_one_open_per_store" in str(exc):
            raise DomainError(
                "COUNT_ALREADY_OPEN", "A count is already open in this store"
            ) from exc
        raise
    return count


def _open_count(count: StockCount) -> StockCount:
    locked = StockCount.objects.select_for_update().get(pk=count.pk)
    if locked.status != CountStatus.OPEN:
        raise DomainError("DOCUMENT_FINAL", "The count is closed")
    return locked


def add_count_line(count: StockCount, *, batch: Batch, actor: User) -> StockCountLine:
    """A batch found while counting that was not in the snapshot (book = current on-hand)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="count line"):
        locked = _open_count(count)
        existing = StockCountLine.objects.filter(count=locked, batch=batch).first()
        if existing is not None:
            return existing
        book = StockBalance.objects.filter(batch=batch, store_id=locked.store_id).first()
        return StockCountLine.objects.create(
            count=locked,
            item_id=batch.item_id,
            batch=batch,
            book_qty=book.qty_base if book is not None else Decimal(0),
        )


def record_count(
    count: StockCount, *, batch: Batch, counted_qty: int, actor: User, note: str = ""
) -> StockCountLine:
    """Enter (or correct) the counted quantity of a batch in base units."""
    counted = _whole(counted_qty, "counted_qty", minimum=0)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="record count"):
        _open_count(count)
        line = StockCountLine.objects.filter(count=count, batch=batch).first()
        if line is None:
            line = add_count_line(count, batch=batch, actor=actor)
        line.counted_qty = Decimal(counted)
        line.counted_by = actor
        line.counted_at = timezone.now()
        line.note = note[:300]
        line.save(update_fields=["counted_qty", "counted_by", "counted_at", "note"])
    return line


@dataclass(frozen=True, slots=True)
class CountVariance:
    line: StockCountLine
    variance: int
    value: Decimal


def count_variances(count: StockCount) -> list[CountVariance]:
    """Counted minus book per batch with its cost value (FEATURES 8.7 variance report)."""
    out = []
    for line in count.lines.select_related("batch").order_by("id"):
        if line.counted_qty is None:
            continue
        variance = ds.CountLine(
            line.item_id,
            line.batch_id,
            count.store_id,
            _whole(line.book_qty, "book_qty", minimum=0),
            _whole(line.counted_qty, "counted_qty", minimum=0),
        ).variance
        out.append(CountVariance(line, variance, q(line.batch.unit_cost * variance)))
    return out


def post_count(count: StockCount, *, actor: User) -> StockCount:
    """Post count corrections for every variance (``pharmacy.post_count``)."""
    _require_perm(actor, "pharmacy.post_count")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="post count"):
        locked = _open_count(count)
        lines = list(locked.lines.order_by("id"))
        uncounted = [ln.batch_id for ln in lines if ln.counted_qty is None]
        if uncounted:
            raise DomainError("COUNT_INCOMPLETE", "Some batches are not counted", batches=uncounted)
        moves = ds.count_adjustments(
            ds.CountLine(
                ln.item_id,
                ln.batch_id,
                locked.store_id,
                _whole(ln.book_qty, "book_qty", minimum=0),
                _whole(ln.counted_qty or 0, "counted_qty", minimum=0),
            )
            for ln in lines
        )
        _apply(moves, actor=actor, source_type="count", source_id=locked.pk)
        locked.status = CountStatus.POSTED
        locked.posted_by = actor
        locked.posted_at = timezone.now()
        locked.save(update_fields=["status", "posted_by", "posted_at"])
    return locked


def cancel_count(count: StockCount, *, actor: User) -> StockCount:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cancel count"):
        locked = _open_count(count)
        locked.status = CountStatus.CANCELLED
        locked.save(update_fields=["status"])
    return locked


# --- transfers ------------------------------------------------------------------------------


def create_transfer(
    *,
    from_store: Store,
    to_store: Store,
    lines: Sequence[tuple[int, int]],
    actor: User,
    note: str = "",
) -> StockTransfer:
    """A draft transfer of ``lines`` (batch id, base qty) between stores (FEATURES 8.10)."""
    if from_store.pk == to_store.pk:
        raise DomainError("TRANSFER_SAME_STORE", "Source and destination stores must differ")
    if not lines:
        raise DomainError("TRANSFER_EMPTY", "The transfer has no lines")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create transfer"):
        transfer = StockTransfer.objects.create(
            number=next_number("TRF"),
            from_store=from_store,
            to_store=to_store,
            note=note[:500],
            created_by=actor,
        )
        seen: set[int] = set()
        for batch_id, qty in lines:
            if batch_id in seen:
                raise DomainError("DUPLICATE_BATCH", "A batch appears twice", batch_id=batch_id)
            seen.add(batch_id)
            batch = Batch.objects.filter(pk=batch_id).first()
            if batch is None:
                raise DomainError("BATCH_UNKNOWN", "Unknown batch", batch_id=batch_id)
            StockTransferLine.objects.create(
                transfer=transfer, item_id=batch.item_id, batch=batch, qty_base=Decimal(_whole(qty))
            )
    return transfer


def send_transfer(transfer: StockTransfer, *, actor: User) -> StockTransfer:
    """Stock leaves the source store (in transit until received)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="send transfer"):
        locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if locked.status != TransferStatus.DRAFT:
            raise DomainError("DOCUMENT_FINAL", "Only a draft transfer can be sent")
        lines = list(locked.lines.order_by("id"))
        balances = _lock_balances([locked.from_store_id], {ln.item_id for ln in lines})
        current = _current(balances)
        outs = []
        for ln in lines:
            key = (ln.item_id, ln.batch_id, locked.from_store_id)
            out, _ = ds.transfer_moves(
                ln.item_id,
                ln.batch_id,
                from_store=locked.from_store_id,
                to_store=locked.to_store_id,
                quantity=_whole(ln.qty_base),
                available=current.get(key, 0),
            )
            current = ds.apply_moves(current, [out])
            outs.append(out)
        _write_moves(outs, actor=actor, source_type="transfer", source_id=locked.pk)
        locked.status = TransferStatus.SENT
        locked.sent_by = actor
        locked.sent_at = timezone.now()
        locked.save(update_fields=["status", "sent_by", "sent_at"])
    return locked


def receive_transfer(transfer: StockTransfer, *, actor: User) -> StockTransfer:
    """Stock arrives in the destination store."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="receive transfer"):
        locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if locked.status != TransferStatus.SENT:
            raise DomainError("TRANSFER_NOT_SENT", "Only a sent transfer can be received")
        moves = [
            ds.StockMoveDraft(
                ln.item_id,
                ln.batch_id,
                locked.to_store_id,
                _whole(ln.qty_base),
                ds.MoveKind.TRANSFER_IN,
            )
            for ln in locked.lines.order_by("id")
        ]
        _write_moves(moves, actor=actor, source_type="transfer", source_id=locked.pk)
        locked.status = TransferStatus.RECEIVED
        locked.received_by = actor
        locked.received_at = timezone.now()
        locked.save(update_fields=["status", "received_by", "received_at"])
    return locked


def cancel_transfer(transfer: StockTransfer, *, actor: User) -> StockTransfer:
    """Cancel a draft transfer (a sent transfer must be received)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cancel transfer"):
        locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if locked.status != TransferStatus.DRAFT:
            raise DomainError("DOCUMENT_FINAL", "Only a draft transfer can be cancelled")
        locked.status = TransferStatus.CANCELLED
        locked.save(update_fields=["status"])
    return locked
