from __future__ import annotations

import pytest
from django.core.management import call_command

from api import permissions as api_permissions
from apps.core.checks import check_required_permissions_registered


def test_check_passes_for_registered_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_permissions, "REQUIRED_CODES", {"core.manage_users"})
    assert check_required_permissions_registered() == []


def test_check_reports_unregistered_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_permissions, "REQUIRED_CODES", {"core.manage_users", "x.missing"})
    (error,) = check_required_permissions_registered()
    assert error.id == "core.E001"
    assert "x.missing" in error.msg


def test_manage_py_check_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # Other tests register throwaway codes via test-only routers; start from the real set.
    monkeypatch.setattr(api_permissions, "REQUIRED_CODES", set())
    call_command("check", fail_level="WARNING")
