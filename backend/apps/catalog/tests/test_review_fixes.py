"""Regression tests for the Phase 1 review: invariant 6 (a line's price is frozen from the
price list effective that day) against admin edits, same-day versions and inserts that would
reprice frozen invoices.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog import services as catalog
from apps.catalog.models import PriceItem, PriceListVersion
from apps.core.tests import builders as b
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _priced_invoice(price: str = "100.00"):
    cashier = fin.staff("cashier")
    svc = fin.priced("lab", price)  # cash list version effective 2020-01-01
    v = fin.visit()
    fin.order(v, fin.staff("doctor"), svc)
    inv = fin.invoice(v, cashier)
    return svc, inv


def test_admin_cannot_edit_the_prices_of_an_effective_version(client) -> None:
    """Review: a superuser changed an effective version's price in Django admin (302) while
    catalog.set_prices refused the same edit."""
    admin_user = b.user(is_staff=True, is_superuser=True)
    svc, _ = _priced_invoice()
    item = PriceItem.objects.get(service=svc)
    client.force_login(admin_user)
    resp = client.post(
        f"/admin/catalog/priceitem/{item.pk}/change/",
        {"version": item.version_id, "service": svc.pk, "unit_price": "1.00"},
    )
    assert resp.status_code == 403
    item.refresh_from_db()
    assert item.unit_price == D("100.00")
    resp = client.post(
        f"/admin/catalog/pricelistversion/{item.version_id}/change/",
        {"price_list": item.version.price_list_id, "effective_from": "2019-01-01"},
    )
    assert resp.status_code == 403


def test_db_freezes_a_version_that_priced_invoices() -> None:
    svc, _inv = _priced_invoice()
    item = PriceItem.objects.get(service=svc)
    b.db_rejects(
        lambda: PriceItem.objects.filter(pk=item.pk).update(unit_price=D("1.00")),
        "PRICE_VERSION_LOCKED",
    )
    b.sql_rejects("DELETE FROM catalog_priceitem WHERE id = %s", [item.pk], "PRICE_VERSION_LOCKED")
    b.db_rejects(
        lambda: PriceListVersion.objects.filter(pk=item.version_id).update(
            effective_from=date(2019, 1, 1)
        ),
        "PRICE_VERSION_LOCKED",
    )
    # Adding a price for a service the version did not list rewrites nothing.
    PriceItem.objects.create(version=item.version, service=b.service(), unit_price=D("5.00"))


def test_db_refuses_a_version_that_would_reprice_an_approved_day() -> None:
    _priced_invoice()
    today = timezone.localdate()
    b.db_rejects(
        lambda: PriceListVersion.objects.create(price_list=fin.cash_list(), effective_from=today),
        "PRICE_VERSION_BACKDATED",
    )
    b.db_rejects(
        lambda: PriceListVersion.objects.create(
            price_list=fin.cash_list(), effective_from=today - timedelta(days=30)
        ),
        "PRICE_VERSION_BACKDATED",
    )
    PriceListVersion.objects.create(
        price_list=fin.cash_list(), effective_from=today + timedelta(days=1)
    )


def test_no_second_version_can_start_on_a_priced_day() -> None:
    """Review: a version created at midday repriced later invoices of the same day; the
    version effective on the first invoice's day was no longer the one it froze."""
    svc, inv = _priced_invoice()
    manager = fin.staff("manager")
    today = timezone.localdate()
    with pytest.raises(DomainError) as exc:
        catalog.create_version(
            fin.cash_list(), effective_from=today, prices={svc.pk: D("150.00")}, actor=manager
        )
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    with pytest.raises(DomainError) as exc:
        catalog.derive_version(
            fin.cash_list(), effective_from=today, actor=manager, changes={svc.pk: D("150.00")}
        )
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    line = inv.lines.get()
    assert catalog.effective_version(fin.cash_list(), inv.priced_on).pk == (
        line.price_list_version_id
    )
