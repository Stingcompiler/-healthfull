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
}


def test_eleven_roles_from_architecture() -> None:
    assert ROLE_CODES == EXPECTED_CODES
    assert len(ROLES) == 11
    assert all(r.name_ar and r.name_en for r in ROLES)


def test_roles_match_migration() -> None:
    migration = importlib.import_module("apps.core.migrations.0002_seed_roles_and_singletons")
    assert [tuple(r) for r in migration.ROLES] == [(r.code, r.name_ar, r.name_en) for r in ROLES]


@pytest.mark.django_db
def test_roles_are_seeded_in_the_database() -> None:
    rows = {r.code: (r.name_ar, r.name_en) for r in Role.objects.all()}
    assert rows == {r.code: (r.name_ar, r.name_en) for r in ROLES}
