"""Test setup: migration-seeded reference data is present before and after every test."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from apps.catalog.models import PriceList, PriceListVersion
from apps.catalog.tests.seeding import ensure_reference_data, restore_after_flush
from apps.core.tests import builders as b


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
def cashier(make_user: Any) -> Any:
    return make_user(roles=["cashier"])


@pytest.fixture
def accountant(make_user: Any) -> Any:
    return make_user(roles=["accountant"])


@pytest.fixture
def price_version() -> PriceListVersion:
    """The default cash list's reference version (the one the seeded catalog prices from)."""
    plist = PriceList.objects.filter(is_default=True).first()
    if plist is None:
        return b.price_version()
    return PriceListVersion.objects.get_or_create(
        price_list=plist, effective_from=b.REFERENCE_VERSION_DATE
    )[0]
