"""``/api/pharmacy``: dispensing, items, stock, goods receipts, adjustments, counts, transfers,
expiry and low-stock reports, and the walk-in sale (FEATURES 8.1-8.10, 5.12).

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, schema in/out and
one call into ``apps.pharmacy.queries`` (reads) or ``apps.pharmacy.desk`` (commands). Rules
live in ``domain.stock`` and ``apps.pharmacy.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Status
from ninja.errors import AuthenticationError

from api.pagination import PageParams
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.billing.schemas import ApproverIn, InvoiceOut
from apps.core.models import User
from apps.payments.approvals import ApproverLogin
from apps.pharmacy import desk, queries
from apps.pharmacy.schemas import (
    AdjustmentDecisionIn,
    AdjustmentStatusCode,
    CountRecordIn,
    CountStatusCode,
    DispenseIn,
    DispenseOut,
    DispenseQueueVisitOut,
    DispenseVisitOut,
    ExpiringBatchOut,
    GoodsReceiptIn,
    GoodsReceiptOut,
    LowStockItemOut,
    PackUnitIn,
    PackUnitPatch,
    PharmacyOptionsOut,
    PharmacySaleIn,
    ReceiptStatusCode,
    SaleCustomerOut,
    SaleServiceOut,
    ScanResultOut,
    StockAdjustmentIn,
    StockAdjustmentOut,
    StockCardOut,
    StockCountIn,
    StockCountOut,
    StockItemIn,
    StockItemListOut,
    StockItemOut,
    StockItemPatch,
    StockServiceOptionOut,
    StockTransferIn,
    StockTransferOut,
    StoreBatchOut,
    SupplierIn,
    SupplierOut,
    TransferCancelIn,
    TransferReceiveIn,
    TransferStatusCode,
)

pharmacy_router = Router(tags=["pharmacy"])
add_ping(pharmacy_router, "pharmacy")

_READ = {**ERROR_RESPONSES, 404: ErrorOut}


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


def _approver(request: HttpRequest, approver: ApproverIn | None) -> ApproverLogin | None:
    if approver is None:
        return None
    return ApproverLogin(request, approver.username, approver.password)


# --- reference ------------------------------------------------------------------------------


@pharmacy_router.get(
    "/options",
    response={200: PharmacyOptionsOut, **_READ},
    operation_id="pharmacy_get_options",
    summary="Stores, suppliers, reason lists and the partial-dispense policy",
)
@require_perm("pharmacy.view")
def options(request: HttpRequest) -> Any:
    return queries.options()


@pharmacy_router.get(
    "/suppliers",
    response={200: list[SupplierOut], **_READ},
    operation_id="pharmacy_list_suppliers",
    summary="Active suppliers",
)
@require_perm("pharmacy.view")
def list_suppliers(request: HttpRequest) -> Any:
    return queries.suppliers()


@pharmacy_router.post(
    "/suppliers",
    response={201: SupplierOut, **_READ},
    operation_id="pharmacy_create_supplier",
    summary="Add a supplier",
)
@require_perm("pharmacy.manage_suppliers")
def create_supplier(request: HttpRequest, payload: SupplierIn) -> Any:
    return Status(201, desk.create_supplier(actor=_user(request), **payload.dict()))


@pharmacy_router.get(
    "/stores/{store_id}/batches",
    response={200: list[StoreBatchOut], **_READ},
    operation_id="pharmacy_list_store_batches",
    summary="Batches with stock in a store (search by item, batch number or barcode)",
)
@require_perm("pharmacy.view")
def store_batches(
    request: HttpRequest,
    store_id: int,
    q: str | None = Query(None, max_length=200),
    item_id: int | None = None,
) -> Any:
    return queries.store_batches(store_id=store_id, q=q, item_id=item_id)


# --- items ----------------------------------------------------------------------------------


@pharmacy_router.get(
    "/items",
    response={200: Page[StockItemListOut], **_READ},
    operation_id="pharmacy_list_items",
    summary="Stock items by name, brand, service code or barcode, with total on-hand",
)
@require_perm("pharmacy.view")
def list_items(
    request: HttpRequest,
    params: Query[PageParams],
    low: bool = False,
    active: bool | None = None,
) -> Any:
    return queries.items(
        q=params.q, page=params.page, page_size=params.page_size, low_only=low, active=active
    )


@pharmacy_router.get(
    "/items/scan",
    response={200: ScanResultOut, **_READ},
    operation_id="pharmacy_scan_barcode",
    summary="The item (and pack unit) a scanned barcode names",
)
@require_perm("pharmacy.view")
def scan(request: HttpRequest, code: str = Query(..., min_length=1, max_length=60)) -> Any:
    return queries.scan(code)


@pharmacy_router.get(
    "/items/services",
    response={200: list[StockServiceOptionOut], **_READ},
    operation_id="pharmacy_list_stock_services",
    summary="Drug and consumable catalog services that have no stock item yet",
)
@require_perm("pharmacy.manage_items")
def stock_services(request: HttpRequest) -> Any:
    return queries.stock_services()


@pharmacy_router.post(
    "/items",
    response={201: StockItemOut, **_READ},
    operation_id="pharmacy_create_item",
    summary="Create the stock item of a drug or consumable service",
)
@require_perm("pharmacy.manage_items")
def create_item(request: HttpRequest, payload: StockItemIn) -> Any:
    return Status(201, desk.create_item(actor=_user(request), **payload.dict()))


@pharmacy_router.get(
    "/items/{item_id}",
    response={200: StockItemOut, **_READ},
    operation_id="pharmacy_get_item",
    summary="One item with its units and batches on hand per store",
)
@require_perm("pharmacy.view")
def get_item(request: HttpRequest, item_id: int) -> Any:
    return queries.item_detail(item_id)


@pharmacy_router.patch(
    "/items/{item_id}",
    response={200: StockItemOut, **_READ},
    operation_id="pharmacy_update_item",
    summary="Edit an item's master data (the base unit stays)",
)
@require_perm("pharmacy.manage_items")
def update_item(request: HttpRequest, item_id: int, payload: StockItemPatch) -> Any:
    return desk.update_item(
        item_id, actor=_user(request), fields=payload.dict(exclude_unset=True, exclude_none=True)
    )


@pharmacy_router.post(
    "/items/{item_id}/units",
    response={201: StockItemOut, **_READ},
    operation_id="pharmacy_add_unit",
    summary="Add a pack unit (strip, box) holding a whole number of base units",
)
@require_perm("pharmacy.manage_items")
def add_unit(request: HttpRequest, item_id: int, payload: PackUnitIn) -> Any:
    return Status(201, desk.add_unit(item_id, actor=_user(request), **payload.dict()))


@pharmacy_router.patch(
    "/items/{item_id}/units/{unit_id}",
    response={200: StockItemOut, **_READ},
    operation_id="pharmacy_update_unit",
    summary="Rename a pack unit or change its barcode and flags (the factor stays)",
)
@require_perm("pharmacy.manage_items")
def update_unit(request: HttpRequest, item_id: int, unit_id: int, payload: PackUnitPatch) -> Any:
    return desk.update_unit(
        item_id,
        unit_id,
        actor=_user(request),
        fields=payload.dict(exclude_unset=True, exclude_none=True),
    )


@pharmacy_router.get(
    "/items/{item_id}/stock-card",
    response={200: StockCardOut, **_READ},
    operation_id="pharmacy_get_stock_card",
    summary="Every stock move of an item with running balances, newest first",
)
@require_perm("pharmacy.view")
def stock_card(request: HttpRequest, item_id: int, store_id: int | None = None) -> Any:
    return queries.stock_card(item_id, store_id=store_id)


# --- dispensing -----------------------------------------------------------------------------


@pharmacy_router.get(
    "/queue",
    response={200: list[DispenseQueueVisitOut], **_READ},
    operation_id="pharmacy_list_queue",
    summary="Visits with paid or authorized drug lines to dispense (search or scan a number)",
)
@require_perm("pharmacy.dispense")
def queue(request: HttpRequest, q: str | None = Query(None, max_length=200)) -> Any:
    return queries.queue(q=q)


@pharmacy_router.get(
    "/queue/visits/{visit_id}",
    response={200: DispenseVisitOut, **_READ},
    operation_id="pharmacy_get_dispense_visit",
    summary="A visit's dispensable lines with units, batches and the FEFO suggestion",
)
@require_perm("pharmacy.dispense")
def dispense_visit(request: HttpRequest, visit_id: int, store_id: int | None = None) -> Any:
    return queries.dispense_visit(visit_id, store_id=store_id)


@pharmacy_router.post(
    "/dispenses",
    response={201: DispenseOut, **_READ},
    operation_id="pharmacy_create_dispense",
    summary="Dispense paid or authorized lines (FEFO, or other batches with a reason)",
    description=(
        "Stock leaves at this moment (invariant 5). A line given in part keeps its rest open "
        "(`remainder: defer`) or cancels and refunds it (`refund`), which needs a "
        "billing.approve_credit_note holder: the actor, or a supervisor typing their "
        "credentials into `approver` (409 APPROVER_INVALID on wrong credentials)."
    ),
)
@require_perm("pharmacy.dispense")
def create_dispense(request: HttpRequest, payload: DispenseIn) -> Any:
    return Status(
        201,
        desk.dispense(
            actor=_user(request),
            visit_id=payload.visit_id,
            store_id=payload.store_id,
            lines=[
                desk.DispenseLineCommand(
                    service_line_id=ln.service_line_id,
                    quantity=ln.quantity,
                    unit_code=ln.unit_code,
                    batches=(
                        None
                        if ln.batches is None
                        else [(b.batch_id, b.quantity) for b in ln.batches]
                    ),
                    override_reason=ln.override_reason,
                    override_note=ln.override_note,
                    remainder=ln.remainder,
                )
                for ln in payload.lines
            ],
            note=payload.note,
            approver=_approver(request, payload.approver),
        ),
    )


@pharmacy_router.get(
    "/dispenses/{dispense_id}",
    response={200: DispenseOut, **_READ},
    operation_id="pharmacy_get_dispense",
    summary="One dispense with its batches",
)
@require_perm("pharmacy.dispense")
def get_dispense(request: HttpRequest, dispense_id: int) -> Any:
    return queries.dispense_detail(dispense_id)


# --- goods receipts -------------------------------------------------------------------------


@pharmacy_router.get(
    "/receipts",
    response={200: Page[GoodsReceiptOut], **_READ},
    operation_id="pharmacy_list_receipts",
    summary="Goods receipts, newest first",
)
@require_perm("pharmacy.view")
def list_receipts(
    request: HttpRequest, params: Query[PageParams], status: ReceiptStatusCode | None = None
) -> Any:
    return queries.receipts(status=status, q=params.q, page=params.page, page_size=params.page_size)


@pharmacy_router.post(
    "/receipts",
    response={201: GoodsReceiptOut, **_READ},
    operation_id="pharmacy_create_receipt",
    summary="Draft a goods receipt with its batches (nothing is in stock until posted)",
)
@require_perm("pharmacy.receive_goods")
def create_receipt(request: HttpRequest, payload: GoodsReceiptIn) -> Any:
    data = payload.dict()
    return Status(201, desk.create_receipt(actor=_user(request), **data))


@pharmacy_router.get(
    "/receipts/{receipt_id}",
    response={200: GoodsReceiptOut, **_READ},
    operation_id="pharmacy_get_receipt",
    summary="One goods receipt with its lines",
)
@require_perm("pharmacy.view")
def get_receipt(request: HttpRequest, receipt_id: int) -> Any:
    return queries.receipt_detail(receipt_id)


@pharmacy_router.post(
    "/receipts/{receipt_id}/post",
    response={200: GoodsReceiptOut, **_READ},
    operation_id="pharmacy_post_receipt",
    summary="Post a draft receipt: its batches enter the store",
)
@require_perm("pharmacy.receive_goods")
def post_receipt(request: HttpRequest, receipt_id: int) -> Any:
    return desk.post_receipt(receipt_id, actor=_user(request))


@pharmacy_router.post(
    "/receipts/{receipt_id}/cancel",
    response={200: GoodsReceiptOut, **_READ},
    operation_id="pharmacy_cancel_receipt",
    summary="Cancel a draft receipt",
)
@require_perm("pharmacy.receive_goods")
def cancel_receipt(request: HttpRequest, receipt_id: int) -> Any:
    return desk.cancel_receipt(receipt_id, actor=_user(request))


# --- adjustments ----------------------------------------------------------------------------


@pharmacy_router.get(
    "/adjustments",
    response={200: Page[StockAdjustmentOut], **_READ},
    operation_id="pharmacy_list_adjustments",
    summary="Stock adjustments, newest first (status=draft: the approval queue)",
)
@require_perm("pharmacy.view")
def list_adjustments(
    request: HttpRequest, params: Query[PageParams], status: AdjustmentStatusCode | None = None
) -> Any:
    return queries.adjustments(
        status=status, q=params.q, page=params.page, page_size=params.page_size
    )


@pharmacy_router.post(
    "/adjustments",
    response={201: StockAdjustmentOut, **_READ},
    operation_id="pharmacy_request_adjustment",
    summary="Request a stock adjustment with a reason (a supervisor approves it)",
)
@require_perm("pharmacy.request_adjustment")
def request_adjustment(request: HttpRequest, payload: StockAdjustmentIn) -> Any:
    return Status(
        201,
        desk.request_adjustment(
            actor=_user(request),
            store_id=payload.store_id,
            reason_code=payload.reason_code,
            note=payload.note,
            lines=[(ln.batch_id, ln.qty_base, ln.note) for ln in payload.lines],
        ),
    )


@pharmacy_router.get(
    "/adjustments/{adjustment_id}",
    response={200: StockAdjustmentOut, **_READ},
    operation_id="pharmacy_get_adjustment",
    summary="One stock adjustment",
)
@require_perm("pharmacy.view")
def get_adjustment(request: HttpRequest, adjustment_id: int) -> Any:
    return queries.adjustment_detail(adjustment_id)


@pharmacy_router.post(
    "/adjustments/{adjustment_id}/approve",
    response={200: StockAdjustmentOut, **_READ},
    operation_id="pharmacy_approve_adjustment",
    summary="Approve and post an adjustment (someone other than its requester)",
)
@require_perm("pharmacy.approve_adjustment")
def approve_adjustment(
    request: HttpRequest, adjustment_id: int, payload: AdjustmentDecisionIn
) -> Any:
    return desk.approve_adjustment(adjustment_id, actor=_user(request), note=payload.note)


@pharmacy_router.post(
    "/adjustments/{adjustment_id}/reject",
    response={200: StockAdjustmentOut, **_READ},
    operation_id="pharmacy_reject_adjustment",
    summary="Reject an adjustment with a reason",
)
@require_perm("pharmacy.approve_adjustment")
def reject_adjustment(
    request: HttpRequest, adjustment_id: int, payload: AdjustmentDecisionIn
) -> Any:
    return desk.reject_adjustment(adjustment_id, actor=_user(request), note=payload.note)


# --- counts ---------------------------------------------------------------------------------


@pharmacy_router.get(
    "/counts",
    response={200: Page[StockCountOut], **_READ},
    operation_id="pharmacy_list_counts",
    summary="Stock count sessions, newest first",
)
@require_perm("pharmacy.view")
def list_counts(
    request: HttpRequest, params: Query[PageParams], status: CountStatusCode | None = None
) -> Any:
    return queries.counts(status=status, q=params.q, page=params.page, page_size=params.page_size)


@pharmacy_router.post(
    "/counts",
    response={201: StockCountOut, **_READ},
    operation_id="pharmacy_start_count",
    summary="Open a count session listing the store's batches with stock",
)
@require_perm("pharmacy.count_stock")
def start_count(request: HttpRequest, payload: StockCountIn) -> Any:
    return Status(
        201,
        desk.start_count(
            actor=_user(request),
            store_id=payload.store_id,
            note=payload.note,
            item_ids=payload.item_ids,
        ),
    )


@pharmacy_router.get(
    "/counts/{count_id}",
    response={200: StockCountOut, **_READ},
    operation_id="pharmacy_get_count",
    summary="One count session: book, counted and variance per batch",
)
@require_perm("pharmacy.view")
def get_count(request: HttpRequest, count_id: int) -> Any:
    return queries.count_detail(count_id)


@pharmacy_router.post(
    "/counts/{count_id}/record",
    response={200: StockCountOut, **_READ},
    operation_id="pharmacy_record_count",
    summary="Enter or correct the counted quantity of a batch (base units)",
)
@require_perm("pharmacy.count_stock")
def record_count(request: HttpRequest, count_id: int, payload: CountRecordIn) -> Any:
    return desk.record_count(
        count_id,
        actor=_user(request),
        batch_id=payload.batch_id,
        counted_qty=payload.counted_qty,
        note=payload.note,
    )


@pharmacy_router.post(
    "/counts/{count_id}/post",
    response={200: StockCountOut, **_READ},
    operation_id="pharmacy_post_count",
    summary="Post the variances as count corrections",
)
@require_perm("pharmacy.post_count")
def post_count(request: HttpRequest, count_id: int) -> Any:
    return desk.post_count(count_id, actor=_user(request))


@pharmacy_router.post(
    "/counts/{count_id}/cancel",
    response={200: StockCountOut, **_READ},
    operation_id="pharmacy_cancel_count",
    summary="Cancel an open count session (nothing moves)",
)
@require_perm("pharmacy.count_stock")
def cancel_count(request: HttpRequest, count_id: int) -> Any:
    return desk.cancel_count(count_id, actor=_user(request))


# --- transfers ------------------------------------------------------------------------------


@pharmacy_router.get(
    "/transfers",
    response={200: Page[StockTransferOut], **_READ},
    operation_id="pharmacy_list_transfers",
    summary="Transfers between stores, newest first",
)
@require_perm("pharmacy.view")
def list_transfers(
    request: HttpRequest, params: Query[PageParams], status: TransferStatusCode | None = None
) -> Any:
    return queries.transfers(
        status=status, q=params.q, page=params.page, page_size=params.page_size
    )


@pharmacy_router.post(
    "/transfers",
    response={201: StockTransferOut, **_READ},
    operation_id="pharmacy_create_transfer",
    summary="Draft a transfer of batches from one store to another",
)
@require_perm("pharmacy.transfer_stock")
def create_transfer(request: HttpRequest, payload: StockTransferIn) -> Any:
    return Status(
        201,
        desk.create_transfer(
            actor=_user(request),
            from_store_id=payload.from_store_id,
            to_store_id=payload.to_store_id,
            note=payload.note,
            lines=[(ln.batch_id, ln.qty_base) for ln in payload.lines],
        ),
    )


@pharmacy_router.get(
    "/transfers/{transfer_id}",
    response={200: StockTransferOut, **_READ},
    operation_id="pharmacy_get_transfer",
    summary="One transfer with its lines",
)
@require_perm("pharmacy.view")
def get_transfer(request: HttpRequest, transfer_id: int) -> Any:
    return queries.transfer_detail(transfer_id)


@pharmacy_router.post(
    "/transfers/{transfer_id}/send",
    response={200: StockTransferOut, **_READ},
    operation_id="pharmacy_send_transfer",
    summary="Send a draft transfer: stock leaves the source store",
)
@require_perm("pharmacy.transfer_stock")
def send_transfer(request: HttpRequest, transfer_id: int) -> Any:
    return desk.send_transfer(transfer_id, actor=_user(request))


@pharmacy_router.post(
    "/transfers/{transfer_id}/receive",
    response={200: StockTransferOut, **_READ},
    operation_id="pharmacy_receive_transfer",
    summary="Receive a sent transfer (a shortage needs a reason and an approver)",
)
@require_perm("pharmacy.transfer_stock")
def receive_transfer(request: HttpRequest, transfer_id: int, payload: TransferReceiveIn) -> Any:
    return desk.receive_transfer(
        transfer_id,
        actor=_user(request),
        received=(
            None if payload.lines is None else {ln.line_id: ln.qty_base for ln in payload.lines}
        ),
        shortage_reason=payload.shortage_reason,
        shortage_note=payload.shortage_note,
        approver=_approver(request, payload.approver),
    )


@pharmacy_router.post(
    "/transfers/{transfer_id}/cancel",
    response={200: StockTransferOut, **_READ},
    operation_id="pharmacy_cancel_transfer",
    summary="Cancel a draft or sent transfer (a sent one returns its stock; note required)",
)
@require_perm("pharmacy.transfer_stock")
def cancel_transfer(request: HttpRequest, transfer_id: int, payload: TransferCancelIn) -> Any:
    return desk.cancel_transfer(transfer_id, actor=_user(request), note=payload.note)


# --- reports --------------------------------------------------------------------------------


@pharmacy_router.get(
    "/reports/expiry",
    response={200: list[ExpiringBatchOut], **_READ},
    operation_id="pharmacy_get_expiry_report",
    summary="Batches with stock expiring within `days` (30, 60 or 90 on screen; expired included)",
)
@require_perm("pharmacy.view")
def expiry_report(
    request: HttpRequest, days: int = Query(30, ge=1, le=365), store_id: int | None = None
) -> Any:
    return queries.expiry(days=days, store_id=store_id)


@pharmacy_router.get(
    "/reports/low-stock",
    response={200: list[LowStockItemOut], **_READ},
    operation_id="pharmacy_get_low_stock",
    summary="Items at or below their minimum, with a reorder suggestion",
)
@require_perm("pharmacy.view")
def low_stock_report(request: HttpRequest, store_id: int | None = None) -> Any:
    return queries.low_stock(store_id=store_id)


# --- walk-in sale ---------------------------------------------------------------------------


@pharmacy_router.get(
    "/sale/customers",
    response={200: list[SaleCustomerOut], **_READ},
    operation_id="pharmacy_list_sale_customers",
    summary="Patient files a walk-in sale may be billed to",
)
@require_perm("billing.pharmacy_sale")
def sale_customers(request: HttpRequest, q: str = Query(..., min_length=1, max_length=200)) -> Any:
    return queries.sale_customers(q)


@pharmacy_router.get(
    "/sale/services",
    response={200: list[SaleServiceOut], **_READ},
    operation_id="pharmacy_list_sale_services",
    summary="Drugs and consumables for sale, with today's cash price and on-hand",
)
@require_perm("billing.pharmacy_sale")
def sale_services(request: HttpRequest, q: str | None = Query(None, max_length=200)) -> Any:
    return queries.sale_services(q)


@pharmacy_router.post(
    "/sales",
    response={201: InvoiceOut, **_READ},
    operation_id="pharmacy_create_sale",
    summary="A walk-in sale: the customer's draft pharmacy invoice (the cashier collects)",
)
@require_perm("billing.pharmacy_sale")
def create_sale(request: HttpRequest, payload: PharmacySaleIn) -> Any:
    return Status(
        201,
        desk.create_sale(
            actor=_user(request),
            patient_id=payload.patient_id,
            customer=None if payload.customer is None else payload.customer.dict(),
            items=[it.dict() for it in payload.items],
        ),
    )
