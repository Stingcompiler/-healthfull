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
reason (``override`` reason code) and ``pharmacy.override_batch``. Units an approved credit
note took back are never dispensed (``orders.services.open_units``). A line can be dispensed
in parts: the first part moves it to ``in_progress``; the remainder stays open (deferred)
until dispensed, or ``complete=True`` (default from ``Policy.partial_dispense_remainder``)
closes the line with what was given (the remainder goes back through ``orders.services`` for
the credit note, approved by a ``billing.approve_credit_note`` holder, and the refund). A
line whose units are all given is performed through ``orders.services.perform_line``.

Returns (:func:`return_dispense`) put units a patient brought back on the shelf with a
``return`` move; transfers can be cancelled after sending (stock goes back) and received
short with an approved, reasoned shortage (FEATURES 8.6, 8.10).

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
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, Exists, F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.billing.models import CreditNote, CreditNoteLine, DocumentStatus
from apps.catalog.models import Service, ServiceKind
from apps.core.models import PartialDispenseRemainder, Policy, ReasonCode, User
from apps.core.roles import PHARMACIST
from apps.core.services import next_number, notify_roles, require_permission, resolve_reason
from apps.orders.models import BillingStatus, FulfilmentStatus, PerformAuthorization, ServiceLine
from apps.pharmacy.models import (
    AdjustmentStatus,
    Batch,
    CountStatus,
    Dispense,
    DispenseLine,
    DispenseReturn,
    DosageForm,
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
    Storage,
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
    "StockCardRow",
    "add_count_line",
    "add_receipt_line",
    "add_unit",
    "approve_adjustment",
    "batch_stock",
    "cancel_count",
    "cancel_receipt",
    "cancel_transfer",
    "count_variances",
    "create_item",
    "create_receipt",
    "create_supplier",
    "create_transfer",
    "dispense",
    "dispense_worklist",
    "dispensed_quantity",
    "expiring_batches",
    "find_by_barcode",
    "item_factors",
    "low_stock",
    "on_hand",
    "post_count",
    "post_receipt",
    "receive_transfer",
    "record_count",
    "reject_adjustment",
    "request_adjustment",
    "return_dispense",
    "returned_quantity",
    "send_transfer",
    "start_count",
    "stock_card",
    "suggest_batches",
    "to_base_units",
    "update_item",
    "update_unit",
]

DISPENSABLE_KINDS = (ServiceKind.DRUG, ServiceKind.CONSUMABLE)


# --- helpers ------------------------------------------------------------------------------


def _orders() -> ModuleType:
    """``apps.orders.services`` (the write path for service line states)."""
    return importlib.import_module("apps.orders.services")


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


def _check_available(batch_id: int, store_id: int, needed: int) -> None:
    """Early check that ``needed`` base units of a batch are on hand in a store.

    Not a lock: the document's posting step checks again under ``FOR UPDATE`` (invariant 5).
    """
    row = StockBalance.objects.filter(batch_id=batch_id, store_id=store_id).first()
    available = int(row.qty_base) if row is not None else 0
    if needed > available:
        raise DomainError(
            "STOCK_INSUFFICIENT",
            "Stock cannot go negative",
            batch_id=batch_id,
            store_id=store_id,
            available=available,
            shortfall=needed - available,
        )


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
        reorder = ds.reorder_suggestion(total, minimum, int(it.reorder_qty))
        out.append(LowStockItem(it, total, minimum, reorder))
    return out


@dataclass(frozen=True, slots=True)
class StockCardRow:
    """One move of an item's stock card with the balances right after it."""

    move: StockMove
    balance: int
    batch_balance: int


def stock_card(item: Item, *, store: Store | None = None) -> list[StockCardRow]:
    """Every move of ``item`` (one store or all), oldest first, with running balances.

    ``balance`` is the item's on-hand after the move (in that store, or in every store);
    ``batch_balance`` the moved batch's on-hand in the move's store.
    """
    qs = StockMove.objects.filter(item=item).select_related("batch", "store", "created_by")
    if store is not None:
        qs = qs.filter(store=store)
    total = 0
    per_batch: dict[tuple[int, int], int] = defaultdict(int)
    rows: list[StockCardRow] = []
    for move in qs.order_by("moved_at", "id"):
        qty = int(move.qty_base)
        total += qty
        key = (move.batch_id, move.store_id)
        per_batch[key] += qty
        rows.append(StockCardRow(move, total, per_batch[key]))
    return rows


def dispensed_quantity(line: ServiceLine) -> int:
    """Base units handed out for the line (returns are counted apart)."""
    total = DispenseLine.objects.filter(service_line=line).aggregate(t=Sum("qty_base"))["t"]
    return int(total or 0)


def returned_quantity(line: ServiceLine) -> int:
    """Base units of the line a patient brought back (:func:`return_dispense`)."""
    total = DispenseReturn.objects.filter(dispense_line__service_line=line).aggregate(
        t=Sum("qty_base")
    )["t"]
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
            ),
            credited=Coalesce(
                Subquery(
                    CreditNoteLine.objects.filter(
                        invoice_line__service_line=OuterRef("pk"),
                        invoice_line__frozen=True,
                        credit_note__status=DocumentStatus.APPROVED,
                    )
                    .values("invoice_line__service_line")
                    .annotate(t=Sum("quantity"))
                    .values("t")
                ),
                Value(Decimal(0)),
                output_field=DecimalField(),
            ),
        )
        .annotate(remaining=F("quantity") - F("credited") - F("dispensed"))
        .select_related("visit", "visit__patient", "service")
        .order_by("ordered_at", "id")
    )
    if visit is not None:
        qs = qs.filter(visit=visit)
    return qs


# --- item master ----------------------------------------------------------------------------


#: Item fields a pharmacist may set at creation or edit later (FEATURES 8.1). The service and
#: the base unit code are fixed once the item exists: stock is counted in that unit.
ITEM_FIELDS = frozenset(
    {
        "generic_name",
        "brand_name",
        "form",
        "strength",
        "base_unit_name_ar",
        "base_unit_name_en",
        "barcode",
        "min_stock",
        "reorder_qty",
        "storage",
        "is_controlled",
        "active",
    }
)
UNIT_FIELDS = frozenset({"name_ar", "name_en", "barcode", "is_dispensable", "is_purchase_unit"})
SUPPLIER_FIELDS = frozenset({"contact_name", "phone", "address", "tax_no", "notes"})


def _check_barcode(code: str, *, item_id: int | None = None, unit_id: int | None = None) -> str:
    """``code`` stripped; refuses a barcode another item or pack unit already carries."""
    clean = code.strip()
    if not clean:
        return ""
    items = Item.objects.filter(barcode=clean)
    units = UnitConversion.objects.filter(barcode=clean)
    if item_id is not None:
        items = items.exclude(pk=item_id)
    if unit_id is not None:
        units = units.exclude(pk=unit_id)
    if items.exists() or units.exists():
        raise DomainError("BARCODE_TAKEN", "Another item or unit has this barcode", barcode=clean)
    return clean


def _item_values(fields: Mapping[str, object], *, item_id: int | None) -> dict[str, object]:
    """Validated item fields (choices, whole non-negative levels, unique barcode, names)."""
    unknown = sorted(set(fields) - ITEM_FIELDS)
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "These item fields cannot be set", fields=unknown)
    out: dict[str, object] = {}
    for name, value in fields.items():
        if name == "form":
            if value not in DosageForm.values:
                raise DomainError("INVALID_FORM", "Unknown dosage form", form=str(value))
            out[name] = value
        elif name == "storage":
            if value not in Storage.values:
                raise DomainError(
                    "INVALID_STORAGE", "Unknown storage condition", storage=str(value)
                )
            out[name] = value
        elif name in ("min_stock", "reorder_qty"):
            if not isinstance(value, int | Decimal | str):
                raise DomainError("INVALID_QUANTITY", f"{name} must be a whole number")
            out[name] = Decimal(_whole(Decimal(value), name, minimum=0))
        elif name == "barcode":
            out[name] = _check_barcode(str(value), item_id=item_id)
        elif name in ("is_controlled", "active"):
            out[name] = bool(value)
        elif name == "generic_name":
            text = str(value).strip()
            if not text:
                raise DomainError("NAME_REQUIRED", "The generic name is required")
            out[name] = text
        else:
            out[name] = str(value).strip()
    return out


def create_item(
    *,
    service: Service,
    generic_name: str,
    base_unit_code: str,
    base_unit_name_ar: str,
    base_unit_name_en: str,
    actor: User,
    **fields: object,
) -> Item:
    """A stock item for a drug or consumable catalog service (FEATURES 8.1).

    Raises:
        DomainError: ``SERVICE_NOT_STOCKABLE`` (the service is not a drug or consumable),
            ``ITEM_EXISTS``, ``NAME_REQUIRED``, ``UNIT_REQUIRED``, ``INVALID_FORM``,
            ``INVALID_STORAGE``, ``INVALID_QUANTITY``, ``BARCODE_TAKEN``,
            ``FIELD_NOT_EDITABLE``.
    """
    if service.kind not in DISPENSABLE_KINDS:
        raise DomainError(
            "SERVICE_NOT_STOCKABLE", "Only drug and consumable services have stock items"
        )
    if not generic_name.strip():
        raise DomainError("NAME_REQUIRED", "The generic name is required")
    if not base_unit_code.strip():
        raise DomainError("UNIT_REQUIRED", "The base unit is required")
    if Item.objects.filter(service=service).exists():
        raise DomainError("ITEM_EXISTS", "The service already has a stock item")
    values = _item_values(fields, item_id=None)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create item"):
        return Item.objects.create(
            service=service,
            generic_name=generic_name.strip(),
            base_unit_code=base_unit_code.strip(),
            base_unit_name_ar=base_unit_name_ar.strip(),
            base_unit_name_en=base_unit_name_en.strip(),
            **values,
        )


def update_item(item: Item, *, actor: User, **fields: object) -> Item:
    """Edit an item's master data (FEATURES 8.1); the service and base unit stay fixed.

    Raises:
        DomainError: ``FIELD_NOT_EDITABLE``, ``NAME_REQUIRED``, ``INVALID_FORM``,
            ``INVALID_STORAGE``, ``INVALID_QUANTITY``, ``BARCODE_TAKEN``.
    """
    values = _item_values(fields, item_id=item.pk)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit item"):
        locked = Item.objects.select_for_update().get(pk=item.pk)
        for name, value in values.items():
            setattr(locked, name, value)
        if values:
            locked.save(update_fields=[*values, "updated_at"])
    return locked


def find_by_barcode(code: str) -> tuple[Item, UnitConversion | None] | None:
    """The item a scanned barcode names, with the pack unit when it is a unit's barcode."""
    clean = code.strip()
    if not clean:
        return None
    item = Item.objects.filter(barcode=clean).first()
    if item is not None:
        return item, None
    unit = UnitConversion.objects.select_related("item").filter(barcode=clean).first()
    if unit is not None:
        return unit.item, unit
    return None


def add_unit(
    item: Item,
    *,
    unit_code: str,
    name_ar: str,
    name_en: str,
    factor: int,
    actor: User,
    is_dispensable: bool = True,
    is_purchase_unit: bool = False,
    barcode: str = "",
) -> UnitConversion:
    """A pack unit holding ``factor`` base units (box -> strip -> tablet, FEATURES 8.1).

    Raises:
        DomainError: ``INVALID_CONVERSION``, ``INVALID_QUANTITY``, ``BARCODE_TAKEN``.
    """
    code = unit_code.strip()
    whole = _whole(factor, "factor", minimum=2)
    if not code or code == item.base_unit_code:
        raise DomainError("INVALID_CONVERSION", "A pack unit differs from the base unit")
    if UnitConversion.objects.filter(item=item, unit_code=code).exists():
        raise DomainError("INVALID_CONVERSION", "The unit is already defined", unit=code)
    clean_barcode = _check_barcode(barcode)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="add unit"):
        return UnitConversion.objects.create(
            item=item,
            unit_code=code,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            factor=Decimal(whole),
            is_dispensable=is_dispensable,
            is_purchase_unit=is_purchase_unit,
            barcode=clean_barcode,
        )


def update_unit(unit: UnitConversion, *, actor: User, **fields: object) -> UnitConversion:
    """Rename a pack unit, set its barcode or its dispensing and purchase flags.

    The factor never changes: past moves and documents were converted with it.

    Raises:
        DomainError: ``FIELD_NOT_EDITABLE``, ``BARCODE_TAKEN``.
    """
    unknown = sorted(set(fields) - UNIT_FIELDS)
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "These unit fields cannot be set", fields=unknown)
    values: dict[str, object] = {}
    for name, value in fields.items():
        if name == "barcode":
            values[name] = _check_barcode(str(value), unit_id=unit.pk)
        elif name in ("is_dispensable", "is_purchase_unit"):
            values[name] = bool(value)
        else:
            values[name] = str(value).strip()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit unit"):
        locked = UnitConversion.objects.select_for_update().get(pk=unit.pk)
        for name, value in values.items():
            setattr(locked, name, value)
        if values:
            locked.save(update_fields=list(values))
    return locked


# --- suppliers ------------------------------------------------------------------------------


def create_supplier(
    *, code: str, name_ar: str, name_en: str, actor: User, **fields: str
) -> Supplier:
    """A supplier goods are received from (FEATURES 8.5).

    Raises:
        DomainError: ``CODE_REQUIRED``, ``NAME_REQUIRED``, ``SUPPLIER_EXISTS``,
            ``FIELD_NOT_EDITABLE``.
    """
    clean = code.strip().upper()
    if not clean:
        raise DomainError("CODE_REQUIRED", "A supplier code is required")
    if not name_ar.strip() and not name_en.strip():
        raise DomainError("NAME_REQUIRED", "A name in Arabic or English is required")
    unknown = sorted(set(fields) - SUPPLIER_FIELDS)
    if unknown:
        raise DomainError(
            "FIELD_NOT_EDITABLE", "These supplier fields cannot be set", fields=unknown
        )
    if Supplier.objects.filter(code=clean).exists():
        raise DomainError("SUPPLIER_EXISTS", "A supplier has this code", supplier=clean)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create supplier"):
        return Supplier.objects.create(
            code=clean,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            **{k: v.strip() for k, v in fields.items()},
        )


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
        _lock_balances([locked.store_id], {ln.item_id for ln in lines})  # writers queue in id order
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
    the rest is cancelled and refunded (out of stock). ``False`` leaves the remainder of a
    partial dispense open (deferred); ``None`` follows ``Policy.partial_dispense_remainder``
    (FLOW 6: the center decides).
    """

    service_line_id: int
    quantity: Decimal | int
    unit_code: str | None = None
    batches: Sequence[BatchPick] | None = None
    override_reason_code: str | None = None
    override_note: str = ""
    complete: bool | None = False
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


def _eligible(line: ServiceLine) -> bool:
    """``domain.service_line.can_enter_worklist`` with the authorization as locked and
    reloaded by ``orders.lock_lines`` (a revoked one no longer counts)."""
    auth = line.authorization if line.authorization_id is not None else None
    try:
        status = dsl.LineStatus(
            dsl.BillingStatus(line.billing_status),
            dsl.FulfilmentStatus(line.fulfilment_status),
            authorized=auth is not None and auth.revoked_at is None,
        )
    except DomainError:  # started work whose authorization was revoked behind its back
        return False
    return dsl.can_enter_worklist(status)


def dispense(
    *,
    visit: Visit,
    store: Store,
    actor: User,
    requests: Sequence[DispenseRequest],
    note: str = "",
    today: date | None = None,
    approver: User | None = None,
) -> Dispense:
    """Dispense paid (or authorized) drug lines of one visit from ``store`` (FEATURES 8.2-8.4).

    All requests succeed or none does. ``approver`` approves the credit note of a billed
    line closed with ``complete`` (default the actor; needs ``billing.approve_credit_note``).

    Raises:
        DomainError: ``STORE_CANNOT_DISPENSE``, ``DISPENSE_EMPTY``, ``DUPLICATE_LINE``,
            ``LINE_NOT_ON_VISIT``, ``LINE_NOT_DISPENSABLE``, ``ITEM_NOT_STOCKED``,
            ``LINE_NOT_ELIGIBLE`` (not paid nor authorized, or already performed/cancelled),
            ``DISPENSE_EXCEEDS_LINE`` (more than the line's units still billed and not
            given), ``STOCK_INSUFFICIENT``, ``BATCH_EXPIRED``, ``BATCH_UNKNOWN``,
            ``OVERRIDE_QUANTITY_MISMATCH``, ``REASON_REQUIRED``, ``UNIT_UNKNOWN``,
            ``UNIT_NOT_DISPENSABLE``, ``INVALID_QUANTITY``.
        PermissionDenied: a batch override without ``pharmacy.override_batch``; closing a
            billed line's remainder without ``billing.approve_credit_note``.
    """
    if not requests:
        raise DomainError("DISPENSE_EMPTY", "Nothing to dispense")
    line_ids = [r.service_line_id for r in requests]
    if len(set(line_ids)) != len(line_ids):
        raise DomainError("DUPLICATE_LINE", "A line appears twice in one dispense")
    on = today or timezone.localdate()
    now = timezone.now()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="dispense"):
        # Lock order of the money engine: patient, then service lines, then stock.
        _orders().lock_patient(visit.patient_id)
        st = Store.objects.get(pk=store.pk)
        if not st.active or not st.allows_dispense:
            raise DomainError("STORE_CANNOT_DISPENSE", "This store does not dispense")
        lines = {ln.pk: ln for ln in _orders().lock_lines(line_ids)}
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
            if not _eligible(line):
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
        before = _item_totals(current)
        expiry = {bl.batch_id: bl.batch.expiry_date for bl in balances}
        already = {ln_id: dispensed_quantity(lines[ln_id]) for ln_id in line_ids}
        # Units still to give: ordered less credited (refunded) and already given units.
        remaining_units = {ln_id: _orders().open_units(lines[ln_id]) for ln_id in line_ids}

        planned: list[_Planned] = []
        for req in sorted(requests, key=lambda r: r.service_line_id):
            line, item = lines[req.service_line_id], items[req.service_line_id]
            qty_base, unit = to_base_units(item, req.quantity, req.unit_code, dispensing=True)
            remaining = remaining_units[line.pk]
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
                require_permission(actor, "pharmacy.override_batch")
                reason = resolve_reason(req.override_reason_code, "override", req.override_note)
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

        _notify_low_stock(st, before, _item_totals(current), {it.pk: it for it in items.values()})

        refund_rest = Policy.load().partial_dispense_remainder == PartialDispenseRemainder.REFUND
        for p in planned:
            given = already[p.line.pk] + p.qty_base
            complete = refund_rest if p.request.complete is None else p.request.complete
            if p.qty_base == remaining_units[p.line.pk]:
                # Every unit still billed is now given (credited units never are); with
                # credited units the performed quantity is what was given.
                _orders().perform_line(p.line, actor)
            elif complete:
                _close_partially(
                    p.line,
                    actor=actor,
                    given=given,
                    reason_code=p.request.complete_reason_code,
                    note=p.request.override_note or note,
                    approver=approver,
                )
            elif p.line.fulfilment_status == FulfilmentStatus.PENDING:
                # The first part given: the doctor sees the order in progress, and the
                # perform-first authorization can no longer be withdrawn under it.
                _orders().start_line(p.line, actor)
    return record


def _item_totals(current: Mapping[ds.StockKey, int]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for (item_id, _batch, _store), qty in current.items():
        totals[item_id] += qty
    return dict(totals)


def _notify_low_stock(
    store: Store, before: Mapping[int, int], after: Mapping[int, int], items: Mapping[int, Item]
) -> None:
    """Tell pharmacists when an item crosses down to its minimum in a store (FEATURES 0.13)."""
    for item_id, item in items.items():
        minimum = int(item.min_stock)
        was, now = before.get(item_id, 0), after.get(item_id, 0)
        if minimum > 0 and not ds.is_low_stock(was, minimum) and ds.is_low_stock(now, minimum):
            notify_roles(
                [PHARMACIST],
                "stock_low",
                item_id=item_id,
                store_id=store.pk,
                on_hand=now,
                min_stock=minimum,
            )


def _close_partially(
    line: ServiceLine,
    *,
    actor: User,
    given: int,
    reason_code: str,
    note: str,
    approver: User | None = None,
) -> None:
    """A partial dispense that will not be completed: perform what was given, cancel the rest.

    The remainder's credit note and refund are the financial engine's (``orders.services``).
    """
    reason = resolve_reason(reason_code, "line_cancel", note)
    _orders().perform_line(line, actor, performed_quantity=Decimal(given), note=note)
    _orders().cancel_line_remainder(line, reason, actor, note=note, approver=approver)


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

    A decrease larger than the batch's on-hand in the store is refused now
    (``STOCK_INSUFFICIENT``); approval checks again under the row locks (invariant 5).
    """
    reason = resolve_reason(reason_code, "stock_adjust", note)
    if not lines:
        raise DomainError("ADJUSTMENT_EMPTY", "The adjustment has no lines")
    if not store.active:
        raise DomainError("STORE_INACTIVE", "The store is inactive")
    for batch_id, qty, _note in lines:
        _whole(qty, "qty_base", minimum=-(10**12))
        if qty < 0:
            _check_available(batch_id, store.pk, -qty)
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
    require_permission(actor, "pharmacy.approve_adjustment")
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
    """Open a count session listing every batch with stock in the store (or of ``items``).

    Each batch's book quantity is taken again when it is counted, and posting refuses a
    batch whose stock moved after it was counted (``COUNT_STOCK_MOVED``); corrections are
    ``counted - book``.
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
    """Enter (or correct) the counted quantity of a batch in base units.

    The line's book quantity is refreshed to the on-hand at this moment, so stock that moved
    since the session started (a dispense during the count) is not mistaken for a variance.
    """
    counted = _whole(counted_qty, "counted_qty", minimum=0)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="record count"):
        locked = _open_count(count)
        line = StockCountLine.objects.filter(count=locked, batch=batch).first()
        if line is None:
            line = add_count_line(locked, batch=batch, actor=actor)
        line.book_qty = Decimal(_book(batch.pk, locked.store_id))
        line.counted_qty = Decimal(counted)
        line.counted_by = actor
        line.counted_at = timezone.now()
        line.note = note[:300]
        line.save(update_fields=["book_qty", "counted_qty", "counted_by", "counted_at", "note"])
    return line


def _book(batch_id: int, store_id: int) -> int:
    row = StockBalance.objects.filter(batch_id=batch_id, store_id=store_id).first()
    return int(row.qty_base) if row is not None else 0


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
    require_permission(actor, "pharmacy.post_count")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="post count"):
        locked = _open_count(count)
        lines = list(locked.lines.order_by("id"))
        uncounted = [ln.batch_id for ln in lines if ln.counted_qty is None]
        if uncounted:
            raise DomainError("COUNT_INCOMPLETE", "Some batches are not counted", batches=uncounted)
        balances = _lock_balances([locked.store_id], {ln.item_id for ln in lines})
        current = _current(balances)
        moved = [
            ln.batch_id
            for ln in lines
            if current.get((ln.item_id, ln.batch_id, locked.store_id), 0) != int(ln.book_qty)
        ]
        if moved:
            raise DomainError(
                "COUNT_STOCK_MOVED",
                "Stock of these batches moved after they were counted; count them again",
                batches=moved,
            )
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
    """A draft transfer of ``lines`` (batch id, base qty) between stores (FEATURES 8.10).

    A line larger than the batch's on-hand in the source store is refused now
    (``STOCK_INSUFFICIENT``); sending checks again under the row locks (invariant 5).
    """
    if from_store.pk == to_store.pk:
        raise DomainError("TRANSFER_SAME_STORE", "Source and destination stores must differ")
    if not lines:
        raise DomainError("TRANSFER_EMPTY", "The transfer has no lines")
    if not from_store.active or not to_store.active:
        raise DomainError("STORE_INACTIVE", "The store is inactive")
    for batch_id, qty in lines:
        _check_available(batch_id, from_store.pk, _whole(qty))
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


def receive_transfer(
    transfer: StockTransfer,
    *,
    actor: User,
    received: Mapping[int, int] | None = None,
    shortage_reason_code: str | None = None,
    shortage_note: str = "",
    approver: User | None = None,
) -> StockTransfer:
    """Stock arrives in the destination store (FEATURES 8.10).

    ``received`` maps transfer line id to the base units that arrived (default: all). Units
    sent but not received left the source at sending and are lost in transit: the shortage
    is recorded on the transfer with a reason and an approver holding
    ``pharmacy.approve_adjustment`` (FEATURES 8.6, invariant 4).

    Raises:
        DomainError: ``TRANSFER_NOT_SENT``, ``RECEIPT_EXCEEDS_SENT``, ``REASON_REQUIRED``,
            ``TRANSFER_LINE_UNKNOWN``, reason errors.
        PermissionDenied: a shortage approver without ``pharmacy.approve_adjustment``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="receive transfer"):
        locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if locked.status != TransferStatus.SENT:
            raise DomainError("TRANSFER_NOT_SENT", "Only a sent transfer can be received")
        lines = list(locked.lines.order_by("id"))
        got = dict(received or {})
        unknown = sorted(set(got) - {ln.pk for ln in lines})
        if unknown:
            raise DomainError("TRANSFER_LINE_UNKNOWN", "Unknown transfer lines", line_ids=unknown)
        now = timezone.now()
        reason: ReasonCode | None = None
        approval: Approval | None = None
        chosen = approver or actor
        if any(got.get(ln.pk, _whole(ln.qty_base)) < _whole(ln.qty_base) for ln in lines):
            reason = resolve_reason(shortage_reason_code, "stock_adjust", shortage_note)
            require_permission(chosen, "pharmacy.approve_adjustment")
            approval = Approval(chosen.pk, now, shortage_note.strip(), reason.code)
        moves = []
        for ln in lines:
            sent = _whole(ln.qty_base)
            arrived = got.get(ln.pk, sent)
            ds.transfer_receipt(sent, arrived, approval)
            if arrived:
                moves.append(
                    ds.StockMoveDraft(
                        ln.item_id,
                        ln.batch_id,
                        locked.to_store_id,
                        arrived,
                        ds.MoveKind.TRANSFER_IN,
                    )
                )
        _apply(moves, actor=actor, source_type="transfer", source_id=locked.pk)
        locked.status = TransferStatus.RECEIVED
        locked.received_by = actor
        locked.received_at = now
        fields = ["status", "received_by", "received_at"]
        if reason is not None:
            locked.shortage_reason = reason
            locked.shortage_note = shortage_note.strip()[:300]
            locked.shortage_approved_by = chosen
            fields += ["shortage_reason", "shortage_note", "shortage_approved_by"]
        locked.save(update_fields=fields)
    return locked


def cancel_transfer(transfer: StockTransfer, *, actor: User, note: str = "") -> StockTransfer:
    """Cancel a transfer. A sent one (not received) returns its stock to the source store,
    with who and why recorded."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="cancel transfer"):
        locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
        if locked.status not in (TransferStatus.DRAFT, TransferStatus.SENT):
            raise DomainError("DOCUMENT_FINAL", "Only a draft or sent transfer can be cancelled")
        fields = ["status"]
        if locked.status == TransferStatus.SENT:
            text = note.strip()
            if not text:
                raise DomainError("REASON_REQUIRED", "Say why the sent transfer is cancelled")
            back = [
                ds.StockMoveDraft(
                    ln.item_id,
                    ln.batch_id,
                    locked.from_store_id,
                    _whole(ln.qty_base),
                    ds.MoveKind.TRANSFER_IN,
                )
                for ln in locked.lines.order_by("id")
            ]
            _apply(back, actor=actor, source_type="transfer_cancel", source_id=locked.pk)
            locked.cancelled_by = actor
            locked.cancelled_at = timezone.now()
            locked.cancel_note = text[:300]
            fields += ["cancelled_by", "cancelled_at", "cancel_note"]
        locked.status = TransferStatus.CANCELLED
        locked.save(update_fields=fields)
    return locked


# --- returns -------------------------------------------------------------------------------


def return_dispense(
    dispense_line: DispenseLine,
    *,
    quantity: int,
    actor: User,
    reason_code: str,
    note: str = "",
    credit_note: CreditNote | None = None,
) -> DispenseReturn:
    """Put units a patient brought back on the shelf: a ``return`` move into the batch and
    store they left (FEATURES 8.4; invariants 4 and 5).

    ``credit_note`` is the approved credit note that took the units off the bill when they
    are refunded; it must credit this line. The return itself never moves money.

    Raises:
        PermissionDenied: without ``pharmacy.dispense``.
        DomainError: ``RETURN_EXCEEDS_DISPENSED``, ``INVALID_QUANTITY``,
            ``REFUND_SOURCE_INVALID`` (the credit note is not approved or credits another
            line), reason errors.
    """
    require_permission(actor, "pharmacy.dispense")
    reason = resolve_reason(reason_code, "stock_adjust", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"return: {note}"):
        dl_row = DispenseLine.objects.select_related("dispense").get(pk=dispense_line.pk)
        (line,) = _orders().lock_lines([dl_row.service_line_id])
        if (
            credit_note is not None
            and not CreditNoteLine.objects.filter(
                credit_note=credit_note,
                credit_note__status=DocumentStatus.APPROVED,
                invoice_line__service_line_id=line.pk,
            ).exists()
        ):
            raise DomainError("REFUND_SOURCE_INVALID", "The credit note does not credit this line")
        returned = int(
            DispenseReturn.objects.filter(dispense_line=dl_row).aggregate(t=Sum("qty_base"))["t"]
            or 0
        )
        now = timezone.now()
        move = ds.return_move(
            dl_row.item_id,
            dl_row.batch_id,
            dl_row.dispense.store_id,
            _whole(quantity),
            dispensed=_whole(dl_row.qty_base),
            returned=returned,
            approval=Approval(actor.pk, now, note.strip(), reason.code),
        )
        (stock_move,) = _apply(
            [move], actor=actor, source_type="dispense_return", source_id=dl_row.pk, note=note
        )
        return DispenseReturn.objects.create(
            number=next_number("RTN"),
            dispense_line=dl_row,
            credit_note=credit_note,
            qty_base=Decimal(move.quantity),
            reason_code=reason,
            note=note.strip()[:300],
            returned_by=actor,
            stock_move=stock_move,
        )
