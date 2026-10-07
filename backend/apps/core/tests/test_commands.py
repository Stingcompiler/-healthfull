from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.core.management.commands.seed_e2e import DEPARTMENTS, E2E_PASSWORD, USERS
from apps.core.models import (
    CenterProfile,
    Department,
    DoctorProfile,
    Policy,
    User,
    UserRole,
)
from apps.core.permissions import effective_permissions
from conftest import ApiClient

# --- seed_e2e -------------------------------------------------------------------------------

EXPECTED_USERS = {
    "reception": "receptionist",
    "doctor": "doctor",
    "cashier": "cashier",
    "cashsup": "cashier_supervisor",
    "pharmacist": "pharmacist",
    "labtech": "lab_tech",
    "labsup": "lab_supervisor",
    "nurse": "nurse",
    "accountant": "accountant",
    "manager": "manager",
    "admin": "admin",
}


def _seed(settings: Any) -> str:
    settings.DEBUG = True
    out = StringIO()
    call_command("seed_e2e", stdout=out)
    return out.getvalue()


def _snapshot() -> dict[str, Any]:
    return {
        "users": sorted(
            User.objects.values_list(
                "username",
                "is_active",
                "is_staff",
                "is_superuser",
                "must_change_password",
                "language",
                "theme",
            )
        ),
        "roles": sorted(UserRole.objects.values_list("user__username", "role__code")),
        "departments": sorted(Department.objects.values_list("code", "name_ar", "name_en")),
        "doctor_profiles": list(
            DoctorProfile.objects.values_list("user__username", "department__code")
        ),
        "center": CenterProfile.objects.values().get(),
        "policy_count": Policy.objects.count(),
    }


@pytest.mark.django_db
def test_seed_creates_the_contract_dataset(settings: Any) -> None:
    output = _seed(settings)
    assert "11 users (11 new)" in output
    assert {u.username: u.role for u in USERS} == EXPECTED_USERS
    for username, role in EXPECTED_USERS.items():
        user = User.objects.get(username=username)
        assert user.check_password(E2E_PASSWORD)
        assert user.role_codes() == [role]
        assert user.must_change_password is False
        assert user.is_active
        assert (user.language, user.theme) == ("ar", "light")
        assert user.full_name_ar
        assert user.full_name_en
    # The admin role user is a normal user: it gets the admin role's permissions only.
    admin = User.objects.get(username="admin")
    assert not admin.is_staff
    assert not admin.is_superuser
    assert "core.manage_users" in effective_permissions(admin)
    assert not User.objects.get(username="manager").is_staff
    # Superuser is a separate break-glass account with no role.
    root = User.objects.get(username="root")
    assert root.is_superuser
    assert root.is_staff
    assert root.role_codes() == []
    assert root.check_password(E2E_PASSWORD)
    assert User.objects.filter(is_superuser=True).count() == 1
    assert {d[0] for d in DEPARTMENTS} == set(Department.objects.values_list("code", flat=True))
    assert set(Department.objects.values_list("name_en", flat=True)) == {
        "General Medicine",
        "Pediatrics",
        "Gynecology",
        "Dental",
        "Laboratory",
        "Pharmacy",
    }
    assert all(name for name in Department.objects.values_list("name_ar", flat=True))
    profile = DoctorProfile.objects.get(user__username="doctor")
    assert profile.department.code == "GEN"
    center = CenterProfile.load()
    assert center.name_ar
    assert center.name_en
    assert Policy.objects.count() == 1
    assert effective_permissions(User.objects.get(username="doctor")) == frozenset()


@pytest.mark.django_db
def test_seed_is_idempotent_and_repairs_drift(settings: Any) -> None:
    _seed(settings)
    first = _snapshot()

    # Simulate a messy previous e2e run.
    doctor = User.objects.get(username="doctor")
    doctor.set_password("Something-Else-1")
    doctor.save()
    User.objects.filter(username="cashier").update(
        failed_login_count=5,
        locked_until=timezone.now() + timedelta(minutes=10),
        must_change_password=True,
        is_active=False,
    )
    # Preferences changed by e2e specs (preferences API, switchers) are reset too.
    User.objects.filter(username="admin").update(language="en", theme="warm")
    nurse = User.objects.get(username="nurse")
    UserRole.objects.create(user=nurse, role_id=User.objects.get(username="admin").roles.get().pk)

    output = _seed(settings)
    assert "11 users (0 new)" in output
    assert _snapshot() == first
    assert User.objects.get(username="doctor").check_password(E2E_PASSWORD)
    cashier = User.objects.get(username="cashier")
    assert (cashier.failed_login_count, cashier.locked_until) == (0, None)
    assert User.objects.get(username="nurse").role_codes() == ["nurse"]


@pytest.mark.django_db
def test_seeded_users_can_log_in(settings: Any) -> None:
    _seed(settings)
    client = ApiClient()
    response = client.login("cashsup", E2E_PASSWORD)
    assert response.status_code == 200
    assert response.json()["roles"] == ["cashier_supervisor"]


@pytest.mark.django_db
def test_seed_refuses_without_debug(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.DEBUG = False
    monkeypatch.delenv("ALLOW_SEED_E2E", raising=False)
    with pytest.raises(CommandError, match="Refusing"):
        call_command("seed_e2e", stdout=StringIO())
    assert not User.objects.exists()
    monkeypatch.setenv("ALLOW_SEED_E2E", "1")
    call_command("seed_e2e", stdout=StringIO())
    assert User.objects.count() == 12


@pytest.mark.django_db
def test_seed_refuses_a_database_that_is_not_a_test_one(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db import connection

    settings.DEBUG = True
    monkeypatch.delenv("ALLOW_SEED_E2E", raising=False)
    monkeypatch.setitem(connection.settings_dict, "NAME", "hospital_dev")
    with pytest.raises(CommandError, match="hospital_dev"):
        call_command("seed_e2e", stdout=StringIO())
    assert not User.objects.exists()
    monkeypatch.setenv("ALLOW_SEED_E2E", "1")
    call_command("seed_e2e", stdout=StringIO())
    assert User.objects.filter(username="admin").exists()


@pytest.mark.django_db
def test_seed_clears_login_throttles(settings: Any) -> None:
    from apps.core.models import LoginThrottle, ThrottleScope

    LoginThrottle.objects.create(scope=ThrottleScope.IP, key="127.0.0.1", count=99)
    _seed(settings)
    assert not LoginThrottle.objects.exists()


# --- export_openapi ---------------------------------------------------------------------------


def test_export_openapi_to_stdout() -> None:
    out = StringIO()
    call_command("export_openapi", stdout=out)
    schema = json.loads(out.getvalue())
    assert schema["openapi"].startswith("3.")
    assert "/api/auth/login" in schema["paths"]


def test_export_openapi_is_deterministic_and_sorted(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "openapi.json"
    call_command("export_openapi", output=str(target), stdout=StringIO())
    first = target.read_text(encoding="utf-8")
    call_command("export_openapi", output=str(target), stdout=StringIO())
    assert target.read_text(encoding="utf-8") == first
    assert first.endswith("}\n")
    data = json.loads(first)
    assert json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n" == first
    assert list(tmp_path.joinpath("nested").iterdir()) == [target]  # no temp files left


def test_export_openapi_check_mode(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    with pytest.raises(CommandError, match="out of date"):
        call_command("export_openapi", output=str(target), check=True, stdout=StringIO())
    call_command("export_openapi", output=str(target), stdout=StringIO())
    out = StringIO()
    call_command("export_openapi", output=str(target), check=True, stdout=out)
    assert "up to date" in out.getvalue()
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CommandError, match="out of date"):
        call_command("export_openapi", output=str(target), check=True, stdout=StringIO())
    with pytest.raises(CommandError, match="requires --output"):
        call_command("export_openapi", check=True, stdout=StringIO())


def test_export_openapi_cleans_up_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "openapi.json"

    def boom(self: Path, other: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        call_command("export_openapi", output=str(target), stdout=StringIO())
    assert list(tmp_path.iterdir()) == []


# --- maintenance --------------------------------------------------------------------------


@pytest.mark.django_db
def test_maintenance_removes_expired_sessions_and_stale_throttles() -> None:
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session

    from apps.core.models import LoginThrottle, ThrottleScope

    now = timezone.now()
    live = SessionStore()
    live.create()
    Session.objects.create(session_key="old" * 10, session_data="x", expire_date=now - timedelta(1))
    old = LoginThrottle.objects.create(scope=ThrottleScope.IP, key="10.0.0.1", count=3)
    locked = LoginThrottle.objects.create(
        scope=ThrottleScope.USERNAME, key="ghost", count=5, locked_until=now + timedelta(hours=2)
    )
    fresh = LoginThrottle.objects.create(scope=ThrottleScope.IP, key="10.0.0.2", count=1)
    LoginThrottle.objects.filter(pk__in=[old.pk, locked.pk]).update(
        updated_at=now - timedelta(days=2)
    )

    out = StringIO()
    call_command("maintenance", stdout=out)
    assert "removed 1 expired session(s) and 1 stale login throttle row(s)" in out.getvalue()
    assert list(Session.objects.values_list("session_key", flat=True)) == [live.session_key]
    remaining = set(LoginThrottle.objects.values_list("key", flat=True))
    assert remaining == {"ghost", "10.0.0.2"}
    assert fresh.pk
