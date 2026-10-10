from __future__ import annotations

import importlib

import pytest

from apps.core.models import Role
from apps.core.roles import ROLE_CODES, ROLES

EXPECTED_CODES = {
    "receptionist",
    "doctor",
    "cashier",
    "cashier_supervisor",
    "pharmacist",
    "lab_tech",
    "lab_supervisor",
    "nurse",
    "accountant",
    "manager",
    "admin",
    # The waiting-room kiosk account (ADR 0019).
    "display",
}


def test_twelve_roles_from_architecture() -> None:
    assert ROLE_CODES == EXPECTED_CODES
    assert len(ROLES) == 12
    assert all(r.name_ar and r.name_en for r in ROLES)


def test_roles_match_migration() -> None:
    rows = [
        tuple(r)
        for name in ("0002_seed_roles_and_singletons", "0014_display_role")
        for r in importlib.import_module(f"apps.core.migrations.{name}").ROLES
    ]
    assert rows == [(r.code, r.name_ar, r.name_en) for r in ROLES]


@pytest.mark.django_db
def test_roles_are_seeded_in_the_database() -> None:
    rows = {r.code: (r.name_ar, r.name_en) for r in Role.objects.all()}
    assert rows == {r.code: (r.name_ar, r.name_en) for r in ROLES}
