"""Schemas of ``/api/pharmacy`` (FEATURES 8.1-8.10, 5.12).

Quantities are whole base units (``qty_base``, e.g. tablets) unless a field says it is in a
pack unit. Costs are decimal strings with four places (cost per base unit), money totals
two places. Class names are unique across apps (OpenAPI components are named after them;
``api/tests/test_main.py`` guards it), hence the ``Stock``/``Pharmacy``/``Goods`` prefixes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Field, Schema

from apps.billing.schemas import ApproverIn

DosageFormCode = Literal[
    "tablet",
    "capsule",
    "syrup",
    "suspension",
    "injection",
    "infusion",
    "cream",
    "drops",
    "inhaler",
    "suppository",
    "sachet",
    "supply",
    "other",
]
StorageCode = Literal["room", "cool", "fridge", "frozen"]
StoreKindCode = Literal["main", "pharmacy", "lab", "ward", "other"]
MoveKindCode = Literal[
    "receipt",
    "dispense",
    "adjustment",
    "transfer_out",
    "transfer_in",
    "count_correction",
    "return",
]
ReceiptStatusCode = Literal["draft", "posted", "cancelled"]
AdjustmentStatusCode = Literal["draft", "approved", "rejected"]
CountStatusCode = Literal["open", "posted", "cancelled"]
TransferStatusCode = Literal["draft", "sent", "received", "cancelled"]
RemainderCode = Literal["defer", "refund"]
PharmacyReasonCategory = Literal["override", "stock_adjust", "line_cancel"]

#: A cost per base unit as the API sends it (four decimal places).
CostStr = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]{4}$", examples=["2.5000"])]
#: A money amount as the API sends it (two decimal places).
PharmacyMoneyStr = Annotated[str, Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", examples=["150.00"])]
#: A cost sent by the client: digits with up to four decimals (judged by the service).
CostIn = Annotated[
    str, Field(min_length=1, max_length=20, pattern=r"^[0-9]+(\.[0-9]{1,4})?$", examples=["300"])
]
#: A whole number of units sent by the client.
Qty = Annotated[int, Field(ge=1, le=10_000_000)]
SignedQty = Annotated[int, Field(ge=-10_000_000, le=10_000_000)]
Code = Annotated[str, Field(min_length=1, max_length=60)]
Note = Annotated[str, Field(max_length=300)]


# --- references -----------------------------------------------------------------------------


class PharmacyNameOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class PharmacyUserRefOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str


class PharmacyReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str
    requires_note: bool


class StoreOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: StoreKindCode
    allows_dispense: bool


class SupplierOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    contact_name: str
    phone: str


class SupplierIn(Schema):
    code: Annotated[str, Field(min_length=1, max_length=30)]
    name_ar: Annotated[str, Field(max_length=200)] = ""
    name_en: Annotated[str, Field(max_length=200)] = ""
    contact_name: Annotated[str, Field(max_length=150)] = ""
    phone: Annotated[str, Field(max_length=50)] = ""
    address: Annotated[str, Field(max_length=300)] = ""
    tax_no: Annotated[str, Field(max_length=60)] = ""


class PharmacyOptionsOut(Schema):
    """Reference lists of the pharmacy screens."""

    stores: list[StoreOut]
    suppliers: list[SupplierOut]
    reasons_override: list[PharmacyReasonOut]
    reasons_stock_adjust: list[PharmacyReasonOut]
    reasons_line_cancel: list[PharmacyReasonOut]
    partial_dispense_remainder: RemainderCode = Field(
        ..., description="The center's default for the undispensed rest of a line (FLOW 6)"
    )
    default_store_id: int | None = Field(..., description="The first store that dispenses")


# --- item master ----------------------------------------------------------------------------


class PackUnitOut(Schema):
    id: int
    unit_code: str
    name_ar: str
    name_en: str
    factor: int = Field(..., description="Base units in one of this unit")
    barcode: str
    is_dispensable: bool
    is_purchase_unit: bool


class StockItemListOut(Schema):
    id: int
    service: PharmacyNameOut
    generic_name: str
    brand_name: str
    form: DosageFormCode
    strength: str
    base_unit_code: str
    base_unit_name_ar: str
    base_unit_name_en: str
    barcode: str
    min_stock: int
    reorder_qty: int
    storage: StorageCode
    is_controlled: bool
    active: bool
    on_hand: int = Field(..., description="Base units in every store")
    low: bool = Field(..., description="At or below the minimum")
    units: list[PackUnitOut]


class BatchStockOut(Schema):
    """One batch of an item in one store."""

    batch_id: int
    batch_no: str
    expiry_date: date
    unit_cost: CostStr
    store_id: int
    on_hand: int
    expired: bool
    days_left: int


class StockItemOut(StockItemListOut):
    batches: list[BatchStockOut]


class StoreBatchOut(BatchStockOut):
    """A batch with stock in a store, named for a picker."""

    item_id: int
    item_name: str
    base_unit_name_ar: str
    base_unit_name_en: str


class StockItemIn(Schema):
    service_id: int
    generic_name: Annotated[str, Field(min_length=1, max_length=200)]
    brand_name: Annotated[str, Field(max_length=200)] = ""
    form: DosageFormCode = "tablet"
    strength: Annotated[str, Field(max_length=60)] = ""
    base_unit_code: Annotated[str, Field(min_length=1, max_length=20)]
    base_unit_name_ar: Annotated[str, Field(min_length=1, max_length=50)]
    base_unit_name_en: Annotated[str, Field(min_length=1, max_length=50)]
    barcode: Annotated[str, Field(max_length=60)] = ""
    min_stock: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    reorder_qty: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    storage: StorageCode = "room"
    is_controlled: bool = False


class StockItemPatch(Schema):
    generic_name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    brand_name: Annotated[str, Field(max_length=200)] | None = None
    form: DosageFormCode | None = None
    strength: Annotated[str, Field(max_length=60)] | None = None
    base_unit_name_ar: Annotated[str, Field(min_length=1, max_length=50)] | None = None
    base_unit_name_en: Annotated[str, Field(min_length=1, max_length=50)] | None = None
    barcode: Annotated[str, Field(max_length=60)] | None = None
    min_stock: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    reorder_qty: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    storage: StorageCode | None = None
    is_controlled: bool | None = None
    active: bool | None = None


class PackUnitIn(Schema):
    unit_code: Annotated[str, Field(min_length=1, max_length=20)]
    name_ar: Annotated[str, Field(min_length=1, max_length=50)]
    name_en: Annotated[str, Field(min_length=1, max_length=50)]
    factor: Annotated[int, Field(ge=2, le=100_000)]
    barcode: Annotated[str, Field(max_length=60)] = ""
    is_dispensable: bool = True
    is_purchase_unit: bool = False


class PackUnitPatch(Schema):
    name_ar: Annotated[str, Field(min_length=1, max_length=50)] | None = None
    name_en: Annotated[str, Field(min_length=1, max_length=50)] | None = None
    barcode: Annotated[str, Field(max_length=60)] | None = None
    is_dispensable: bool | None = None
    is_purchase_unit: bool | None = None


class StockServiceOptionOut(Schema):
    """A drug or consumable catalog service without a stock item yet."""

    id: int
    code: str
    name_ar: str
    name_en: str
    kind: str


class ScanResultOut(Schema):
    """What a scanned barcode names."""

    item: StockItemListOut
    unit_code: str | None = Field(..., description="The pack unit whose barcode was scanned")


class StockCardRowOut(Schema):
    id: int
    moved_at: datetime
    kind: MoveKindCode
    qty_base: int
    balance: int = Field(..., description="The item's on-hand after the move (store or all)")
    batch_balance: int = Field(..., description="The batch's on-hand in the store after it")
    batch_no: str
    expiry_date: date
    store: PharmacyNameOut
    source_type: str
    source_id: int | None
    note: str
    created_by: PharmacyUserRefOut


class StockCardOut(Schema):
    item: StockItemListOut
    store_id: int | None
    rows: list[StockCardRowOut]


# --- dispensing -----------------------------------------------------------------------------


class DispensePatientOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: str
    date_of_birth: date | None


class DispensePrescriptionOut(Schema):
    dose: str
    route: str
    frequency_code: str
    frequency_per_day: str | None
    duration_days: int | None
    as_needed: bool
    instructions: str


class DispenseQueueLineOut(Schema):
    id: int
    service: PharmacyNameOut
    kind: str
    item_id: int | None = Field(..., description="None: the service has no stock item")
    base_unit_name_ar: str
    base_unit_name_en: str
    quantity: int
    dispensed: int
    remaining: int
    authorized: bool = Field(..., description="Perform-first authorization, not paid")
    started: bool
    ordered_at: datetime
    note: str
    prescription: DispensePrescriptionOut | None


class DispenseQueueVisitOut(Schema):
    visit_id: int
    visit_number: str
    visit_type: str
    created_at: datetime
    patient: DispensePatientOut
    lines: list[DispenseQueueLineOut]


class FefoPickOut(Schema):
    batch_id: int
    quantity: int


class DispenseLineOptionsOut(DispenseQueueLineOut):
    units: list[PackUnitOut]
    batches: list[BatchStockOut] = Field(..., description="The store's batches, FEFO order")
    fefo: list[FefoPickOut] | None = Field(
        ..., description="The FEFO suggestion for every remaining unit; None if stock is short"
    )
    available: int = Field(..., description="Usable base units in the store")


class DispenseVisitOut(Schema):
    visit_id: int
    visit_number: str
    visit_type: str
    created_at: datetime
    patient: DispensePatientOut
    store: StoreOut
    lines: list[DispenseLineOptionsOut]


class DispenseBatchIn(Schema):
    batch_id: int
    quantity: Qty = Field(..., description="Base units from this batch")


class DispenseLineIn(Schema):
    service_line_id: int
    quantity: Qty
    unit_code: Annotated[str, Field(max_length=20)] | None = Field(
        None, description="Pack unit of `quantity`; the base unit when empty"
    )
    batches: list[DispenseBatchIn] | None = Field(
        None, description="Another choice than the FEFO suggestion (needs a reason)"
    )
    override_reason: Annotated[str, Field(max_length=40)] | None = None
    override_note: Note = ""
    remainder: RemainderCode | None = Field(
        None,
        description=(
            "When this does not give every remaining unit: keep the rest open (defer) or "
            "cancel and refund it (needs a billing.approve_credit_note holder). None follows "
            "the center's policy."
        ),
    )


class DispenseIn(Schema):
    visit_id: int
    store_id: int
    lines: Annotated[list[DispenseLineIn], Field(min_length=1, max_length=50)]
    note: Annotated[str, Field(max_length=500)] = ""
    approver: ApproverIn | None = Field(
        None, description="A supervisor approving a refunded remainder at the counter"
    )


class DispenseLineOut(Schema):
    id: int
    service_line_id: int
    service: PharmacyNameOut
    batch_no: str
    expiry_date: date
    unit_code: str | None
    quantity_units: int
    qty_base: int
    batch_override: bool
    override_reason: str | None


class DispenseOut(Schema):
    id: int
    number: str
    visit_id: int
    visit_number: str
    store: StoreOut
    dispensed_by: PharmacyUserRefOut
    dispensed_at: datetime
    lines: list[DispenseLineOut]


# --- dispense returns (ADR 0018) --------------------------------------------------------------


class ReturnCreditNoteOut(Schema):
    id: int
    number: str


class DispenseReturnOut(Schema):
    number: str
    qty_base: int
    reason: PharmacyReasonOut | None
    note: str
    returned_by: PharmacyUserRefOut | None
    approved_by: PharmacyUserRefOut | None = Field(
        ..., description="The second person who approved (billed lines only)"
    )
    returned_at: datetime
    credit_note_number: str | None


class ReturnableLineOut(Schema):
    id: int = Field(..., description="The dispense line")
    service_line_id: int
    service: PharmacyNameOut
    batch_no: str
    expiry_date: date
    unit_code: str | None
    qty_base: int = Field(..., description="Base units dispensed")
    returned: int = Field(..., description="Base units already returned")
    returnable: int = Field(..., description="Base units that may still come back")
    billing_status: str
    needs_approver: bool = Field(
        ..., description="A billed line: a second person approves the return"
    )
    credit_notes: list[ReturnCreditNoteOut] = Field(
        ..., description="Approved credit notes that credit the line (the cashier's refund)"
    )
    returns: list[DispenseReturnOut]


class ReturnableDispenseOut(Schema):
    id: int
    number: str
    visit_id: int
    visit_number: str
    patient: DispensePatientOut
    store: StoreOut
    dispensed_by: PharmacyUserRefOut
    dispensed_at: datetime
    lines: list[ReturnableLineOut]


class DispenseReturnIn(Schema):
    """Units a patient brought back (FEATURES 8.4): base units, an ``stock_adjust`` reason, and
    for a billed line a second person's credentials (``pharmacy.approve_return``)."""

    quantity: Qty
    reason_code: Code
    note: Note = ""
    credit_note_id: int | None = Field(
        None, description="An approved credit note crediting the line (links the refund)"
    )
    approver: ApproverIn | None = Field(
        None, description="Required for a billed line: someone else approves"
    )


# --- goods receipts -------------------------------------------------------------------------


class GoodsReceiptLineIn(Schema):
    item_id: int
    batch_no: Annotated[str, Field(min_length=1, max_length=60)]
    expiry_date: date
    quantity: Qty
    unit_code: Annotated[str, Field(max_length=20)] | None = None
    unit_cost: CostIn = Field(..., description="Cost of one `unit_code` (or base unit)")


class GoodsReceiptIn(Schema):
    supplier_id: int
    store_id: int
    supplier_invoice_no: Annotated[str, Field(max_length=60)] = ""
    supplier_invoice_date: date | None = None
    note: Annotated[str, Field(max_length=500)] = ""
    lines: Annotated[list[GoodsReceiptLineIn], Field(min_length=1, max_length=200)]


class GoodsReceiptLineOut(Schema):
    id: int
    item_id: int
    item_name: str
    batch_no: str
    expiry_date: date
    unit_code: str | None
    quantity_units: int
    qty_base: int
    unit_cost: CostStr
    line_total: PharmacyMoneyStr


class GoodsReceiptOut(Schema):
    id: int
    number: str
    status: ReceiptStatusCode
    supplier: PharmacyNameOut
    store: StoreOut
    supplier_invoice_no: str
    supplier_invoice_date: date | None
    note: str
    total_cost: PharmacyMoneyStr
    created_by: PharmacyUserRefOut
    created_at: datetime
    posted_by: PharmacyUserRefOut | None
    posted_at: datetime | None
    lines: list[GoodsReceiptLineOut]


# --- adjustments ----------------------------------------------------------------------------


class StockAdjustmentLineIn(Schema):
    batch_id: int
    qty_base: SignedQty = Field(..., description="Signed change in base units (not zero)")
    note: Note = ""


class StockAdjustmentIn(Schema):
    store_id: int
    reason_code: Annotated[str, Field(min_length=1, max_length=40)]
    note: Annotated[str, Field(max_length=1000)] = ""
    lines: Annotated[list[StockAdjustmentLineIn], Field(min_length=1, max_length=100)]


class AdjustmentDecisionIn(Schema):
    note: Annotated[str, Field(max_length=1000)] = ""


class StockAdjustmentLineOut(Schema):
    id: int
    item_id: int
    item_name: str
    batch_id: int
    batch_no: str
    expiry_date: date
    qty_base: int
    note: str


class StockAdjustmentOut(Schema):
    id: int
    number: str
    status: AdjustmentStatusCode
    store: StoreOut
    reason: PharmacyReasonOut
    note: str
    requested_by: PharmacyUserRefOut
    requested_at: datetime
    decided_by: PharmacyUserRefOut | None
    decided_at: datetime | None
    decision_note: str
    lines: list[StockAdjustmentLineOut]


# --- counts ---------------------------------------------------------------------------------


class StockCountIn(Schema):
    store_id: int
    note: Annotated[str, Field(max_length=1000)] = ""
    item_ids: list[int] | None = Field(None, description="Count only these items")


class CountRecordIn(Schema):
    batch_id: int
    counted_qty: Annotated[int, Field(ge=0, le=10_000_000)]
    note: Note = ""


class StockCountLineOut(Schema):
    id: int
    item_id: int
    item_name: str
    base_unit_name_ar: str
    base_unit_name_en: str
    batch_id: int
    batch_no: str
    expiry_date: date
    book_qty: int
    counted_qty: int | None
    variance: int | None
    variance_value: PharmacyMoneyStr | None
    counted_by: PharmacyUserRefOut | None
    counted_at: datetime | None
    note: str


class StockCountOut(Schema):
    id: int
    number: str
    status: CountStatusCode
    store: StoreOut
    note: str
    started_by: PharmacyUserRefOut
    started_at: datetime
    posted_by: PharmacyUserRefOut | None
    posted_at: datetime | None
    counted: int
    total: int
    variance_value: PharmacyMoneyStr
    lines: list[StockCountLineOut]


# --- transfers ------------------------------------------------------------------------------


class StockTransferLineIn(Schema):
    batch_id: int
    qty_base: Qty


class StockTransferIn(Schema):
    from_store_id: int
    to_store_id: int
    note: Annotated[str, Field(max_length=500)] = ""
    lines: Annotated[list[StockTransferLineIn], Field(min_length=1, max_length=100)]


class TransferReceivedLineIn(Schema):
    line_id: int
    qty_base: Annotated[int, Field(ge=0, le=10_000_000)]


class TransferReceiveIn(Schema):
    lines: list[TransferReceivedLineIn] | None = Field(
        None, description="Base units that arrived per line; every unit sent when omitted"
    )
    shortage_reason: Annotated[str, Field(max_length=40)] | None = None
    shortage_note: Note = ""
    approver: ApproverIn | None = Field(
        None, description="A holder of pharmacy.approve_adjustment approving a shortage"
    )


class TransferCancelIn(Schema):
    note: Note = ""


class StockTransferLineOut(Schema):
    id: int
    item_id: int
    item_name: str
    batch_id: int
    batch_no: str
    expiry_date: date
    qty_base: int


class StockTransferOut(Schema):
    id: int
    number: str
    status: TransferStatusCode
    from_store: StoreOut
    to_store: StoreOut
    note: str
    created_by: PharmacyUserRefOut
    created_at: datetime
    sent_by: PharmacyUserRefOut | None
    sent_at: datetime | None
    received_by: PharmacyUserRefOut | None
    received_at: datetime | None
    shortage_reason: PharmacyReasonOut | None
    shortage_note: str
    shortage_approved_by: PharmacyUserRefOut | None
    cancelled_by: PharmacyUserRefOut | None
    cancelled_at: datetime | None
    cancel_note: str
    lines: list[StockTransferLineOut]


# --- reports --------------------------------------------------------------------------------


class ExpiringBatchOut(Schema):
    batch_id: int
    batch_no: str
    expiry_date: date
    days_left: int
    expired: bool
    item_id: int
    item_name: str
    base_unit_name_ar: str
    base_unit_name_en: str
    store: PharmacyNameOut
    on_hand: int
    value: PharmacyMoneyStr = Field(..., description="On-hand at batch cost")


class LowStockItemOut(Schema):
    item_id: int
    item_name: str
    service_code: str
    base_unit_name_ar: str
    base_unit_name_en: str
    on_hand: int
    min_stock: int
    reorder_qty: int
    suggested_order: int


# --- walk-in sale ---------------------------------------------------------------------------


class SaleCustomerOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    phone: str
    sex: str


class SaleServiceOut(Schema):
    """A drug or consumable a walk-in customer may buy, at today's cash price."""

    service_id: int
    code: str
    name_ar: str
    name_en: str
    kind: str
    unit_price: PharmacyMoneyStr | None = Field(..., description="None: no price today")
    item_id: int | None
    base_unit_name_ar: str
    base_unit_name_en: str
    on_hand: int


class SaleCustomerIn(Schema):
    """A new walk-in customer: a file with a name and sex (phone optional)."""

    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    sex: Literal["male", "female"]
    phone: Annotated[str, Field(max_length=30)] = ""


class SaleItemIn(Schema):
    service_id: int
    quantity: Qty
    note: Note = ""


class PharmacySaleIn(Schema):
    patient_id: int | None = Field(None, description="An existing file; or give `customer`")
    customer: SaleCustomerIn | None = None
    items: Annotated[list[SaleItemIn], Field(min_length=1, max_length=50)]
