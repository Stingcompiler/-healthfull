"""Pharmacy module services added with the screens (FEATURES 8.1, 8.5-8.7, 8.10).

Item master edits and barcodes, suppliers, the stock card, and the early stock checks of
adjustment requests and transfers (invariant 5: a request that would take a batch below zero
is refused when it is made, not only when it is approved or sent).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.core.tests import builders as b
from apps.pharmacy import services as ps
from apps.pharmacy.models import Batch, Item, StockAdjustment, StockTransfer, UnitConversion
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacist(make_user):
    return make_user(roles=["pharmacist"])


@pytest.fixture
def store():
    st = b.store("PHARM")
    st.allows_dispense = True
    st.save()
    return st


def _stock(it: Item, st, qty: int, expiry: date = date(2028, 1, 1)) -> Batch:
    batch = Batch.objects.create(
        item=it, batch_no=f"B{b.n()}", expiry_date=expiry, unit_cost=Decimal("2.0000")
    )
    b.stock_move(batch, st, str(qty))
    return batch


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


# --- item master ----------------------------------------------------------------------------


def test_create_item_validates_choices_levels_and_barcode(pharmacist) -> None:
    svc = b.service(kind="drug")
    for fields, code in (
        ({"form": "potion"}, "INVALID_FORM"),
        ({"storage": "attic"}, "INVALID_STORAGE"),
        ({"min_stock": -1}, "INVALID_QUANTITY"),
        ({"reorder_qty": Decimal("1.5")}, "INVALID_QUANTITY"),
    ):
        with pytest.raises(DomainError) as exc:
            ps.create_item(
                service=svc,
                generic_name="Amoxicillin",
                base_unit_code="capsule",
                base_unit_name_ar="كبسولة",
                base_unit_name_en="capsule",
                actor=pharmacist,
                **fields,
            )
        assert _code(exc) == code
    item = ps.create_item(
        service=svc,
        generic_name=" Amoxicillin ",
        base_unit_code="capsule",
        base_unit_name_ar="كبسولة",
        base_unit_name_en="capsule",
        actor=pharmacist,
        barcode="6251234567890",
        min_stock=50,
    )
    assert item.generic_name == "Amoxicillin"
    other = b.service(kind="drug")
    with pytest.raises(DomainError) as exc:
        ps.create_item(
            service=other,
            generic_name="Copy",
            base_unit_code="tablet",
            base_unit_name_ar="حبة",
            base_unit_name_en="tablet",
            actor=pharmacist,
            barcode="6251234567890",
        )
    assert _code(exc) == "BARCODE_TAKEN"


def test_update_item_changes_allowed_fields_only(pharmacist) -> None:
    item = b.item(generic_name="Ibuprofen 400")
    updated = ps.update_item(
        item,
        actor=pharmacist,
        brand_name="Brufen",
        strength="400 mg",
        min_stock=30,
        reorder_qty=200,
        storage="cool",
        barcode="111",
        active=False,
    )
    assert (updated.brand_name, updated.strength, updated.storage) == ("Brufen", "400 mg", "cool")
    assert (int(updated.min_stock), int(updated.reorder_qty), updated.active) == (30, 200, False)
    with pytest.raises(DomainError) as exc:
        ps.update_item(item, actor=pharmacist, base_unit_code="ml")
    assert _code(exc) == "FIELD_NOT_EDITABLE"
    with pytest.raises(DomainError) as exc:
        ps.update_item(item, actor=pharmacist, generic_name="  ")
    assert _code(exc) == "NAME_REQUIRED"


def test_barcodes_are_unique_across_items_and_units(pharmacist) -> None:
    first = b.item(barcode="AAA")
    second = b.item()
    unit = ps.add_unit(
        second,
        unit_code="strip",
        name_ar="شريط",
        name_en="strip",
        factor=10,
        actor=pharmacist,
        barcode="BBB",
    )
    assert unit.barcode == "BBB"
    with pytest.raises(DomainError) as exc:
        ps.update_item(second, actor=pharmacist, barcode="AAA")
    assert _code(exc) == "BARCODE_TAKEN"
    with pytest.raises(DomainError) as exc:
        ps.update_item(first, actor=pharmacist, barcode="BBB")
    assert _code(exc) == "BARCODE_TAKEN"
    with pytest.raises(DomainError) as exc:
        ps.add_unit(
            first,
            unit_code="box",
            name_ar="علبة",
            name_en="box",
            factor=20,
            actor=pharmacist,
            barcode="AAA",
        )
    assert _code(exc) == "BARCODE_TAKEN"
    # An item keeps its own barcode when saved again.
    assert ps.update_item(first, actor=pharmacist, barcode="AAA").barcode == "AAA"


def test_find_by_barcode_returns_the_item_and_the_scanned_unit(pharmacist) -> None:
    item = b.item(barcode="ITEM-1")
    UnitConversion.objects.create(
        item=item, unit_code="box", name_ar="علبة", name_en="box", factor=30, barcode="BOX-1"
    )
    assert ps.find_by_barcode("ITEM-1") == (item, None)
    found, unit = ps.find_by_barcode(" BOX-1 ") or (None, None)
    assert found == item
    assert unit is not None
    assert unit.unit_code == "box"
    assert ps.find_by_barcode("nothing") is None
    assert ps.find_by_barcode("") is None


def test_update_unit_keeps_its_factor(pharmacist) -> None:
    item = b.item()
    unit = ps.add_unit(
        item, unit_code="strip", name_ar="شريط", name_en="strip", factor=10, actor=pharmacist
    )
    changed = ps.update_unit(
        unit, actor=pharmacist, name_en="Strip of 10", barcode="S10", is_dispensable=False
    )
    assert (changed.name_en, changed.barcode, changed.is_dispensable) == (
        "Strip of 10",
        "S10",
        False,
    )
    assert int(changed.factor) == 10
    with pytest.raises(DomainError) as exc:
        ps.update_unit(unit, actor=pharmacist, factor=12)
    assert _code(exc) == "FIELD_NOT_EDITABLE"


# --- suppliers ------------------------------------------------------------------------------


def test_create_supplier_normalizes_and_refuses_duplicates(pharmacist) -> None:
    supplier = ps.create_supplier(
        code=" medi-co ", name_ar="ميدي", name_en="Medi Co", actor=pharmacist, phone="0912"
    )
    assert supplier.code == "MEDI-CO"
    with pytest.raises(DomainError) as exc:
        ps.create_supplier(code="MEDI-CO", name_ar="x", name_en="y", actor=pharmacist)
    assert _code(exc) == "SUPPLIER_EXISTS"
    with pytest.raises(DomainError) as exc:
        ps.create_supplier(code="NEW", name_ar=" ", name_en="", actor=pharmacist)
    assert _code(exc) == "NAME_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.create_supplier(code=" ", name_ar="x", name_en="y", actor=pharmacist)
    assert _code(exc) == "CODE_REQUIRED"


# --- stock card -----------------------------------------------------------------------------


def test_stock_card_lists_moves_oldest_first_with_running_balance(store, pharmacist) -> None:
    item = b.item()
    other_store = b.store()
    first = _stock(item, store, 50)
    second = _stock(item, store, 20, date(2027, 6, 1))
    _stock(item, other_store, 5)
    b.stock_move(first, store, "-8", kind="adjustment")
    rows = ps.stock_card(item, store=store)
    assert [r.move.kind for r in rows] == ["receipt", "receipt", "adjustment"]
    assert [r.balance for r in rows] == [50, 70, 62]
    assert [r.batch_balance for r in rows] == [50, 20, 42]
    assert rows[1].move.batch_id == second.pk
    every = ps.stock_card(item)
    assert [r.balance for r in every] == [50, 70, 75, 67]


# --- early stock checks ---------------------------------------------------------------------


def test_adjustment_request_refuses_taking_a_batch_below_zero(store, pharmacist) -> None:
    item = b.item()
    batch = _stock(item, store, 10)
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store, reason_code="DAMAGED", lines=[(batch.pk, -11, "")], actor=pharmacist
        )
    assert _code(exc) == "STOCK_INSUFFICIENT"
    assert exc.value.details["available"] == 10
    assert not StockAdjustment.objects.exists()
    adj = ps.request_adjustment(
        store=store, reason_code="DAMAGED", lines=[(batch.pk, -10, "")], actor=pharmacist
    )
    assert adj.lines.get().qty_base == Decimal(-10)


def test_adjustment_request_refuses_an_inactive_store(store, pharmacist) -> None:
    batch = _stock(b.item(), store, 10)
    store.active = False
    store.save()
    with pytest.raises(DomainError) as exc:
        ps.request_adjustment(
            store=store, reason_code="DAMAGED", lines=[(batch.pk, -1, "")], actor=pharmacist
        )
    assert _code(exc) == "STORE_INACTIVE"


def test_transfer_draft_refuses_more_than_on_hand(store, pharmacist) -> None:
    item = b.item()
    batch = _stock(item, store, 10)
    main = b.store("MAIN2")
    with pytest.raises(DomainError) as exc:
        ps.create_transfer(
            from_store=store, to_store=main, lines=[(batch.pk, 11)], actor=pharmacist
        )
    assert _code(exc) == "STOCK_INSUFFICIENT"
    assert not StockTransfer.objects.exists()
    transfer = ps.create_transfer(
        from_store=store, to_store=main, lines=[(batch.pk, 10)], actor=pharmacist
    )
    assert transfer.lines.get().qty_base == Decimal(10)
