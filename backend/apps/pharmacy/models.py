"""Pharmacy and inventory (ARCHITECTURE 4.8, FEATURES 8, invariant 5).

* ``StockMove`` is the append-only stock ledger in base units (signed); on-hand is the sum of
  moves. Stock decrements at dispense, never at invoicing.
* ``StockBalance`` is the per (batch, store) projection of the moves. Only the
  ``stock_balance`` trigger on ``StockMove`` writes it (direct writes are refused), and its
  ``qty_base >= 0`` check makes the move that would take stock negative fail: stock never
  goes negative, enforced by the database. Services still lock the balance rows
  (``select_for_update``) and check with ``domain/stock.py`` first, to answer
  ``STOCK_INSUFFICIENT`` cleanly.
* Documents (receipts, adjustments, counts, transfers) are editable while draft/open and
  frozen once posted, approved, received or cancelled. Dispenses are append-only.
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q

from apps.core.db import (
    append_only,
    choice_check,
    cost_field,
    money_field,
    parent_must_be_editable,
    protect_when,
    quantity_field,
    track_history,
)


@track_history()
class DrugClass(models.Model):
    """A drug class used for allergy alerts at prescribing (FEATURES 3.2), e.g. penicillins."""

    code = models.CharField(max_length=40, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "drug class"
        verbose_name_plural = "drug classes"
        ordering: ClassVar[list[str]] = ["code"]

    def __str__(self) -> str:
        return self.name_en or self.code


class DosageForm(models.TextChoices):
    TABLET = "tablet", "Tablet"
    CAPSULE = "capsule", "Capsule"
    SYRUP = "syrup", "Syrup"
    SUSPENSION = "suspension", "Suspension"
    INJECTION = "injection", "Injection"
    INFUSION = "infusion", "Infusion"
    CREAM = "cream", "Cream or ointment"
    DROPS = "drops", "Drops"
    INHALER = "inhaler", "Inhaler"
    SUPPOSITORY = "suppository", "Suppository"
    SACHET = "sachet", "Sachet"
    SUPPLY = "supply", "Medical supply"
    OTHER = "other", "Other"


class Storage(models.TextChoices):
    ROOM = "room", "Room temperature"
    COOL = "cool", "Cool place"
    FRIDGE = "fridge", "Refrigerated (2-8 C)"
    FROZEN = "frozen", "Frozen"


@track_history()
class Item(models.Model):
    """Stock item master (FEATURES 8.1), one per catalog service of kind drug/consumable."""

    service = models.OneToOneField(
        "catalog.Service", on_delete=models.PROTECT, related_name="stock_item"
    )
    generic_name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=200, blank=True)
    form = models.CharField(max_length=20, choices=DosageForm.choices, default=DosageForm.TABLET)
    strength = models.CharField(max_length=60, blank=True)
    base_unit_code = models.CharField(max_length=20, help_text="Smallest unit, e.g. tablet, ml.")
    base_unit_name_ar = models.CharField(max_length=50)
    base_unit_name_en = models.CharField(max_length=50)
    barcode = models.CharField(max_length=60, blank=True)
    min_stock = quantity_field(default=0, help_text="Low stock alert threshold (base units).")
    reorder_qty = quantity_field(default=0, help_text="Suggested reorder quantity (base units).")
    storage = models.CharField(max_length=10, choices=Storage.choices, default=Storage.ROOM)
    is_controlled = models.BooleanField(default=False)
    drug_classes = models.ManyToManyField(DrugClass, blank=True, related_name="items")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "stock item"
        ordering: ClassVar[list[str]] = ["generic_name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("form", DosageForm, "pharmacy_item_form_valid"),
            choice_check("storage", Storage, "pharmacy_item_storage_valid"),
            models.CheckConstraint(
                condition=Q(min_stock__gte=0) & Q(reorder_qty__gte=0),
                name="pharmacy_item_levels_non_negative",
            ),
            models.UniqueConstraint(
                fields=["barcode"], condition=~Q(barcode=""), name="pharmacy_item_barcode_unique"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(
                fields=["generic_name"],
                opclasses=["gin_trgm_ops"],
                name="pharmacy_item_generic_trgm",
            ),
            GinIndex(
                fields=["brand_name"], opclasses=["gin_trgm_ops"], name="pharmacy_item_brand_trgm"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.generic_name} {self.strength}".strip()


@track_history()
class UnitConversion(models.Model):
    """A pack unit of an item: 1 ``unit_code`` = ``factor`` base units (box -> strip -> tablet)."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="units")
    unit_code = models.CharField(max_length=20)
    name_ar = models.CharField(max_length=50)
    name_en = models.CharField(max_length=50)
    factor = quantity_field()
    barcode = models.CharField(max_length=60, blank=True)
    is_dispensable = models.BooleanField(default=True)
    is_purchase_unit = models.BooleanField(default=False)

    class Meta:
        verbose_name = "unit conversion"
        ordering: ClassVar[list[str]] = ["item", "factor"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["item", "unit_code"], name="pharmacy_unit_unique"),
            models.CheckConstraint(condition=Q(factor__gt=0), name="pharmacy_unit_factor_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.unit_code} = {self.factor}"


class StoreKind(models.TextChoices):
    MAIN = "main", "Main store"
    PHARMACY = "pharmacy", "Pharmacy"
    LAB = "lab", "Laboratory"
    WARD = "ward", "Ward or department"
    OTHER = "other", "Other"


@track_history()
class Store(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=StoreKind.choices, default=StoreKind.PHARMACY)
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="stores"
    )
    allows_dispense = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "store"
        ordering: ClassVar[list[str]] = ["code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", StoreKind, "pharmacy_store_kind_valid"),
        ]

    def __str__(self) -> str:
        return self.name_en or self.code


@track_history()
class Supplier(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=300, blank=True)
    tax_no = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "supplier"
        ordering: ClassVar[list[str]] = ["code"]

    def __str__(self) -> str:
        return self.name_en or self.code


@track_history()
class Batch(models.Model):
    """A lot of an item with its expiry and cost per base unit (FEATURES 8.2)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="batches")
    batch_no = models.CharField(max_length=60)
    expiry_date = models.DateField()
    unit_cost = cost_field(help_text="Cost per base unit.")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="batches"
    )
    received_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "batch"
        verbose_name_plural = "batches"
        ordering: ClassVar[list[str]] = ["item", "expiry_date", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["item", "batch_no", "expiry_date"], name="pharmacy_batch_unique"
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0), name="pharmacy_batch_cost_non_negative"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["item", "expiry_date"], name="pharmacy_batch_fefo_idx"),
            models.Index(fields=["expiry_date"], name="pharmacy_batch_expiry_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.batch_no} exp {self.expiry_date}"


class MoveKind(models.TextChoices):
    RECEIPT = "receipt", "Goods receipt"
    DISPENSE = "dispense", "Dispense"
    ADJUSTMENT = "adjustment", "Adjustment"
    TRANSFER_OUT = "transfer_out", "Transfer out"
    TRANSFER_IN = "transfer_in", "Transfer in"
    COUNT_CORRECTION = "count_correction", "Count correction"
    RETURN = "return", "Return"


_STOCK_BALANCE_SQL = """
    IF NOT EXISTS (
        SELECT 1 FROM pharmacy_batch b WHERE b.id = NEW.batch_id AND b.item_id = NEW.item_id
    ) THEN
        RAISE EXCEPTION 'STOCK_ITEM_MISMATCH: batch % does not belong to item %',
            NEW.batch_id, NEW.item_id;
    END IF;
    -- A zero row first (always valid), then the signed change: the CHECK (qty_base >= 0)
    -- judges the resulting balance, and the UPDATE row lock serializes concurrent moves.
    INSERT INTO pharmacy_stockbalance (item_id, batch_id, store_id, qty_base, updated_at)
    VALUES (NEW.item_id, NEW.batch_id, NEW.store_id, 0, now())
    ON CONFLICT (batch_id, store_id) DO NOTHING;
    UPDATE pharmacy_stockbalance
       SET qty_base = qty_base + NEW.qty_base, updated_at = now()
     WHERE batch_id = NEW.batch_id AND store_id = NEW.store_id;
    RETURN NULL;
"""


class StockMove(models.Model):
    """Append-only stock ledger row, quantity in base units (signed)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="moves")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="moves")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="moves")
    qty_base = quantity_field()
    kind = models.CharField(max_length=20, choices=MoveKind.choices)
    source_type = models.CharField(
        max_length=40, help_text="Document kind, e.g. dispense_line, receipt_line, count_line."
    )
    source_id = models.BigIntegerField(null=True, blank=True)
    unit_cost = cost_field(help_text="Batch cost per base unit at the time of the move.")
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    moved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "stock move"
        ordering: ClassVar[list[str]] = ["-moved_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", MoveKind, "pharmacy_move_kind_valid"),
            models.CheckConstraint(
                condition=(Q(kind__in=["receipt", "transfer_in"]) & Q(qty_base__gt=0))
                | (Q(kind__in=["dispense", "transfer_out"]) & Q(qty_base__lt=0))
                | (Q(kind__in=["adjustment", "count_correction", "return"]) & ~Q(qty_base=0)),
                name="pharmacy_move_sign_matches_kind",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0), name="pharmacy_move_cost_non_negative"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["item", "store", "moved_at"], name="pharmacy_move_item_idx"),
            models.Index(fields=["source_type", "source_id"], name="pharmacy_move_source_idx"),
            models.Index(fields=["kind", "moved_at"], name="pharmacy_move_kind_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            append_only(),
            pgtrigger.Trigger(
                name="stock_balance",
                when=pgtrigger.After,
                operation=pgtrigger.Insert,
                func=_STOCK_BALANCE_SQL,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.qty_base} of {self.item_id}"


class StockBalance(models.Model):
    """On-hand per batch and store, maintained only by the ``stock_balance`` trigger."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="balances")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="balances")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="balances")
    qty_base = quantity_field()
    updated_at = models.DateTimeField()

    class Meta:
        verbose_name = "stock balance"
        ordering: ClassVar[list[str]] = ["item", "store", "batch"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["batch", "store"], name="pharmacy_balance_unique"),
            # Invariant 5: stock never goes negative.
            models.CheckConstraint(
                condition=Q(qty_base__gte=0), name="pharmacy_balance_never_negative"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["item", "store"], name="pharmacy_balance_item_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "balance_only_from_moves",
                code="STOCK_BALANCE_DERIVED",
                message="stock balances change only through stock moves",
                # WHEN runs before the trigger body: depth 0 = a statement from a client,
                # depth 1 = the INSERT ... ON CONFLICT issued by StockMove's trigger.
                condition=pgtrigger.Condition("pg_trigger_depth() = 0"),
                operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id}@{self.store_id}: {self.qty_base}"


# --- Dispensing ----------------------------------------------------------------------------


class Dispense(models.Model):
    """One dispensing event for a visit (paid or authorized drug lines). Append-only."""

    number = models.CharField(max_length=30, unique=True)
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="dispenses")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="dispenses")
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    dispensed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "dispense"
        ordering: ClassVar[list[str]] = ["-dispensed_at", "-id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["visit"], name="pharmacy_dispense_visit_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [append_only()]

    def __str__(self) -> str:
        return self.number


class DispenseLine(models.Model):
    dispense = models.ForeignKey(Dispense, on_delete=models.PROTECT, related_name="lines")
    service_line = models.ForeignKey(
        "orders.ServiceLine", on_delete=models.PROTECT, related_name="dispense_lines"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="+")
    unit = models.ForeignKey(
        UnitConversion, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity_units = quantity_field(help_text="Quantity in the chosen unit.")
    qty_base = quantity_field()
    batch_override = models.BooleanField(
        default=False, help_text="Pharmacist chose another batch than the FEFO suggestion."
    )
    override_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "override"},
    )
    override_note = models.CharField(max_length=300, blank=True)
    stock_move = models.OneToOneField(
        StockMove, on_delete=models.PROTECT, related_name="dispense_line"
    )

    class Meta:
        verbose_name = "dispense line"
        ordering: ClassVar[list[str]] = ["dispense", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(quantity_units__gt=0) & Q(qty_base__gt=0),
                name="pharmacy_dispenseline_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(batch_override=False) | Q(override_reason__isnull=False),
                name="pharmacy_dispenseline_override_reason",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [append_only()]

    def __str__(self) -> str:
        return f"{self.dispense_id}: {self.qty_base} of {self.item_id}"


# --- Goods receipts ------------------------------------------------------------------------


class ReceiptStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class GoodsReceipt(models.Model):
    """Goods received from a supplier against its invoice (FEATURES 8.5)."""

    number = models.CharField(max_length=30, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="receipts")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="receipts")
    supplier_invoice_no = models.CharField(max_length=60, blank=True)
    supplier_invoice_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=ReceiptStatus.choices, default=ReceiptStatus.DRAFT
    )
    total_cost = money_field(default=0)
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "goods receipt"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", ReceiptStatus, "pharmacy_receipt_status_valid"),
            models.CheckConstraint(
                condition=Q(total_cost__gte=0), name="pharmacy_receipt_total_non_negative"
            ),
            models.CheckConstraint(
                condition=~Q(status=ReceiptStatus.POSTED)
                | Q(posted_by__isnull=False, posted_at__isnull=False),
                name="pharmacy_receipt_post_documented",
            ),
            models.UniqueConstraint(
                fields=["supplier", "supplier_invoice_no"],
                condition=~Q(supplier_invoice_no="") & ~Q(status=ReceiptStatus.CANCELLED),
                name="pharmacy_receipt_supplier_invoice_once",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "receipt_final",
                code="DOCUMENT_FINAL",
                message="posted or cancelled receipts never change",
                condition=pgtrigger.Q(old__status__in=["posted", "cancelled"]),
            ),
        ]

    def __str__(self) -> str:
        return self.number


@track_history()
class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    batch_no = models.CharField(max_length=60)
    expiry_date = models.DateField()
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, null=True, blank=True, related_name="receipt_lines"
    )
    unit = models.ForeignKey(
        UnitConversion, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity_units = quantity_field()
    qty_base = quantity_field()
    unit_cost = cost_field(help_text="Cost per base unit.")
    line_total = money_field()

    class Meta:
        verbose_name = "goods receipt line"
        ordering: ClassVar[list[str]] = ["receipt", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(quantity_units__gt=0) & Q(qty_base__gt=0),
                name="pharmacy_receiptline_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0) & Q(line_total__gte=0),
                name="pharmacy_receiptline_cost_non_negative",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            parent_must_be_editable(
                "line_needs_draft_receipt",
                code="DOCUMENT_FINAL",
                parent_table="pharmacy_goodsreceipt",
                fk_column="receipt_id",
                editable_condition="p.status = 'draft'",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.receipt_id}: {self.qty_base} of {self.item_id}"


# --- Adjustments, counts, transfers -------------------------------------------------------


class AdjustmentStatus(models.TextChoices):
    DRAFT = "draft", "Awaiting approval"
    APPROVED = "approved", "Approved and posted"
    REJECTED = "rejected", "Rejected"


@track_history()
class StockAdjustment(models.Model):
    """Stock correction with a reason and supervisor approval (FEATURES 8.6)."""

    number = models.CharField(max_length=30, unique=True)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="adjustments")
    reason_code = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"category": "stock_adjust"},
    )
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=AdjustmentStatus.choices, default=AdjustmentStatus.DRAFT
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        verbose_name = "stock adjustment"
        ordering: ClassVar[list[str]] = ["-requested_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", AdjustmentStatus, "pharmacy_adjustment_status_valid"),
            models.CheckConstraint(
                condition=Q(status=AdjustmentStatus.DRAFT)
                | Q(decided_by__isnull=False, decided_at__isnull=False),
                name="pharmacy_adjustment_decision_documented",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "adjustment_final",
                code="DOCUMENT_FINAL",
                message="decided adjustments never change",
                condition=pgtrigger.Q(old__status__in=["approved", "rejected"]),
            ),
        ]

    def __str__(self) -> str:
        return self.number


@track_history()
class StockAdjustmentLine(models.Model):
    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="+")
    qty_base = quantity_field(help_text="Signed change in base units.")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "stock adjustment line"
        ordering: ClassVar[list[str]] = ["adjustment", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~Q(qty_base=0), name="pharmacy_adjustmentline_non_zero"
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            parent_must_be_editable(
                "line_needs_draft_adjustment",
                code="DOCUMENT_FINAL",
                parent_table="pharmacy_stockadjustment",
                fk_column="adjustment_id",
                editable_condition="p.status = 'draft'",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.adjustment_id}: {self.qty_base} of {self.batch_id}"


class CountStatus(models.TextChoices):
    OPEN = "open", "Counting"
    POSTED = "posted", "Posted"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class StockCount(models.Model):
    """A stock count session: book vs counted, posting count corrections (FEATURES 8.7)."""

    number = models.CharField(max_length=30, unique=True)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="counts")
    status = models.CharField(max_length=20, choices=CountStatus.choices, default=CountStatus.OPEN)
    note = models.TextField(blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "stock count"
        ordering: ClassVar[list[str]] = ["-started_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", CountStatus, "pharmacy_count_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=CountStatus.POSTED)
                | Q(posted_by__isnull=False, posted_at__isnull=False),
                name="pharmacy_count_post_documented",
            ),
            models.UniqueConstraint(
                fields=["store"],
                condition=Q(status=CountStatus.OPEN),
                name="pharmacy_count_one_open_per_store",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "count_final",
                code="DOCUMENT_FINAL",
                message="posted or cancelled counts never change",
                condition=pgtrigger.Q(old__status__in=["posted", "cancelled"]),
            ),
        ]

    def __str__(self) -> str:
        return self.number


@track_history()
class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="+")
    book_qty = quantity_field(help_text="On-hand when the count started (base units).")
    counted_qty = quantity_field(null=True, blank=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    counted_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "stock count line"
        ordering: ClassVar[list[str]] = ["count", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["count", "batch"], name="pharmacy_countline_unique"),
            models.CheckConstraint(
                condition=Q(book_qty__gte=0)
                & (Q(counted_qty__isnull=True) | Q(counted_qty__gte=0)),
                name="pharmacy_countline_qty_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(counted_qty__isnull=True)
                | Q(counted_by__isnull=False, counted_at__isnull=False),
                name="pharmacy_countline_count_documented",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            parent_must_be_editable(
                "line_needs_open_count",
                code="DOCUMENT_FINAL",
                parent_table="pharmacy_stockcount",
                fk_column="count_id",
                editable_condition="p.status = 'open'",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.count_id}: {self.batch_id}"


class TransferStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    RECEIVED = "received", "Received"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class StockTransfer(models.Model):
    """Internal transfer between stores (FEATURES 8.10, V1?)."""

    number = models.CharField(max_length=30, unique=True)
    from_store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="transfers_out")
    to_store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="transfers_in")
    status = models.CharField(
        max_length=20, choices=TransferStatus.choices, default=TransferStatus.DRAFT
    )
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "stock transfer"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", TransferStatus, "pharmacy_transfer_status_valid"),
            models.CheckConstraint(
                condition=~Q(from_store=F("to_store")), name="pharmacy_transfer_distinct_stores"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=[TransferStatus.SENT, TransferStatus.RECEIVED])
                | Q(sent_by__isnull=False, sent_at__isnull=False),
                name="pharmacy_transfer_send_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=TransferStatus.RECEIVED)
                | Q(received_by__isnull=False, received_at__isnull=False),
                name="pharmacy_transfer_receipt_documented",
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            protect_when(
                "transfer_final",
                code="DOCUMENT_FINAL",
                message="received or cancelled transfers never change",
                condition=pgtrigger.Q(old__status__in=["received", "cancelled"]),
            ),
        ]

    def __str__(self) -> str:
        return self.number


@track_history()
class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="+")
    qty_base = quantity_field()

    class Meta:
        verbose_name = "stock transfer line"
        ordering: ClassVar[list[str]] = ["transfer", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(qty_base__gt=0), name="pharmacy_transferline_qty_positive"
            ),
            models.UniqueConstraint(
                fields=["transfer", "batch"], name="pharmacy_transferline_batch_once"
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            parent_must_be_editable(
                "line_needs_draft_transfer",
                code="DOCUMENT_FINAL",
                parent_table="pharmacy_stocktransfer",
                fk_column="transfer_id",
                editable_condition="p.status = 'draft'",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transfer_id}: {self.qty_base} of {self.batch_id}"
