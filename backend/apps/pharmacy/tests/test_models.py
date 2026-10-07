"""Stock ledger and documents (ARCHITECTURE 4.8, invariant 5)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.pharmacy.models import (
    Dispense,
    DispenseLine,
    GoodsReceipt,
    GoodsReceiptLine,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockCount,
    StockMove,
    StockTransfer,
    Supplier,
    UnitConversion,
)

pytestmark = pytest.mark.django_db


def _on_hand(batch: Any, store: Any) -> Decimal:
    row = StockBalance.objects.filter(batch=batch, store=store).first()
    return row.qty_base if row else Decimal("0")


# --- StockMove: append-only ledger, balance projection, never negative --------------------


def test_moves_maintain_the_balance() -> None:
    batch, store = b.batch(), b.store()
    b.stock_move(batch, store, "100", "receipt")
    b.stock_move(batch, store, "-30", "dispense")
    b.stock_move(batch, store, "-5", "adjustment")
    assert _on_hand(batch, store) == Decimal("65.000")
    assert StockMove.objects.filter(batch=batch).count() == 3


def test_stock_never_goes_negative() -> None:
    batch, store = b.batch(), b.store()
    b.stock_move(batch, store, "10", "receipt")
    with (
        pytest.raises(IntegrityError, match="pharmacy_balance_never_negative"),
        transaction.atomic(),
    ):
        b.stock_move(batch, store, "-11", "dispense")
    # Nothing was written: the move and the balance roll back together.
    assert _on_hand(batch, store) == Decimal("10.000")
    assert StockMove.objects.filter(batch=batch).count() == 1
    # A store that never received the batch cannot dispense it either.
    with (
        pytest.raises(IntegrityError, match="pharmacy_balance_never_negative"),
        transaction.atomic(),
    ):
        b.stock_move(batch, b.store(), "-1", "dispense")


def test_negative_stock_rejected_through_raw_sql_too() -> None:
    batch, store = b.batch(), b.store()
    user = b.user()
    b.sql_rejects(
        "INSERT INTO pharmacy_stockmove (item_id, batch_id, store_id, qty_base, kind, "
        "source_type, unit_cost, note, created_by_id, moved_at) "
        "VALUES (%s, %s, %s, -1, 'dispense', 'raw', 0, '', %s, now())",
        [batch.item_id, batch.pk, store.pk, user.pk],
        "pharmacy_balance_never_negative",
    )


def test_stock_move_is_append_only_orm_and_raw_sql() -> None:
    batch, store = b.batch(), b.store()
    move = b.stock_move(batch, store, "10")
    b.db_rejects(
        lambda: StockMove.objects.filter(pk=move.pk).update(qty_base=Decimal("1000")),
        "APPEND_ONLY",
    )
    b.db_rejects(lambda: StockMove.objects.filter(pk=move.pk).delete(), "APPEND_ONLY")
    b.sql_rejects(
        "UPDATE pharmacy_stockmove SET qty_base = 1000 WHERE id = %s", [move.pk], "APPEND_ONLY"
    )
    b.sql_rejects("DELETE FROM pharmacy_stockmove WHERE id = %s", [move.pk], "APPEND_ONLY")


def test_balance_cannot_be_written_directly() -> None:
    batch, store = b.batch(), b.store()
    b.stock_move(batch, store, "10")
    balance = StockBalance.objects.get(batch=batch, store=store)
    b.db_rejects(
        lambda: StockBalance.objects.filter(pk=balance.pk).update(qty_base=Decimal("999")),
        "STOCK_BALANCE_DERIVED",
    )
    b.sql_rejects(
        "DELETE FROM pharmacy_stockbalance WHERE id = %s", [balance.pk], "STOCK_BALANCE_DERIVED"
    )
    b.db_rejects(
        lambda: StockBalance.objects.create(
            item=batch.item,
            batch=batch,
            store=b.store(),
            qty_base=Decimal("5"),
            updated_at=timezone.now(),
        ),
        "STOCK_BALANCE_DERIVED",
    )


def test_move_must_match_batch_item() -> None:
    batch, store = b.batch(), b.store()
    other = b.item()
    b.db_rejects(
        lambda: StockMove.objects.create(
            item=other,
            batch=batch,
            store=store,
            qty_base=Decimal("1"),
            kind="receipt",
            source_type="test",
            unit_cost=Decimal("0"),
            created_by=b.user(),
        ),
        "STOCK_ITEM_MISMATCH",
    )


@pytest.mark.parametrize(
    ("kind", "qty"),
    [
        ("receipt", "-1"),
        ("transfer_in", "-1"),
        ("dispense", "1"),
        ("transfer_out", "1"),
        ("adjustment", "0"),
    ],
)
def test_move_sign_matches_kind(kind: str, qty: str) -> None:
    batch, store = b.batch(), b.store()
    b.stock_move(batch, store, "100")
    with (
        pytest.raises(IntegrityError, match="pharmacy_move_sign_matches_kind"),
        transaction.atomic(),
    ):
        b.stock_move(batch, store, qty, kind)


# --- Dispense (append-only) -----------------------------------------------------------------


def test_dispense_is_append_only() -> None:
    batch, store = b.batch(), b.store()
    b.stock_move(batch, store, "20")
    move = b.stock_move(batch, store, "-10", "dispense")
    visit = b.visit()
    line = b.service_line(visit, batch.item.service)
    dispense = Dispense.objects.create(
        number="DSP-1", visit=visit, store=store, dispensed_by=b.user()
    )
    d_line = DispenseLine.objects.create(
        dispense=dispense,
        service_line=line,
        item=batch.item,
        batch=batch,
        quantity_units=Decimal("10"),
        qty_base=Decimal("10"),
        stock_move=move,
    )
    b.db_rejects(
        lambda: DispenseLine.objects.filter(pk=d_line.pk).update(qty_base=Decimal("1")),
        "APPEND_ONLY",
    )
    b.sql_rejects("DELETE FROM pharmacy_dispense WHERE id = %s", [dispense.pk], "APPEND_ONLY")
    with (
        pytest.raises(IntegrityError, match="pharmacy_dispenseline_override_reason"),
        transaction.atomic(),
    ):
        DispenseLine.objects.create(
            dispense=dispense,
            service_line=line,
            item=batch.item,
            batch=batch,
            quantity_units=Decimal("1"),
            qty_base=Decimal("1"),
            batch_override=True,
            stock_move=b.stock_move(batch, store, "-1", "dispense"),
        )


# --- Documents freeze once final ------------------------------------------------------------


def test_posted_receipt_and_its_lines_are_frozen() -> None:
    supplier = Supplier.objects.create(code="SUP1", name_ar="مورد", name_en="Supplier")
    store = b.store()
    it = b.item()
    receipt = GoodsReceipt.objects.create(
        number="GRN-1",
        supplier=supplier,
        store=store,
        supplier_invoice_no="F-1",
        created_by=b.user(),
    )
    line = GoodsReceiptLine.objects.create(
        receipt=receipt,
        item=it,
        batch_no="L1",
        expiry_date=timezone.localdate().replace(year=2029),
        quantity_units=Decimal("1"),
        qty_base=Decimal("100"),
        unit_cost=Decimal("1.5"),
        line_total=Decimal("150.00"),
    )
    GoodsReceipt.objects.filter(pk=receipt.pk).update(
        status="posted", posted_by=b.user(), posted_at=timezone.now()
    )
    b.sql_rejects(
        "UPDATE pharmacy_goodsreceipt SET total_cost = 1 WHERE id = %s",
        [receipt.pk],
        "DOCUMENT_FINAL",
    )
    b.db_rejects(lambda: GoodsReceipt.objects.filter(pk=receipt.pk).delete(), "DOCUMENT_FINAL")
    b.sql_rejects(
        "UPDATE pharmacy_goodsreceiptline SET qty_base = 1 WHERE id = %s",
        [line.pk],
        "DOCUMENT_FINAL",
    )
    b.db_rejects(
        lambda: GoodsReceiptLine.objects.create(
            receipt=receipt,
            item=it,
            batch_no="L2",
            expiry_date=timezone.localdate().replace(year=2029),
            quantity_units=Decimal("1"),
            qty_base=Decimal("1"),
            unit_cost=Decimal("1"),
            line_total=Decimal("1"),
        ),
        "DOCUMENT_FINAL",
    )
    # The same supplier invoice cannot be received twice.
    with (
        pytest.raises(IntegrityError, match="pharmacy_receipt_supplier_invoice_once"),
        transaction.atomic(),
    ):
        GoodsReceipt.objects.create(
            number="GRN-2",
            supplier=supplier,
            store=store,
            supplier_invoice_no="F-1",
            created_by=b.user(),
        )


def test_approved_adjustment_is_frozen() -> None:
    batch, store = b.batch(), b.store()
    adj = StockAdjustment.objects.create(
        number="ADJ-1", store=store, reason_code=b.reason("stock_adjust"), requested_by=b.user()
    )
    line = StockAdjustmentLine.objects.create(
        adjustment=adj, item=batch.item, batch=batch, qty_base=Decimal("-2")
    )
    b.db_rejects(
        lambda: StockAdjustment.objects.filter(pk=adj.pk).update(status="approved"),
        "pharmacy_adjustment_decision_documented",
    )
    StockAdjustment.objects.filter(pk=adj.pk).update(
        status="approved", decided_by=b.user(), decided_at=timezone.now()
    )
    b.sql_rejects(
        "UPDATE pharmacy_stockadjustment SET status = 'draft' WHERE id = %s",
        [adj.pk],
        "DOCUMENT_FINAL",
    )
    b.sql_rejects(
        "UPDATE pharmacy_stockadjustmentline SET qty_base = 5 WHERE id = %s",
        [line.pk],
        "DOCUMENT_FINAL",
    )


def test_one_open_count_per_store_and_transfer_between_distinct_stores() -> None:
    store = b.store()
    StockCount.objects.create(number="CNT-1", store=store, started_by=b.user())
    with (
        pytest.raises(IntegrityError, match="pharmacy_count_one_open_per_store"),
        transaction.atomic(),
    ):
        StockCount.objects.create(number="CNT-2", store=store, started_by=b.user())
    with (
        pytest.raises(IntegrityError, match="pharmacy_transfer_distinct_stores"),
        transaction.atomic(),
    ):
        StockTransfer.objects.create(
            number="TR-1", from_store=store, to_store=store, created_by=b.user()
        )


def test_unit_conversion_and_barcode() -> None:
    it = b.item(barcode="6001234")
    UnitConversion.objects.create(
        item=it, unit_code="box", name_ar="علبة", name_en="Box", factor=100
    )
    with pytest.raises(IntegrityError, match="pharmacy_unit_factor_positive"), transaction.atomic():
        UnitConversion.objects.create(
            item=it, unit_code="strip", name_ar="شريط", name_en="Strip", factor=0
        )
    with pytest.raises(IntegrityError, match="pharmacy_item_barcode_unique"), transaction.atomic():
        b.item(barcode="6001234")
    b.item(barcode="")
    b.item(barcode="")  # empty barcodes do not collide
