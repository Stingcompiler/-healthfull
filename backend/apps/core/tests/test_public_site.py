"""``/api/core/public-site``: the public site switches and the online booking rules (ADR 0028,
0029), and the migration that seeds them and carries the center page grant over."""

from __future__ import annotations

import importlib
from typing import Any

import pghistory.models
import pytest
from django.apps import apps as django_apps

from apps.core.models import PublicSiteSettings, Role, RolePermission, User
from apps.core.permissions import effective_permissions
from apps.core.tests import builders as b
from conftest import ApiClient
from domain.public_site import RULE_DEFAULTS

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.core.migrations.0020_public_site_seed")


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.content
    assert response.json()["code"] == code, response.json()


@pytest.fixture
def admin(make_user: Any) -> User:
    return make_user("siteboss", roles=["admin"])


@pytest.fixture
def client(api_client: ApiClient, admin: User) -> ApiClient:
    assert api_client.login("siteboss").status_code == 200
    return api_client


def test_a_new_install_has_every_switch_off(client: ApiClient) -> None:
    body = client.get("/api/core/public-site").json()
    assert body["site_enabled"] is False
    assert body["online_booking_enabled"] is False
    assert body["patient_tracking_enabled"] is False
    assert body["require_approval"] is True
    for name, value in RULE_DEFAULTS.items():
        assert body[name] == value, name


def test_save_keeps_omitted_fields_and_records_the_reason(client: ApiClient, admin: User) -> None:
    response = client.request(
        "PUT",
        "/api/core/public-site",
        {"reason": "  going live  ", "site_enabled": True, "lead_minutes": 120},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["site_enabled"], body["lead_minutes"]) == (True, 120)
    assert body["online_booking_enabled"] is False
    assert body["horizon_days"] == RULE_DEFAULTS["horizon_days"]
    event = (
        pghistory.models.Events.objects.references(PublicSiteSettings.load())
        .order_by("-pgh_created_at")
        .first()
    )
    assert event is not None
    assert event.pgh_context["user"] == admin.pk
    assert event.pgh_context["reason"] == "public site: going live"


def test_a_reason_is_required(client: ApiClient) -> None:
    _error(
        client.request("PUT", "/api/core/public-site", {"reason": "  ", "site_enabled": True}),
        409,
        "REASON_REQUIRED",
    )
    assert PublicSiteSettings.load().site_enabled is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("horizon_days", 0), ("max_open", 21), ("pow_difficulty_bits", 27), ("lead_minutes", -1)],
)
def test_values_out_of_range_are_refused_with_the_field(
    client: ApiClient, field: str, value: int
) -> None:
    response = client.request("PUT", "/api/core/public-site", {"reason": "x", field: value})
    assert response.status_code == 422, response.content
    assert field in response.content.decode()
    assert getattr(PublicSiteSettings.load(), field) == RULE_DEFAULTS[field]


@pytest.mark.parametrize(("role", "allowed"), [("admin", True), ("manager", True)])
def test_default_roles(make_user: Any, role: str, allowed: bool) -> None:
    make_user(f"ps-{role}", roles=[role])
    api = ApiClient()
    assert api.login(f"ps-{role}").status_code == 200
    assert (api.get("/api/core/public-site").status_code == 200) is allowed


@pytest.mark.parametrize("role", ["receptionist", "cashier", "doctor", "accountant"])
def test_other_roles_are_refused(make_user: Any, role: str) -> None:
    make_user(f"ps-{role}", roles=[role])
    api = ApiClient()
    assert api.login(f"ps-{role}").status_code == 200
    _error(api.get("/api/core/public-site"), 403, "PERMISSION_DENIED")
    _error(
        api.request("PUT", "/api/core/public-site", {"reason": "x", "site_enabled": True}),
        403,
        "PERMISSION_DENIED",
    )


# --- the seeding migration (ADR 0029 K1) ---------------------------------------------------


def _reseed() -> PublicSiteSettings:
    PublicSiteSettings.objects.all()._raw_delete(PublicSiteSettings.objects.db)
    seed.seed_settings(django_apps, None)
    return PublicSiteSettings.objects.get(pk=1)


def test_seed_on_a_new_install_turns_everything_off_and_approval_on() -> None:
    row = _reseed()
    assert (row.site_enabled, row.online_booking_enabled, row.patient_tracking_enabled) == (
        False,
        False,
        False,
    )
    assert row.require_approval is True


def test_seed_on_an_existing_install_keeps_portal_and_instant_booking() -> None:
    b.patient()
    row = _reseed()
    assert row.site_enabled is False
    assert (row.online_booking_enabled, row.patient_tracking_enabled) == (True, True)
    assert row.require_approval is False


def test_seed_copies_the_legacy_environment_rules(settings: Any) -> None:
    settings.PORTAL_BOOKING_LEAD_MINUTES = 45
    settings.PORTAL_MAX_OPEN_APPOINTMENTS = "4"
    row = _reseed()
    assert (row.lead_minutes, row.max_open) == (45, 4)
    assert row.horizon_days == RULE_DEFAULTS["horizon_days"]


def test_seed_leaves_an_existing_row_alone() -> None:
    PublicSiteSettings.objects.filter(pk=1).update(site_enabled=True)
    seed.seed_settings(django_apps, None)
    assert PublicSiteSettings.objects.get(pk=1).site_enabled is True


# --- the grant copy (ADR 0029 B) -------------------------------------------------------------


def _holds(role_code: str, code: str) -> bool:
    user = User.objects.create(username=f"probe-{role_code}-{code}")
    user.roles.add(Role.objects.get(code=role_code))
    return code in effective_permissions(user)


def test_grant_copy_with_no_overrides_writes_nothing() -> None:
    seed.copy_grants(django_apps, None)
    assert not RolePermission.objects.filter(code="core.manage_public_site").exists()
    assert _holds("admin", "core.manage_public_site")
    assert _holds("manager", "core.manage_public_site")
    assert not _holds("receptionist", "core.manage_public_site")


def test_grant_copy_keeps_an_extra_role_granted_the_old_code() -> None:
    receptionist = Role.objects.get(code="receptionist")
    RolePermission.objects.create(role=receptionist, code="core.manage_settings", allowed=True)
    seed.copy_grants(django_apps, None)
    seed.copy_grants(django_apps, None)  # idempotent
    assert RolePermission.objects.filter(code="core.manage_public_site").count() == 1
    assert _holds("receptionist", "core.manage_public_site")


def test_grant_copy_keeps_a_default_role_denied_the_old_code_denied() -> None:
    manager = Role.objects.get(code="manager")
    RolePermission.objects.create(role=manager, code="core.manage_settings", allowed=False)
    seed.copy_grants(django_apps, None)
    assert not _holds("manager", "core.manage_public_site")
    assert _holds("admin", "core.manage_public_site")


def test_grant_copy_drops_a_stale_row_equal_to_the_default_and_reverses() -> None:
    admin = Role.objects.get(code="admin")
    RolePermission.objects.create(role=admin, code="core.manage_public_site", allowed=False)
    seed.copy_grants(django_apps, None)
    assert not RolePermission.objects.filter(code="core.manage_public_site").exists()
    doctor = Role.objects.get(code="doctor")
    RolePermission.objects.create(role=doctor, code="core.manage_settings", allowed=True)
    seed.copy_grants(django_apps, None)
    assert RolePermission.objects.filter(code="core.manage_public_site").exists()
    seed.remove_grants(django_apps, None)
    assert not RolePermission.objects.filter(code="core.manage_public_site").exists()
