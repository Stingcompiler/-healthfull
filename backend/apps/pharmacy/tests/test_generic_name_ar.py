"""The item's Arabic generic name (pharmacy follow-up): set on the item master, searched, and
returned next to every stock line's Latin name so the Arabic screens can show it; the Latin
name stands in while it is empty. The item import template reads its column."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.core.tests import builders as b
from apps.imports import services as imp
from apps.imports.tests.test_item_price_import import xlsx
from apps.payments.tests import api_kit as kit
from apps.pharmacy.models import Batch, Item
from conftest import ApiClient

pytestmark = pytest.mark.django_db


def _pharmacist(make_user: Any) -> ApiClient:
    return kit.actor(make_user, "pharm_ar", "pharmacist").api


def test_the_item_master_sets_edits_and_searches_the_arabic_name(make_user: Any) -> None:
    api = _pharmacist(make_user)
    svc = b.service(kind="drug", code="DRG-CET")
    created = api.post(
        "/api/pharmacy/items",
        {
            "service_id": svc.pk,
            "generic_name": "Cetirizine",
            "generic_name_ar": "  سيتريزين ",
            "strength": "10 mg",
            "base_unit_code": "tablet",
            "base_unit_name_ar": "حبة",
            "base_unit_name_en": "tablet",
        },
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["generic_name_ar"] == "سيتريزين"
    item_id = body["id"]
    edited = api.patch(f"/api/pharmacy/items/{item_id}", {"generic_name_ar": "سيتيريزين"})
    assert edited.json()["generic_name_ar"] == "سيتيريزين"
    found = api.get("/api/pharmacy/items?q=سيتيريزين").json()
    assert [i["id"] for i in found["items"]] == [item_id]


def test_stock_lines_carry_the_arabic_name_with_a_latin_fallback(make_user: Any) -> None:
    api = _pharmacist(make_user)
    store = b.store("PHAR")
    named = b.item(generic_name="Amoxicillin", generic_name_ar="أموكسيسيلين", strength="500 mg")
    plain = b.item(generic_name="Zinc", strength="20 mg")
    soon = date.today() + timedelta(days=10)
    for it in (named, plain):
        batch = Batch.objects.create(
            item=it, batch_no=f"B{it.pk}", expiry_date=soon, unit_cost=Decimal("1.0000")
        )
        b.stock_move(batch, store, "5")
    rows = api.get(f"/api/pharmacy/reports/expiry?days=30&store_id={store.pk}").json()
    by_id = {r["item_id"]: r for r in rows}
    assert by_id[named.pk]["item_name"] == "Amoxicillin 500 mg"
    assert by_id[named.pk]["item_name_ar"] == "أموكسيسيلين 500 mg"
    assert by_id[plain.pk]["item_name_ar"] == "Zinc 20 mg"  # no Arabic name: the Latin one
    batches = api.get(f"/api/pharmacy/stores/{store.pk}/batches?q=أموكسيسيلين").json()
    assert {r["item_id"] for r in batches} == {named.pk}


def test_the_import_template_reads_the_arabic_generic_name(make_user: Any) -> None:
    admin = make_user("imp_admin", roles=["admin"])
    b.store("PHA")
    header = [
        "Service code",
        "Name (English)",
        "Kind (drug or consumable)",
        "Generic name",
        "Generic name (Arabic)",
        "Base unit code",
    ]
    content = xlsx(
        header, [["DRG-ZN", "Zinc 20 mg", "drug", "Zinc sulfate", "كبريتات الزنك", "TAB"]]
    )
    job = imp.preview("items", filename="items.xlsx", content=content, actor=admin, options={})
    imp.confirm_job(job, actor=admin)
    item = Item.objects.get(service__code="DRG-ZN")
    assert (item.generic_name, item.generic_name_ar) == ("Zinc sulfate", "كبريتات الزنك")
