from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

from apps.core import permissions as perm_module
from apps.core.models import Role, RolePermission
from apps.core.permissions import (
    PERMISSIONS,
    effective_permissions,
    get_permission,
    is_registered,
    register_permission,
)
from apps.core.roles import ROLE_CODES

CORE_CODES = {
    "core.manage_users",
    "core.manage_roles",
    "core.manage_settings",
    "core.view_audit",
    "ops.view_status",
}


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    snapshot = dict(perm_module._REGISTRY)
    yield
    perm_module._REGISTRY.clear()
    perm_module._REGISTRY.update(snapshot)


def test_core_codes_are_registered() -> None:
    assert set(PERMISSIONS) >= CORE_CODES
    for code in CORE_CODES:
        definition = get_permission(code)
        assert definition.label_ar
        assert definition.label_en
        assert definition.default_roles <= ROLE_CODES
        assert definition.default_roles


def test_doctors_hold_no_core_permissions_by_default() -> None:
    core_codes = [p for code, p in PERMISSIONS.items() if code.split(".")[0] in {"core", "ops"}]
    assert core_codes
    assert all("doctor" not in p.default_roles for p in core_codes)


#: Apps whose codes move money or reveal billing (FEATURES 3.8: doctors never see prices).
BILLING_APPS = {"billing", "payments", "claims", "ledger"}
BILLING_CODES = {"catalog.view_prices", "catalog.manage_prices", "patients.view_balance"}


def test_doctors_hold_no_billing_permissions_by_default() -> None:
    billing = [
        p
        for code, p in PERMISSIONS.items()
        if code.split(".")[0] in BILLING_APPS or code in BILLING_CODES
    ]
    assert len(billing) > 20
    assert [p.code for p in billing if "doctor" in p.default_roles] == []


def test_every_app_registers_permissions_and_admin_holds_all() -> None:
    apps_with_codes = {code.split(".")[0] for code in PERMISSIONS}
    assert apps_with_codes >= {
        "core",
        "ops",
        "patients",
        "visits",
        "catalog",
        "clinical",
        "orders",
        "billing",
        "payments",
        "ledger",
        "pharmacy",
        "lab",
        "claims",
        "reports",
        "portal",
        "imports",
    }
    assert [code for code, p in PERMISSIONS.items() if "admin" not in p.default_roles] == []


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            "cashier",
            {"billing.approve_invoice", "payments.take_payment", "payments.close_shift"},
            {"payments.confirm_transfer", "payments.approve_refund", "lab.approve_results"},
        ),
        (
            "cashier_supervisor",
            {
                "payments.confirm_transfer",
                "payments.approve_refund",
                "billing.approve_credit_note",
                "billing.override_discount_limit",
                "payments.override_duplicate",
                "orders.authorize_perform_first",
            },
            {"lab.approve_results", "clinical.write_note"},
        ),
        (
            "pharmacist",
            {"pharmacy.dispense", "pharmacy.receive_goods", "pharmacy.count_stock"},
            {"billing.approve_invoice", "pharmacy.approve_adjustment"},
        ),
        ("lab_tech", {"lab.enter_results", "lab.receive_sample"}, {"lab.approve_results"}),
        ("lab_supervisor", {"lab.approve_results", "lab.amend_results"}, {"payments.view"}),
        (
            "nurse",
            {"clinical.record_vitals", "orders.perform_procedure"},
            {"billing.view", "clinical.write_note"},
        ),
        (
            "accountant",
            {"claims.manage", "payments.confirm_transfer", "reports.financial"},
            {"pharmacy.dispense"},
        ),
        (
            "manager",
            {"reports.dashboard", "payments.review_shift", "core.manage_settings"},
            {"payments.take_payment"},
        ),
        (
            "receptionist",
            {"patients.create", "visits.create", "visits.view_queue"},
            {"billing.approve_invoice", "clinical.view"},
        ),
    ],
)
def test_default_role_matrix_follows_flow(role: str, allowed: set[str], denied: set[str]) -> None:
    holds = {code for code, p in PERMISSIONS.items() if role in p.default_roles}
    assert allowed <= holds
    assert not (denied & holds)


def test_registry_is_read_only() -> None:
    with pytest.raises(TypeError):
        PERMISSIONS["x.y"] = None  # type: ignore[index]


def test_as_dict() -> None:
    assert get_permission("core.manage_users").as_dict() == {
        "code": "core.manage_users",
        "label_ar": "إدارة المستخدمين",
        "label_en": "Manage users",
        "default_roles": ["admin"],
    }


@pytest.mark.usefixtures("isolated_registry")
def test_register_and_reregister_identically() -> None:
    first = register_permission(
        "sandbox.approve_thing", label_ar="اعتماد", label_en="Approve", default_roles=["cashier"]
    )
    again = register_permission(
        "sandbox.approve_thing", label_ar="اعتماد", label_en="Approve", default_roles={"cashier"}
    )
    assert first == again
    assert is_registered("sandbox.approve_thing")


@pytest.mark.usefixtures("isolated_registry")
@pytest.mark.parametrize(
    ("code", "kwargs", "match"),
    [
        ("Billing.Approve", {}, "app.action"),
        ("billing", {}, "app.action"),
        ("billing.approve.extra", {}, "app.action"),
        ("billing.approve", {"label_ar": " "}, "labels"),
        ("billing.approve", {"default_roles": ["janitor"]}, "unknown roles"),
    ],
)
def test_register_validation(code: str, kwargs: dict[str, Any], match: str) -> None:
    params: dict[str, Any] = {"label_ar": "ع", "label_en": "e", "default_roles": ()} | kwargs
    with pytest.raises(ImproperlyConfigured, match=match):
        register_permission(code, **params)


@pytest.mark.usefixtures("isolated_registry")
def test_conflicting_registration_is_rejected() -> None:
    register_permission("lab.approve", label_ar="ع", label_en="e", default_roles=["lab_supervisor"])
    with pytest.raises(ImproperlyConfigured, match="already registered"):
        register_permission("lab.approve", label_ar="ع", label_en="e", default_roles=["lab_tech"])


def test_get_permission_unknown() -> None:
    with pytest.raises(ImproperlyConfigured):
        get_permission("nope.nothing")
    assert not is_registered("nope.nothing")


# --- effective_permissions ------------------------------------------------------------------


def test_anonymous_and_none_have_nothing() -> None:
    assert effective_permissions(None) == frozenset()
    assert effective_permissions(AnonymousUser()) == frozenset()


@pytest.mark.django_db
def test_inactive_user_has_nothing(make_user: Any) -> None:
    assert effective_permissions(make_user(roles=["admin"], is_active=False)) == frozenset()


@pytest.mark.django_db
def test_user_without_roles_has_nothing(make_user: Any) -> None:
    assert effective_permissions(make_user()) == frozenset()


@pytest.mark.django_db
def test_superuser_has_everything(make_user: Any) -> None:
    assert effective_permissions(make_user(is_superuser=True)) == frozenset(PERMISSIONS)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("admin", CORE_CODES),
        ("manager", {"core.manage_settings", "core.view_audit", "ops.view_status"}),
        ("accountant", {"core.view_audit"}),
        ("cashier", set()),
        ("doctor", set()),
    ],
)
def test_role_defaults(make_user: Any, role: str, expected: set[str]) -> None:
    assert effective_permissions(make_user(roles=[role])) & CORE_CODES == expected


@pytest.mark.django_db
def test_overrides_grant_and_revoke_per_role(make_user: Any) -> None:
    manager = Role.objects.get(code="manager")
    accountant = Role.objects.get(code="accountant")
    RolePermission.objects.create(role=manager, code="core.view_audit", allowed=False)
    RolePermission.objects.create(role=manager, code="core.manage_users", allowed=True)
    RolePermission.objects.create(role=manager, code="stale.code", allowed=True)

    only_manager = effective_permissions(make_user(roles=["manager"]))
    assert "core.view_audit" not in only_manager
    assert "core.manage_users" in only_manager
    assert "stale.code" not in only_manager

    # The accountant role still grants view_audit to a user holding both roles.
    both = effective_permissions(make_user(roles=["manager", "accountant"]))
    assert "core.view_audit" in both

    RolePermission.objects.create(role=accountant, code="core.view_audit", allowed=False)
    assert "core.view_audit" not in effective_permissions(
        make_user(roles=["manager", "accountant"])
    )


@pytest.mark.django_db
def test_effective_permissions_query_count(make_user: Any, django_assert_num_queries: Any) -> None:
    user = make_user(roles=["admin", "manager"])
    with django_assert_num_queries(2):
        effective_permissions(user)
