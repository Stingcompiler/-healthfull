"""Report tests: migration-seeded reference data, and one day of activity (``scenario``)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from apps.catalog.tests.seeding import ensure_reference_data, restore_after_flush
from apps.reports.tests.scenario import Day, build_day


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
def day(db: None) -> Day:
    return build_day()
