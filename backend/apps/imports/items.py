"""Stock items, batches and opening stock from a sheet (FEATURES 8.13; ADR 0014).

Preview (:func:`parse`): ``domain.item_import`` reads the rows against what the database
knows (catalog codes, items, active stores); this module adds the checks that need the
database: a barcode another item carries (error), and for an existing item a batch that
already exists or stock already on hand (possible duplicates: importing them would count
opening stock twice, so they are imported only when the user asks).

Confirm (:func:`confirm`): every write goes through the owning module's services.

* Per service code, in one savepoint: ``catalog.create_service`` for a new code,
  ``pharmacy.create_item`` and ``pharmacy.add_unit`` for a new item. A refused step rolls
  back that code only and skips its rows.
* Opening stock is a goods receipt per store from the ``OPENING`` supplier, numbered like
  every receipt and posted by ``pharmacy.post_receipt``: batches are created there and the
  stock moves are ``receipt`` moves of its lines. Stock is never written directly
  (invariant 5 and the append-only stock ledger stay with the pharmacy module). The
  receipt's supplier invoice number ``IMPORT-<job>-<store>`` makes a second posting of one job
  impossible (``pharmacy_receipt_supplier_invoice_once``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum

from apps.catalog import services as catalog
from apps.catalog.models import Service
from apps.core.models import User
from apps.core.services import require_permission
from apps.imports.models import ImportJob, ImportRow, RowStatus
from apps.imports.rows import RowDraft
from apps.pharmacy import services as pharmacy
from apps.pharmacy.models import Batch, Item, StockBalance, Store, Supplier, UnitConversion
from domain import item_import as dii
from domain.errors import DomainError

__all__ = ["COLUMNS", "DUPLICATE_HINTS", "clean_options", "confirm", "parse"]

COLUMNS = dii.COLUMNS
#: Hints that make a row a possible duplicate (imported only when asked).
DUPLICATE_HINTS = frozenset({"in_file", "batch_exists", "stock_exists"})

OPENING_SUPPLIER = "OPENING"


def clean_options(options: Mapping[str, Any], *, today: date) -> dict[str, Any]:
    """``store``: the store code of batch rows that name none (optional, must be active).

    Raises:
        DomainError: ``STORE_UNKNOWN``.
    """
    store = str(options.get("store") or "").strip().upper()
    if store and not Store.objects.filter(code=store, active=True).exists():
        raise DomainError("STORE_UNKNOWN", "Unknown or inactive store", store=store)
    return {"store": store} if store else {}


def parse(
    rows: Sequence[tuple[int, Mapping[str, Any]]], *, options: Mapping[str, Any], today: date
) -> list[RowDraft]:
    codes = {
        str(v).strip().upper()
        for _, cells in rows
        if (v := cells.get("service_code")) not in (None, "")
    }
    services = {
        s.code.upper(): s for s in Service.objects.filter(code__in=codes).only("id", "code", "kind")
    }
    items = {
        it.service.code.upper(): it
        for it in Item.objects.filter(service__in=services.values()).select_related("service")
    }
    known = {
        code: dii.KnownService(kind=s.kind, has_item=code in items) for code, s in services.items()
    }
    stores = frozenset(Store.objects.filter(active=True).values_list("code", flat=True))
    parsed = dii.parse_rows(
        rows,
        today=today,
        services=known,
        stores=frozenset(s.upper() for s in stores),
        default_store=options.get("store") or None,
    )

    item_ids = [it.pk for it in items.values()]
    on_hand = {
        row["batch__item_id"]: int(row["total"] or 0)
        for row in StockBalance.objects.filter(batch__item_id__in=item_ids)
        .values("batch__item_id")
        .annotate(total=Sum("qty_base"))
    }
    batches = {
        (item_id, batch_no.upper(), expiry.isoformat())
        for item_id, batch_no, expiry in Batch.objects.filter(item_id__in=item_ids).values_list(
            "item_id", "batch_no", "expiry_date"
        )
    }
    barcodes = {bc for r in parsed if r.defines_item for bc in _barcodes(r.data)}
    taken = set(Item.objects.filter(barcode__in=barcodes).values_list("barcode", flat=True)) | set(
        UnitConversion.objects.filter(barcode__in=barcodes).values_list("barcode", flat=True)
    )

    drafts: list[RowDraft] = []
    for row in parsed:
        code = row.data["service_code"]
        item = items.get(code)
        if row.defines_item and item is None and row.data.get("barcode") in taken:
            row.add_error("BARCODE_TAKEN", "barcode")
        if item is not None and row.has_batch and not row.errors:
            key = (item.pk, str(row.data["batch_no"]).upper(), str(row.data["expiry_date"]))
            if key in batches:
                row.warnings.append({"code": "batch_exists", "item_id": item.pk})
            if on_hand.get(item.pk, 0) > 0:
                row.warnings.append(
                    {"code": "stock_exists", "item_id": item.pk, "on_hand": on_hand[item.pk]}
                )
        drafts.append(
            RowDraft(
                row_no=row.row_no,
                data=row.data,
                errors=row.errors,
                warnings=row.warnings,
                duplicate_of=item.pk if item is not None else None,
            )
        )
    return drafts


def _barcodes(data: Mapping[str, Any]) -> list[str]:
    code = str(data.get("barcode") or "").strip()
    return [code] if code else []


def _service(code: str, data: Mapping[str, Any], actor: User) -> Service:
    found = Service.objects.filter(code__iexact=code).first()
    if found is not None:
        return found
    require_permission(actor, "catalog.manage")
    return catalog.create_service(
        actor,
        code=code,
        name_ar=str(data.get("name_ar") or ""),
        name_en=str(data.get("name_en") or ""),
        kind=str(data.get("kind") or "drug"),
    )


def _item(code: str, data: Mapping[str, Any], actor: User) -> Item:
    service = _service(code, data, actor)
    existing = Item.objects.filter(service=service).first()
    if existing is not None:
        return existing
    fields: dict[str, object] = {
        "generic_name_ar": str(data.get("generic_name_ar") or ""),
        "brand_name": str(data.get("brand_name") or ""),
        "form": str(data.get("form") or "tablet"),
        "strength": str(data.get("strength") or ""),
        "storage": str(data.get("storage") or "room"),
        "barcode": str(data.get("barcode") or ""),
    }
    for key in ("min_stock", "reorder_qty"):
        if data.get(key) is not None:
            fields[key] = int(data[key])
    item = pharmacy.create_item(
        service=service,
        generic_name=str(data.get("generic_name") or ""),
        base_unit_code=str(data.get("base_unit_code") or ""),
        base_unit_name_ar=str(data.get("base_unit_name_ar") or ""),
        base_unit_name_en=str(data.get("base_unit_name_en") or ""),
        actor=actor,
        **fields,
    )
    if data.get("pack_unit_code"):
        pharmacy.add_unit(
            item,
            unit_code=str(data["pack_unit_code"]),
            name_ar=str(data.get("pack_unit_name_ar") or ""),
            name_en=str(data.get("pack_unit_name_en") or ""),
            factor=int(data["pack_factor"]),
            actor=actor,
            is_purchase_unit=True,
        )
    return item


def _opening_supplier(actor: User) -> Supplier:
    found = Supplier.objects.filter(code=OPENING_SUPPLIER).first()
    if found is not None:
        return found
    return pharmacy.create_supplier(
        code=OPENING_SUPPLIER,
        name_ar="رصيد افتتاحي (استيراد)",
        name_en="Opening stock (import)",
        actor=actor,
        notes="Created by the Excel import of opening stock (FEATURES 8.13).",
    )


def _skip(row: ImportRow, code: str) -> None:
    row.status = RowStatus.SKIPPED
    row.errors = [{"code": code, "field": ""}]
    row.save(update_fields=["status", "errors", "result_id"])


def confirm(
    job: ImportJob, rows: Sequence[ImportRow], *, actor: User, today: date
) -> dict[str, Any]:
    """Create the items of ``rows`` and post their opening stock; marks each row.

    ``rows`` are the rows to import (locked, in sheet order). Returns the job summary
    additions (``receipts``: the posted receipt numbers).
    """
    if any(r.data.get("quantity") is not None for r in rows):
        require_permission(actor, "pharmacy.receive_goods")
    codes = {str(r.data["service_code"]) for r in rows}
    if codes - set(Service.objects.filter(code__in=codes).values_list("code", flat=True)):
        require_permission(actor, "catalog.manage")  # new catalog services
    groups: dict[str, list[ImportRow]] = defaultdict(list)
    for row in rows:
        groups[str(row.data["service_code"])].append(row)

    stock_rows: dict[str, list[tuple[ImportRow, Item]]] = defaultdict(list)
    for code, group in groups.items():
        try:
            with transaction.atomic():
                item = _item(code, group[0].data, actor)
        except DomainError as exc:
            for row in group:
                _skip(row, exc.code)
            continue
        for row in group:
            row.result_id = item.pk
            if row.data.get("quantity") is not None:
                stock_rows[str(row.data["store"])].append((row, item))
            else:
                row.status = RowStatus.IMPORTED
                row.save(update_fields=["status", "result_id"])

    receipts: list[str] = []
    for store_code in sorted(stock_rows):
        lines = stock_rows[store_code]
        added: list[ImportRow] = []
        try:
            with transaction.atomic():
                store = Store.objects.get(code=store_code)
                receipt = pharmacy.create_receipt(
                    supplier=_opening_supplier(actor),
                    store=store,
                    actor=actor,
                    supplier_invoice_no=f"IMPORT-{job.pk}-{store_code}"[:60],
                    note=f"Opening stock, Excel import {job.pk} ({job.original_filename})",
                )
                for row, item in lines:
                    try:
                        with transaction.atomic():
                            pharmacy.add_receipt_line(
                                receipt,
                                item=item,
                                batch_no=str(row.data["batch_no"]),
                                expiry_date=date.fromisoformat(str(row.data["expiry_date"])),
                                quantity=int(row.data["quantity"]),
                                unit_cost=Decimal(str(row.data.get("unit_cost") or "0")),
                                actor=actor,
                                today=today,
                            )
                    except DomainError as exc:
                        _skip(row, exc.code)
                        continue
                    added.append(row)
                if not added:
                    raise DomainError("RECEIPT_EMPTY", "No opening stock line could be added")
                pharmacy.post_receipt(receipt, actor=actor, today=today)
        except (DomainError, Store.DoesNotExist) as exc:
            code = exc.code if isinstance(exc, DomainError) else "STORE_UNKNOWN"
            for row, _ in lines:
                # The savepoint rolled back the per-line skips too: write them again.
                if row.status == RowStatus.SKIPPED:
                    row.save(update_fields=["status", "errors", "result_id"])
                else:
                    _skip(row, code)
            continue
        receipts.append(receipt.number)
        for row in added:
            row.status = RowStatus.IMPORTED
            row.save(update_fields=["status", "result_id"])
    return {"receipts": sorted(receipts)}
