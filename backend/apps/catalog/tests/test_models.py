"""Catalog, price lists, payers and coverage rules (FEATURES 5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import (
    CoverageRule,
    Exclusion,
    PriceItem,
    PriceList,
    PriceListVersion,
    Service,
)
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db


def test_default_cash_price_list_is_seeded() -> None:
    default = PriceList.objects.filter(is_default=True).first() or b.price_version().price_list
    assert default.kind == "cash"
    assert default.active


def test_only_one_default_price_list() -> None:
    b.price_version()  # makes sure a default list exists
    with pytest.raises(IntegrityError, match="catalog_pricelist_one_default"), transaction.atomic():
        PriceList.objects.create(code="CASH2", name_ar="x", name_en="x", is_default=True)
    with (
        pytest.raises(IntegrityError, match="catalog_pricelist_default_is_active_cash"),
        transaction.atomic(),
    ):
        PriceList.objects.filter(is_default=True).update(kind="payer")


def test_versions_are_dated_and_prices_non_negative() -> None:
    version = b.price_version(effective_from=date(2026, 3, 1))
    with (
        pytest.raises(IntegrityError, match="catalog_pricelistversion_unique"),
        transaction.atomic(),
    ):
        PriceListVersion.objects.create(
            price_list=version.price_list, effective_from=date(2026, 3, 1)
        )
    svc = b.service()
    PriceItem.objects.create(version=version, service=svc, unit_price=Decimal("150.00"))
    with pytest.raises(IntegrityError, match="catalog_priceitem_unique"), transaction.atomic():
        PriceItem.objects.create(version=version, service=svc, unit_price=Decimal("1"))
    with (
        pytest.raises(IntegrityError, match="catalog_priceitem_price_non_negative"),
        transaction.atomic(),
    ):
        PriceItem.objects.create(version=version, service=b.service(), unit_price=Decimal("-1"))


def test_service_kind_and_name() -> None:
    with pytest.raises(IntegrityError, match="catalog_service_kind_valid"), transaction.atomic():
        b.service(kind="massage")
    with pytest.raises(IntegrityError, match="catalog_service_has_name"), transaction.atomic():
        Service.objects.create(code="EMPTY", name_ar="", name_en="", kind="lab")


@pytest.mark.parametrize(
    ("kwargs", "constraint"),
    [
        ({"rule_kind": "percentage"}, "catalog_coveragerule_percentage_needs_percent"),
        ({"rule_kind": "copay"}, "catalog_coveragerule_copay_needs_amount"),
        ({"rule_kind": "ceiling"}, "catalog_coveragerule_ceiling_needs_amount"),
        (
            {"rule_kind": "percentage", "payer_percent": Decimal("120")},
            "catalog_coveragerule_percent_range",
        ),
        (
            {"rule_kind": "copay", "copay_amount": Decimal("-1")},
            "catalog_coveragerule_amounts_non_negative",
        ),
        ({"rule_kind": "discount"}, "catalog_coveragerule_kind_valid"),
    ],
)
def test_coverage_rule_shape(kwargs: dict[str, object], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        CoverageRule.objects.create(payer=b.payer(), **kwargs)


def test_one_active_rule_per_scope() -> None:
    payer = b.payer()
    svc = b.service()
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=Decimal("80"))
    CoverageRule.objects.create(
        payer=payer, service_kind="lab", rule_kind="percentage", payer_percent=Decimal("90")
    )
    CoverageRule.objects.create(
        payer=payer, service=svc, rule_kind="copay", copay_amount=Decimal("500")
    )
    for kwargs, name in (
        ({}, "catalog_coveragerule_one_default"),
        ({"service_kind": "lab"}, "catalog_coveragerule_one_per_kind"),
        ({"service": svc}, "catalog_coveragerule_one_per_service"),
        ({"service": svc, "service_kind": "lab"}, "catalog_coveragerule_one_scope"),
    ):
        with pytest.raises(IntegrityError, match=name), transaction.atomic():
            CoverageRule.objects.create(
                payer=payer, rule_kind="percentage", payer_percent=Decimal("50"), **kwargs
            )
    # An inactive older rule does not block a new one.
    CoverageRule.objects.filter(payer=payer, service__isnull=True, service_kind="").update(
        active=False
    )
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=Decimal("70"))


def test_exclusion_has_exactly_one_scope() -> None:
    payer = b.payer()
    Exclusion.objects.create(payer=payer, service=b.service())
    Exclusion.objects.create(payer=payer, service_kind="consumable")
    with (
        pytest.raises(IntegrityError, match="catalog_exclusion_exactly_one_scope"),
        transaction.atomic(),
    ):
        Exclusion.objects.create(payer=payer)
    with pytest.raises(IntegrityError, match="catalog_exclusion_unique_kind"), transaction.atomic():
        Exclusion.objects.create(payer=payer, service_kind="consumable")


def test_payer_contract_dates() -> None:
    with pytest.raises(IntegrityError, match="catalog_payer_contract_dates"), transaction.atomic():
        b.payer(contract_start=date(2026, 5, 1), contract_end=date(2026, 4, 1))
