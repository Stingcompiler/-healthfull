"""The banks list an administrator keeps (FEATURES 6.1, ``payments.manage_banks``).

Transfers, QR and card payments name a bank from this list; the reference is unique per bank,
so a bank is never deleted, only deactivated (its payments keep pointing at it).
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.payments import banks
from apps.payments.models import Bank
from apps.payments.tests import api_kit as kit
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


def test_the_seeded_banks_are_listed_with_inactive_ones(make_user: Any) -> None:
    Bank.objects.create(code="OLD", name_ar="قديم", name_en="Old", active=False, sort_order=99)
    codes = [b.code for b in banks.list_banks()]
    assert {"BOK", "FIB", "ONB", "OTHER", "OLD"} <= set(codes)
    assert codes[-1] == "OLD"  # sort order, then code


def test_create_checks_the_code_and_refuses_a_duplicate(make_user: Any) -> None:
    admin = make_user("bank-admin", roles=["admin"])
    bank = banks.create_bank(
        admin, code="SYB", name_ar=" بنك السودان ", name_en="Sudan Bank", sort_order=5
    )
    assert (bank.code, bank.name_ar, bank.active) == ("SYB", "بنك السودان", True)
    assert bank.sort_order == 5
    with pytest.raises(DomainError) as err:
        banks.create_bank(admin, code="syb", name_ar="x", name_en="x")
    assert err.value.code == "INVALID_CODE"
    with pytest.raises(DomainError) as err:
        banks.create_bank(admin, code="BOK", name_ar="x", name_en="x")
    assert err.value.code == "BANK_CODE_TAKEN"


def test_update_renames_reorders_and_deactivates(make_user: Any) -> None:
    admin = make_user("bank-admin2", roles=["admin"])
    bok = Bank.objects.get(code="BOK")
    changed = banks.update_bank(admin, bok.pk, name_en="Bankak", active=False, sort_order=7)
    assert (changed.name_en, changed.active, changed.sort_order) == ("Bankak", False, 7)
    assert changed.code == "BOK"
    with pytest.raises(ValueError, match="Not editable"):
        banks.update_bank(admin, bok.pk, code="NEW")


def test_api_manages_banks_and_the_desk_list_follows(make_user: Any) -> None:
    admin = kit.actor(make_user, "boss", "admin")
    accountant = kit.actor(make_user, "acct", "accountant")
    cashier = kit.actor(make_user, "till", "cashier")

    created = accountant.api.post(
        "/api/payments/banks", {"code": "MYC", "name_ar": "ماي كاش", "name_en": "MyCash"}
    )
    assert created.status_code == 201, created.content
    bank_id = created.json()["id"]
    assert created.json()["active"] is True
    assert "MYC" in [b["code"] for b in cashier.api.get("/api/payments/banks").json()]

    dup = admin.api.post("/api/payments/banks", {"code": "MYC", "name_ar": "x", "name_en": "x"})
    assert dup.status_code == 409
    assert dup.json()["code"] == "BANK_CODE_TAKEN"

    off = admin.api.patch(f"/api/payments/banks/{bank_id}", {"active": False})
    assert off.status_code == 200, off.content
    assert off.json()["active"] is False
    assert "MYC" not in [b["code"] for b in cashier.api.get("/api/payments/banks").json()]
    every = admin.api.get("/api/payments/banks/all").json()
    assert {"code": "MYC", "active": False}.items() <= next(
        b for b in every if b["code"] == "MYC"
    ).items()


def test_only_holders_of_manage_banks_may_change_the_list(make_user: Any) -> None:
    bok = Bank.objects.get(code="BOK").pk
    for role in ("cashier", "cashier_supervisor", "manager"):
        user = kit.actor(make_user, f"no-{role}", role)
        for response in (
            user.api.get("/api/payments/banks/all"),
            user.api.post("/api/payments/banks", {"code": "ZZ", "name_ar": "x", "name_en": "x"}),
            user.api.patch(f"/api/payments/banks/{bok}", {"active": False}),
        ):
            assert response.status_code == 403, (role, response.content)
            assert response.json()["details"]["permission"] == "payments.manage_banks"
