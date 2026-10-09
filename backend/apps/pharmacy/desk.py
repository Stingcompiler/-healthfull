"""The pharmacy screens' commands (FEATURES 8.1-8.10, 5.12).

Each command resolves the request's references, runs ``apps.pharmacy.services`` (or the
billing service of the walk-in sale) and returns what the screen shows next
(``apps.pharmacy.queries``), so a router makes one call. Rules, row locks
(``select_for_update`` on stock balances), stock moves and audit context stay in the
services. A supervisor approving at the counter types their credentials (ADR 0009,
``apps.payments.approvals``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.billing import queries as billing_queries
from apps.billing import services as billing
from apps.catalog.models import Service
from apps.core.models import User
from apps.orders import services as orders
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.payments.approvals import ApproverLogin, resolve_approver
from apps.pharmacy import queries
from apps.pharmacy import services as ps
from apps.pharmacy.models import (
    Batch,
    GoodsReceipt,
    Item,
    StockAdjustment,
    StockCount,
    StockTransfer,
    Store,
    Supplier,
    UnitConversion,
)
from apps.visits.models import Visit
from domain.errors import DomainError

__all__ = [
    "DispenseLineCommand",
    "add_unit",
    "approve_adjustment",
    "cancel_count",
    "cancel_receipt",
    "cancel_transfer",
    "create_item",
    "create_receipt",
    "create_sale",
    "create_supplier",
    "create_transfer",
    "dispense",
    "post_count",
    "post_receipt",
    "receive_transfer",
    "record_count",
    "reject_adjustment",
    "request_adjustment",
    "send_transfer",
    "start_count",
    "update_item",
    "update_unit",
]


# --- items ----------------------------------------------------------------------------------


def create_item(*, actor: User, service_id: int, **fields: Any) -> dict[str, Any]:
    item = ps.create_item(service=Service.objects.get(pk=service_id), actor=actor, **fields)
    return queries.item_detail(item.pk)


def update_item(item_id: int, *, actor: User, fields: Mapping[str, Any]) -> dict[str, Any]:
    ps.update_item(Item.objects.get(pk=item_id), actor=actor, **fields)
    return queries.item_detail(item_id)


def add_unit(item_id: int, *, actor: User, **fields: Any) -> dict[str, Any]:
    ps.add_unit(Item.objects.get(pk=item_id), actor=actor, **fields)
    return queries.item_detail(item_id)


def update_unit(
    item_id: int, unit_id: int, *, actor: User, fields: Mapping[str, Any]
) -> dict[str, Any]:
    ps.update_unit(UnitConversion.objects.get(pk=unit_id, item_id=item_id), actor=actor, **fields)
    return queries.item_detail(item_id)


def create_supplier(*, actor: User, code: str, name_ar: str, name_en: str, **fields: str) -> Any:
    supplier = ps.create_supplier(
        code=code, name_ar=name_ar, name_en=name_en, actor=actor, **fields
    )
    return next(s for s in queries.suppliers() if s["id"] == supplier.pk)


# --- dispensing -----------------------------------------------------------------------------


class DispenseLineCommand:
    """One line of a dispense request as the screen sends it."""

    def __init__(
        self,
        *,
        service_line_id: int,
        quantity: int,
        unit_code: str | None = None,
        batches: Sequence[tuple[int, int]] | None = None,
        override_reason: str | None = None,
        override_note: str = "",
        remainder: str | None = None,
    ) -> None:
        self.request = ps.DispenseRequest(
            service_line_id=service_line_id,
            quantity=quantity,
            unit_code=unit_code or None,
            batches=(
                None if batches is None else [ps.BatchPick(b_id, qty) for b_id, qty in batches]
            ),
            override_reason_code=override_reason,
            override_note=override_note,
            complete=None if remainder is None else remainder == "refund",
        )


def dispense(
    *,
    actor: User,
    visit_id: int,
    store_id: int,
    lines: Sequence[DispenseLineCommand],
    note: str,
    approver: ApproverLogin | None,
) -> dict[str, Any]:
    """Dispense paid or authorized lines of a visit (FEATURES 8.2-8.4, invariants 1 and 5).

    A refunded remainder's credit note is approved by ``approver`` (a
    ``billing.approve_credit_note`` holder at the counter), else by the actor.
    """
    chosen = resolve_approver(approver, actor=actor)
    record = ps.dispense(
        visit=Visit.objects.get(pk=visit_id),
        store=Store.objects.get(pk=store_id),
        actor=actor,
        requests=[ln.request for ln in lines],
        note=note,
        approver=chosen,
    )
    return queries.dispense_detail(record.pk)


# --- goods receipts -------------------------------------------------------------------------


def create_receipt(
    *,
    actor: User,
    supplier_id: int,
    store_id: int,
    supplier_invoice_no: str,
    supplier_invoice_date: date | None,
    note: str,
    lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """A draft receipt with its lines, all or nothing (FEATURES 8.5)."""
    with transaction.atomic():
        receipt = ps.create_receipt(
            supplier=Supplier.objects.get(pk=supplier_id),
            store=Store.objects.get(pk=store_id),
            actor=actor,
            supplier_invoice_no=supplier_invoice_no,
            supplier_invoice_date=supplier_invoice_date,
            note=note,
        )
        items = {it.pk: it for it in Item.objects.filter(pk__in={ln["item_id"] for ln in lines})}
        for ln in lines:
            item = items.get(ln["item_id"])
            if item is None:
                raise Item.DoesNotExist(f"Item {ln['item_id']} not found")
            ps.add_receipt_line(
                receipt,
                item=item,
                batch_no=ln["batch_no"],
                expiry_date=ln["expiry_date"],
                quantity=ln["quantity"],
                unit_cost=Decimal(ln["unit_cost"]),
                unit_code=ln.get("unit_code") or None,
                actor=actor,
            )
    return queries.receipt_detail(receipt.pk)


def post_receipt(receipt_id: int, *, actor: User) -> dict[str, Any]:
    ps.post_receipt(GoodsReceipt.objects.get(pk=receipt_id), actor=actor)
    return queries.receipt_detail(receipt_id)


def cancel_receipt(receipt_id: int, *, actor: User) -> dict[str, Any]:
    ps.cancel_receipt(GoodsReceipt.objects.get(pk=receipt_id), actor=actor)
    return queries.receipt_detail(receipt_id)


# --- adjustments ----------------------------------------------------------------------------


def request_adjustment(
    *,
    actor: User,
    store_id: int,
    reason_code: str,
    note: str,
    lines: Sequence[tuple[int, int, str]],
) -> dict[str, Any]:
    adj = ps.request_adjustment(
        store=Store.objects.get(pk=store_id),
        reason_code=reason_code,
        lines=lines,
        actor=actor,
        note=note,
    )
    return queries.adjustment_detail(adj.pk)


def approve_adjustment(adjustment_id: int, *, actor: User, note: str) -> dict[str, Any]:
    ps.approve_adjustment(StockAdjustment.objects.get(pk=adjustment_id), actor=actor, note=note)
    return queries.adjustment_detail(adjustment_id)


def reject_adjustment(adjustment_id: int, *, actor: User, note: str) -> dict[str, Any]:
    ps.reject_adjustment(StockAdjustment.objects.get(pk=adjustment_id), actor=actor, note=note)
    return queries.adjustment_detail(adjustment_id)


# --- counts ---------------------------------------------------------------------------------


def start_count(
    *, actor: User, store_id: int, note: str, item_ids: Sequence[int] | None
) -> dict[str, Any]:
    items = None if item_ids is None else list(Item.objects.filter(pk__in=item_ids))
    count = ps.start_count(Store.objects.get(pk=store_id), actor=actor, items=items, note=note)
    return queries.count_detail(count.pk)


def record_count(
    count_id: int, *, actor: User, batch_id: int, counted_qty: int, note: str
) -> dict[str, Any]:
    ps.record_count(
        StockCount.objects.get(pk=count_id),
        batch=Batch.objects.get(pk=batch_id),
        counted_qty=counted_qty,
        actor=actor,
        note=note,
    )
    return queries.count_detail(count_id)


def post_count(count_id: int, *, actor: User) -> dict[str, Any]:
    ps.post_count(StockCount.objects.get(pk=count_id), actor=actor)
    return queries.count_detail(count_id)


def cancel_count(count_id: int, *, actor: User) -> dict[str, Any]:
    ps.cancel_count(StockCount.objects.get(pk=count_id), actor=actor)
    return queries.count_detail(count_id)


# --- transfers ------------------------------------------------------------------------------


def create_transfer(
    *,
    actor: User,
    from_store_id: int,
    to_store_id: int,
    note: str,
    lines: Sequence[tuple[int, int]],
) -> dict[str, Any]:
    transfer = ps.create_transfer(
        from_store=Store.objects.get(pk=from_store_id),
        to_store=Store.objects.get(pk=to_store_id),
        lines=lines,
        actor=actor,
        note=note,
    )
    return queries.transfer_detail(transfer.pk)


def send_transfer(transfer_id: int, *, actor: User) -> dict[str, Any]:
    ps.send_transfer(StockTransfer.objects.get(pk=transfer_id), actor=actor)
    return queries.transfer_detail(transfer_id)


def receive_transfer(
    transfer_id: int,
    *,
    actor: User,
    received: Mapping[int, int] | None,
    shortage_reason: str | None,
    shortage_note: str,
    approver: ApproverLogin | None,
) -> dict[str, Any]:
    """Receive a sent transfer; a shortage needs a reason and an approver holding
    ``pharmacy.approve_adjustment`` (the actor, or a supervisor at the counter)."""
    chosen = resolve_approver(approver, actor=actor)
    ps.receive_transfer(
        StockTransfer.objects.get(pk=transfer_id),
        actor=actor,
        received=received,
        shortage_reason_code=shortage_reason,
        shortage_note=shortage_note,
        approver=chosen,
    )
    return queries.transfer_detail(transfer_id)


def cancel_transfer(transfer_id: int, *, actor: User, note: str) -> dict[str, Any]:
    ps.cancel_transfer(StockTransfer.objects.get(pk=transfer_id), actor=actor, note=note)
    return queries.transfer_detail(transfer_id)


# --- walk-in sale ---------------------------------------------------------------------------


def create_sale(
    *,
    actor: User,
    patient_id: int | None,
    customer: Mapping[str, str] | None,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """A walk-in pharmacy sale (FEATURES 5.12): the customer's file (an existing one, or a
    new file with a name and sex), a ``pharmacy_sale`` visit, its lines and their draft
    invoice. The cashier approves and collects it; the pharmacy dispenses once paid.

    Raises:
        DomainError: ``CUSTOMER_REQUIRED`` (neither or both of ``patient_id`` and
            ``customer``), and the errors of registration and ``create_pharmacy_sale``.
    """
    if (patient_id is None) == (customer is None):
        raise DomainError("CUSTOMER_REQUIRED", "Choose a patient file or enter a new customer")
    with transaction.atomic():
        if patient_id is not None:
            patient = patients.resolve(Patient.objects.get(pk=patient_id))
        else:
            customer = customer or {}
            name = customer["full_name"].strip()
            arabic = any("؀" <= ch <= "ۿ" for ch in name)
            patient = patients.register_patient(
                patients.PatientData(
                    full_name_ar=name if arabic else "",
                    full_name_en="" if arabic else name,
                    sex=customer["sex"],
                    phone=customer.get("phone", ""),
                ),
                actor=actor,
                confirm_not_duplicate=True,
            )
        invoice = billing.create_pharmacy_sale(
            patient,
            [
                orders.LineInput(
                    service=it["service_id"], quantity=Decimal(it["quantity"]), note=it["note"]
                )
                for it in items
            ],
            actor=actor,
        )
    return billing_queries.invoice_detail(invoice.pk)
