"""The seed restore after transactional tests never writes outside the test database.

Review: when the last test of a session was transactional, the restore ran after
pytest-django had destroyed the test database and switched the connection to the runtime
database, and seeded (or failed on) that database.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection
from pytest_django.plugin import blocking_manager_key

from apps.catalog.tests import seeding


class _Item:
    def __init__(self) -> None:
        blocker = SimpleNamespace(unblock=contextlib.nullcontext)
        self.config = SimpleNamespace(stash={blocking_manager_key: blocker})

    def get_closest_marker(self, name: str) -> Any:
        return SimpleNamespace(kwargs={"transaction": True}) if name == "django_db" else None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []
    monkeypatch.setattr(seeding, "restore_reference_data", lambda: seen.append(1))
    return seen


def test_no_restore_after_the_last_test(calls: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(connection.settings_dict, "NAME", "test_hospital_x")
    seeding.restore_after_flush(_Item(), None)  # type: ignore[arg-type]
    assert calls == []


def test_no_restore_outside_a_test_database(
    calls: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(connection.settings_dict, "NAME", "hospital_dev")
    seeding.restore_after_flush(_Item(), _Item())  # type: ignore[arg-type]
    assert calls == []


def test_restore_between_tests_on_the_test_database(
    calls: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(connection.settings_dict, "NAME", "test_hospital_x")
    seeding.restore_after_flush(_Item(), _Item())  # type: ignore[arg-type]
    assert calls == [1]
