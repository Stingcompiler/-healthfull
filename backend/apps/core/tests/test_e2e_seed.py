"""The e2e base catalog that ``seed_e2e`` adds (``apps.core.e2e.catalog``)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.catalog import services as catalog_services
from apps.catalog.models import (
    CoverageRule,
    CoverageRuleKind,
    Exclusion,
    Payer,
    PriceList,
    PriceListVersion,
    Service,
    ServiceKind,
)
from apps.core.e2e import catalog
from apps.core.models import DoctorProfile, ReasonCode, Room
from apps.core.permissions import effective_permissions
from apps.core.reason_codes import REASON_CODES
from apps.lab.models import LabParameter, LabTest, RangeSex
from apps.payments.models import Bank, Till
from apps.pharmacy import services as pharmacy_services
from apps.pharmacy.models import Batch, GoodsReceipt, Item, StockBalance, StockMove, Store
from apps.visits.models import Bed, BedStatus, DoctorSchedule

pytestmark = pytest.mark.django_db


def _seed(settings: Any) -> str:
    settings.DEBUG = True
    out = StringIO()
    call_command("seed_e2e", stdout=out)
    return out.getvalue()


def _counts() -> dict[str, int]:
    return {
        "services": Service.objects.count(),
        "versions": PriceListVersion.objects.count(),
        "rules": CoverageRule.objects.count(),
        "exclusions": Exclusion.objects.count(),
        "items": Item.objects.count(),
        "batches": Batch.objects.count(),
        "receipts": GoodsReceipt.objects.count(),
        "moves": StockMove.objects.count(),
        "lab_tests": LabTest.objects.count(),
        "parameters": LabParameter.objects.count(),
        "schedules": DoctorSchedule.objects.count(),
        "beds": Bed.objects.count(),
        "rooms": Room.objects.count(),
        "tills": Till.objects.count(),
    }


def test_doctors_have_departments_schedules_and_a_consultation_fee(settings: Any) -> None:
    _seed(settings)
    profiles = {
        p.user.username: p for p in DoctorProfile.objects.select_related("user", "department")
    }
    assert set(profiles) == {"doctor", "pediatrician", "gynecologist", "dentist"}
    expected = {"doctor": "GEN", "pediatrician": "PED", "gynecologist": "GYN", "dentist": "DEN"}
    for username, dept in expected.items():
        profile = profiles[username]
        assert profile.department.code == dept
        assert profile.consultation_service is not None
        assert profile.consultation_service.kind == ServiceKind.CONSULTATION
        assert profile.consultation_service.department_id == profile.department_id
        assert profile.schedules.filter(active=True).exists()
        assert profile.specialty_ar
        assert profile.specialty_en
        # Doctors never hold billing permissions (ARCHITECTURE 4.10).
        perms = effective_permissions(profile.user)
        assert not {c for c in perms if c.split(".")[0] in {"billing", "payments"}}
    # The general practitioner works every day, so appointment specs always find a slot.
    weekdays = set(profiles["doctor"].schedules.values_list("weekday", flat=True))
    assert weekdays == set(range(7))
    assert all(s.room is not None for s in DoctorSchedule.objects.all())


def test_services_of_every_kind_with_both_names(settings: Any) -> None:
    _seed(settings)
    services = Service.objects.filter(code__in=[s.code for s in catalog.SERVICES])
    assert services.count() == len(catalog.SERVICES)
    assert set(services.values_list("kind", flat=True)) == set(ServiceKind.values)
    for service in services:
        assert service.name_ar
        assert service.name_en
        assert service.department_id is not None
        assert service.category_id is not None
        assert service.active


def test_price_lists_have_a_version_effective_today(settings: Any) -> None:
    _seed(settings)
    today = timezone.localdate()
    codes = {s.code: s.pk for s in Service.objects.all()}
    cash = PriceList.objects.get(code="CASH")
    assert cash.is_default
    cash_prices = catalog_services.version_prices(catalog_services.effective_version(cash, today))
    assert len(cash_prices) == len(catalog.SERVICES)
    assert cash_prices[codes["CONS-GEN"]] == Decimal("15000.00")
    assert cash_prices[codes["DRG-AMOX500"]] == Decimal("300.00")
    for spec in catalog.PAYERS:
        payer = Payer.objects.get(code=spec.code)
        assert payer.price_list is not None
        assert payer.price_list.code == spec.code
        version = catalog_services.effective_version(payer.price_list, today)
        assert version.effective_from == today
        prices = catalog_services.version_prices(version)
        assert prices[codes["CONS-GEN"]] == Decimal("15000.00") * Decimal(spec.price_factor)
    # A +10% version is scheduled for the first day of next month; today's prices stand.
    scheduled = PriceListVersion.objects.get(price_list=cash, effective_from__gt=today)
    assert scheduled.effective_from.day == 1
    assert today < scheduled.effective_from <= today + timedelta(days=31)
    assert scheduled.percent_change == Decimal("10.00")
    assert catalog_services.version_prices(scheduled)[codes["CONS-GEN"]] == Decimal("16500.00")


def test_three_payers_with_different_rules_and_one_exclusion(settings: Any) -> None:
    _seed(settings)
    rules = {
        (r.payer.code, r.service.code if r.service else ""): r
        for r in CoverageRule.objects.filter(active=True).select_related("payer", "service")
    }
    aman = rules[("AMAN", "")]
    assert (aman.rule_kind, aman.payer_percent) == (CoverageRuleKind.PERCENTAGE, Decimal(70))
    assert rules[("AMAN", "GYN-US")].requires_pre_approval
    nakheel = rules[("NAKHEEL", "")]
    assert (nakheel.rule_kind, nakheel.copay_amount) == (CoverageRuleKind.COPAY, Decimal(2000))
    rahma = rules[("RAHMA", "")]
    assert (rahma.rule_kind, rahma.ceiling_amount) == (CoverageRuleKind.CEILING, Decimal(10000))
    assert not Payer.objects.get(code="RAHMA").requires_card_number
    exclusion = Exclusion.objects.get(active=True)
    assert (exclusion.payer.code, exclusion.service and exclusion.service.code) == (
        "AMAN",
        "DEN-FILL",
    )
    resolved = catalog_services.resolve_coverage(
        Payer.objects.get(code="AMAN"), Service.objects.get(code="DEN-FILL")
    )
    assert resolved.excluded


def test_stock_items_units_and_two_batches_in_both_stores(settings: Any) -> None:
    _seed(settings)
    today = timezone.localdate()
    pharmacy = Store.objects.get(code="PHA")
    main = Store.objects.get(code="MAIN")
    assert pharmacy.allows_dispense
    assert not main.allows_dispense
    for spec in catalog.ITEMS:
        item = Item.objects.get(service__code=spec.service)
        factors = pharmacy_services.item_factors(item)
        assert factors[item.base_unit_code] == 1
        assert len(factors) >= 2  # a pack unit above the base unit
        batches = list(Batch.objects.filter(item=item).order_by("expiry_date"))
        assert len(batches) == 2
        assert batches[0].expiry_date < batches[1].expiry_date
        assert all(b.expiry_date > today for b in batches)
        on_pharmacy = [
            int(StockBalance.objects.get(batch=b, store=pharmacy).qty_base) for b in batches
        ]
        assert all(qty > 0 for qty in on_pharmacy)
    tablets = pharmacy_services.item_factors(Item.objects.get(service__code="DRG-PARA500"))
    assert tablets == {"tablet": 1, "strip": 10, "box": 100}
    # Expiry and low-stock reports have something to show (FEATURES 8.8, 8.9).
    soon = pharmacy_services.expiring_batches(days=30)
    assert {e.batch.item.service.code for e in soon} >= {"DRG-AMOX500", "DRG-ORS"}
    low = {entry.item.service.code for entry in pharmacy_services.low_stock()}
    assert low == {"DRG-CEFTRI1G"}
    amox = Item.objects.get(service__code="DRG-AMOX500")
    assert set(amox.drug_classes.values_list("code", flat=True)) == {"PENICILLIN"}
    assert pharmacy_services.on_hand(amox, main) == 400


def test_lab_tests_with_parameters_and_reference_ranges(settings: Any) -> None:
    _seed(settings)
    assert LabTest.objects.count() == len(catalog.LAB_TESTS)
    for test in LabTest.objects.select_related("service"):
        assert test.service.kind == ServiceKind.LAB
        params = list(test.parameters.all())
        assert params
        for param in params:
            assert param.name_ar
            assert param.name_en
            assert param.reference_ranges.exists(), param.code
    hgb = LabParameter.objects.get(test__code="CBC", code="HGB")
    assert set(hgb.reference_ranges.values_list("sex", flat=True)) == {
        RangeSex.ANY,
        RangeSex.MALE,
        RangeSex.FEMALE,
    }
    protein = LabParameter.objects.get(test__code="UA", code="PROT")
    assert protein.choices == ["nil", "trace", "1+", "2+", "3+"]


def test_wards_beds_tills_banks_and_reason_codes(settings: Any) -> None:
    _seed(settings)
    wards = Room.objects.filter(department__code="WRD")
    assert set(wards.values_list("code", flat=True)) == {"WRD-M", "WRD-F", "WRD-P"}
    beds = {b.code: b for b in Bed.objects.select_related("room", "bed_service")}
    assert len(beds) == 9
    assert all(b.bed_service.kind == ServiceKind.BED for b in beds.values())
    assert beds["F-04"].status == BedStatus.MAINTENANCE
    assert beds["P-01"].bed_service.code == "BED-PRIV"
    assert Bed.objects.filter(status=BedStatus.AVAILABLE).count() == 8
    assert set(Till.objects.values_list("code", flat=True)) >= {"T1", "T2"}
    assert Bank.objects.filter(code__in=catalog.SEEDED_BANKS, active=True).count() == 4
    for reason in REASON_CODES:
        assert ReasonCode.objects.get(category=reason.category, code=reason.code).active


def test_catalog_seed_is_idempotent(settings: Any) -> None:
    first_output = _seed(settings)
    assert "5 new versions" in first_output
    assert "2 new receipts" in first_output
    first = _counts()
    stock = sorted(StockBalance.objects.values_list("batch_id", "store_id", "qty_base"))
    output = _seed(settings)
    assert "0 new versions" in output
    assert "0 new receipts" in output
    assert _counts() == first
    assert sorted(StockBalance.objects.values_list("batch_id", "store_id", "qty_base")) == stock


def test_reseed_repairs_catalog_drift(settings: Any) -> None:
    _seed(settings)
    ReasonCode.objects.filter(category="line_cancel", code="PATIENT_REFUSED").update(active=False)
    Bank.objects.filter(code="BOK").update(active=False)
    Service.objects.filter(code="CONS-GEN").update(name_en="Renamed", active=False)
    aman = Payer.objects.get(code="AMAN")
    extra = CoverageRule.objects.create(
        payer=aman,
        service=Service.objects.get(code="LAB-CBC"),
        rule_kind=CoverageRuleKind.PERCENTAGE,
        payer_percent=Decimal(100),
    )
    _seed(settings)
    assert ReasonCode.objects.get(category="line_cancel", code="PATIENT_REFUSED").active
    assert Bank.objects.get(code="BOK").active
    service = Service.objects.get(code="CONS-GEN")
    assert (service.name_en, service.active) == ("General consultation", True)
    extra.refresh_from_db()
    assert not extra.active
