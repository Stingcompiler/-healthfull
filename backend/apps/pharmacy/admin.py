from __future__ import annotations

from django.contrib import admin

from apps.core.admin_base import ReadOnlyAdmin, ReadOnlyInline
from apps.pharmacy.models import (
    Batch,
    Dispense,
    DispenseLine,
    DispenseReturn,
    DrugClass,
    GoodsReceipt,
    GoodsReceiptLine,
    Item,
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
    UnitConversion,
)


@admin.register(DrugClass)
class DrugClassAdmin(admin.ModelAdmin[DrugClass]):
    list_display = ("code", "name_ar", "name_en", "active")
    search_fields = ("code", "name_ar", "name_en")


class UnitConversionInline(admin.TabularInline[UnitConversion, Item]):
    model = UnitConversion
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin[Item]):
    list_display = ("generic_name", "brand_name", "form", "strength", "base_unit_code", "active")
    list_filter = ("form", "storage", "is_controlled", "active")
    search_fields = ("generic_name", "brand_name", "barcode", "service__code")
    raw_id_fields = ("service",)
    filter_horizontal = ("drug_classes",)
    inlines = (UnitConversionInline,)


@admin.register(UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin[UnitConversion]):
    list_display = ("item", "unit_code", "factor", "is_dispensable", "is_purchase_unit")
    raw_id_fields = ("item",)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin[Store]):
    list_display = ("code", "name_ar", "name_en", "kind", "allows_dispense", "active")
    list_filter = ("kind", "active")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin[Supplier]):
    list_display = ("code", "name_ar", "name_en", "phone", "active")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Batch)
class BatchAdmin(ReadOnlyAdmin[Batch]):
    list_display = ("item", "batch_no", "expiry_date", "unit_cost", "supplier")
    search_fields = ("batch_no", "item__generic_name")
    date_hierarchy = "expiry_date"


@admin.register(StockMove)
class StockMoveAdmin(ReadOnlyAdmin[StockMove]):
    list_display = ("moved_at", "kind", "item", "batch", "store", "qty_base", "source_type")
    list_filter = ("kind", "store")
    date_hierarchy = "moved_at"


@admin.register(StockBalance)
class StockBalanceAdmin(ReadOnlyAdmin[StockBalance]):
    list_display = ("item", "batch", "store", "qty_base", "updated_at")
    list_filter = ("store",)
    search_fields = ("item__generic_name", "batch__batch_no")


class DispenseLineInline(ReadOnlyInline[DispenseLine, Dispense]):
    model = DispenseLine
    fields = ("service_line", "item", "batch", "quantity_units", "qty_base", "batch_override")


@admin.register(Dispense)
class DispenseAdmin(ReadOnlyAdmin[Dispense]):
    list_display = ("number", "visit", "store", "dispensed_by", "dispensed_at")
    search_fields = ("number", "visit__number")
    inlines = (DispenseLineInline,)


@admin.register(DispenseLine)
class DispenseLineAdmin(ReadOnlyAdmin[DispenseLine]):
    list_display = ("dispense", "item", "batch", "qty_base", "batch_override")


@admin.register(DispenseReturn)
class DispenseReturnAdmin(ReadOnlyAdmin[DispenseReturn]):
    list_display = ("number", "dispense_line", "qty_base", "reason_code", "returned_by")


class GoodsReceiptLineInline(ReadOnlyInline[GoodsReceiptLine, GoodsReceipt]):
    model = GoodsReceiptLine
    fields = ("item", "batch_no", "expiry_date", "qty_base", "unit_cost", "line_total")


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(ReadOnlyAdmin[GoodsReceipt]):
    list_display = ("number", "supplier", "store", "supplier_invoice_no", "status", "total_cost")
    list_filter = ("status", "store")
    search_fields = ("number", "supplier_invoice_no")
    inlines = (GoodsReceiptLineInline,)


@admin.register(GoodsReceiptLine)
class GoodsReceiptLineAdmin(ReadOnlyAdmin[GoodsReceiptLine]):
    list_display = ("receipt", "item", "batch_no", "expiry_date", "qty_base", "unit_cost")


class StockAdjustmentLineInline(ReadOnlyInline[StockAdjustmentLine, StockAdjustment]):
    model = StockAdjustmentLine
    fields = ("item", "batch", "qty_base", "note")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(ReadOnlyAdmin[StockAdjustment]):
    list_display = ("number", "store", "reason_code", "status", "requested_by", "decided_by")
    list_filter = ("status", "store")
    search_fields = ("number",)
    inlines = (StockAdjustmentLineInline,)


@admin.register(StockAdjustmentLine)
class StockAdjustmentLineAdmin(ReadOnlyAdmin[StockAdjustmentLine]):
    list_display = ("adjustment", "item", "batch", "qty_base")


class StockCountLineInline(ReadOnlyInline[StockCountLine, StockCount]):
    model = StockCountLine
    fields = ("item", "batch", "book_qty", "counted_qty", "counted_by")


@admin.register(StockCount)
class StockCountAdmin(ReadOnlyAdmin[StockCount]):
    list_display = ("number", "store", "status", "started_at", "posted_at")
    list_filter = ("status", "store")
    inlines = (StockCountLineInline,)


@admin.register(StockCountLine)
class StockCountLineAdmin(ReadOnlyAdmin[StockCountLine]):
    list_display = ("count", "item", "batch", "book_qty", "counted_qty")


class StockTransferLineInline(ReadOnlyInline[StockTransferLine, StockTransfer]):
    model = StockTransferLine
    fields = ("item", "batch", "qty_base")


@admin.register(StockTransfer)
class StockTransferAdmin(ReadOnlyAdmin[StockTransfer]):
    list_display = ("number", "from_store", "to_store", "status", "created_at")
    list_filter = ("status",)
    inlines = (StockTransferLineInline,)


@admin.register(StockTransferLine)
class StockTransferLineAdmin(ReadOnlyAdmin[StockTransferLine]):
    list_display = ("transfer", "item", "batch", "qty_base")
