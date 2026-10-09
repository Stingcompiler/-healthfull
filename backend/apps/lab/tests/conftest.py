"""Test setup: reference data before and after every test; lab users and two tests."""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal

import pytest

from apps.catalog.tests.seeding import ensure_reference_data, restore_after_flush
from apps.core.tests import builders as b
from apps.lab.models import LabParameter, LabTest, ReferenceRange


@pytest.fixture(autouse=True)
def _reference_data(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("django_db") is not None:
        request.getfixturevalue("db")
        ensure_reference_data()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
    result = yield
    restore_after_flush(item, nextitem)
    return result


@pytest.fixture
def tech(make_user):
    return make_user(roles=["lab_tech"])


@pytest.fixture
def supervisor(make_user):
    return make_user(roles=["lab_supervisor"])


@pytest.fixture
def cbc() -> LabTest:
    test = LabTest.objects.create(
        service=b.service("lab"), code="CBC", sample_type="whole_blood", turnaround_minutes=60
    )
    hb = LabParameter.objects.create(
        test=test, code="HB", name_ar="الهيموغلوبين", name_en="Haemoglobin", unit="g/dL"
    )
    ReferenceRange.objects.create(
        parameter=hb,
        sex="male",
        age_min_days=18 * 365,
        low=Decimal(13),
        high=Decimal(17),
        critical_low=Decimal(7),
        critical_high=Decimal(20),
    )
    ReferenceRange.objects.create(
        parameter=hb, sex="female", age_min_days=18 * 365, low=Decimal(12), high=Decimal("15.5")
    )
    ReferenceRange.objects.create(
        parameter=hb,
        age_min_days=365,
        age_max_days=12 * 365,
        low=Decimal(11),
        high=Decimal("14.5"),
        critical_low=Decimal(7),
    )
    LabParameter.objects.create(
        test=test,
        code="BG",
        name_ar="فصيلة الدم",
        name_en="Blood group",
        value_type="choice",
        choices=["A", "B", "AB", "O"],
        sort_order=2,
    )
    return test


@pytest.fixture
def malaria() -> LabTest:
    test = LabTest.objects.create(service=b.service("lab"), code="BFFM", sample_type="whole_blood")
    LabParameter.objects.create(
        test=test,
        code="MP",
        name_ar="طفيل الملاريا",
        name_en="Malaria parasite",
        value_type="pos_neg",
    )
    return test
