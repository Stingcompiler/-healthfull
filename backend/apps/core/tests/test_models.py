from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.core.models import (
    AuthEvent,
    AuthEventKind,
    CenterProfile,
    Department,
    DoctorProfile,
    Notification,
    Policy,
    ReasonCode,
    Role,
    RolePermission,
    Room,
    Sequence,
    User,
    UserRole,
)
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


# --- Singletons -------------------------------------------------------------------------


@pytest.mark.parametrize("model", [CenterProfile, Policy])
def test_singleton_exists_after_migrations_and_loads(model: Any) -> None:
    assert model.objects.count() == 1
    obj = model.load()
    assert obj.pk == 1
    assert model.load().pk == 1
    assert model.objects.count() == 1


@pytest.mark.parametrize("model", [CenterProfile, Policy])
def test_singleton_load_recreates_missing_row(model: Any) -> None:
    model.objects.all()._raw_delete(using="default")
    assert model.objects.count() == 0
    assert model.load().pk == 1


def test_singleton_save_forces_primary_key() -> None:
    profile = CenterProfile(pk=99, name_en="Other")
    profile.save()
    assert profile.pk == 1
    assert CenterProfile.objects.count() == 1
    assert CenterProfile.load().name_en == "Other"


def test_singleton_cannot_be_deleted() -> None:
    with pytest.raises(DomainError) as exc:
        Policy.load().delete()
    assert exc.value.code == "SINGLETON_NOT_DELETABLE"


def test_singleton_db_constraint_rejects_second_row() -> None:
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO core_centerprofile (id, name_ar, name_en, address, phone, "
            "logo, registration_no, tax_no, digits, updated_at) VALUES "
            "(2, '', '', '', '', '', '', '', 'latin', now())"
        )


def test_policy_defaults() -> None:
    policy = Policy.load()
    assert policy.allow_partial_payment is False
    assert policy.default_pay_first is True
    assert policy.follow_up_window_days == 7
    assert policy.follow_up_discount_percent == Decimal("100.00")
    assert policy.session_idle_minutes == 480
    assert policy.discount_limit_percent == {
        "cashier": 0,
        "cashier_supervisor": 25,
        "accountant": 25,
        "manager": 100,
    }
    assert policy.perform_first_roles == ["cashier_supervisor", "manager"]
    policy.full_clean()
    assert str(policy) == "Policy"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discount_limit_percent", []),
        ("discount_limit_percent", {"janitor": 10}),
        ("discount_limit_percent", {"cashier": 101}),
        ("discount_limit_percent", {"cashier": -1}),
        ("discount_limit_percent", {"cashier": "10"}),
        ("discount_limit_percent", {"cashier": True}),
        ("perform_first_roles", ["janitor"]),
        ("perform_first_roles", "manager"),
        ("follow_up_discount_percent", Decimal("150")),
        ("session_idle_minutes", 1),
    ],
)
def test_policy_validation(field: str, value: Any) -> None:
    policy = Policy.load()
    setattr(policy, field, value)
    with pytest.raises(ValidationError) as exc:
        policy.full_clean()
    assert field in exc.value.message_dict


def test_policy_db_constraints() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Policy.objects.filter(pk=1).update(follow_up_discount_percent=Decimal("101"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Policy.objects.filter(pk=1).update(session_idle_minutes=2)


def test_policy_discount_limit_for() -> None:
    policy = Policy.load()
    assert policy.discount_limit_for(["cashier"]) == Decimal(0)
    assert policy.discount_limit_for(["cashier", "manager"]) == Decimal(100)
    assert policy.discount_limit_for(["doctor"]) == Decimal(0)
    policy.discount_limit_percent = {"cashier": 12.5}
    assert policy.discount_limit_for(["cashier"]) == Decimal("12.5")
    policy.discount_limit_percent = "garbage"
    assert policy.discount_limit_for(["cashier"]) == Decimal(0)


def test_center_profile_defaults_and_str() -> None:
    profile = CenterProfile.load()
    assert profile.digits == "latin"
    assert str(profile) == "Center profile"
    profile.name_ar = "مركز"
    assert str(profile) == "مركز"
    profile.name_en = "Center"
    assert str(profile) == "Center"


# --- Users and roles --------------------------------------------------------------------


def test_user_defaults(make_user: Any) -> None:
    user = User.objects.create_user("plain", password="x-Strong-Pass-1")
    # Never chosen: the client follows the device until the user picks (ARCHITECTURE 5.1).
    assert user.language == ""
    assert user.theme == ""
    assert user.must_change_password is True
    assert user.failed_login_count == 0
    assert user.password_changed_at is not None
    assert str(user) == "plain"


def test_user_display_names(make_user: Any) -> None:
    user = make_user("names")
    assert (user.display_name_ar, user.display_name_en) == ("names", "names")
    user.full_name_en = "English"
    assert (user.display_name_ar, user.display_name_en) == ("English", "English")
    user.full_name_ar = "عربي"
    assert (user.display_name_ar, user.display_name_en) == ("عربي", "English")


def test_user_lock_helpers(make_user: Any) -> None:
    user = make_user("lock")
    assert not user.is_locked()
    user.locked_until = timezone.now() + timedelta(minutes=1)
    assert user.is_locked()
    assert not user.is_locked(timezone.now() + timedelta(minutes=2))


def test_user_roles_and_role_codes(make_user: Any) -> None:
    user = make_user("multi", roles=["nurse", "doctor"])
    assert user.role_codes() == ["doctor", "nurse"]
    with pytest.raises(IntegrityError), transaction.atomic():
        UserRole.objects.create(user=user, role=Role.objects.get(code="nurse"))


def test_role_is_protected_while_assigned(make_user: Any) -> None:
    from django.db.models import ProtectedError

    make_user("holder", roles=["nurse"])
    with pytest.raises(ProtectedError):
        Role.objects.get(code="nurse").delete()


def test_role_clean_rejects_unknown_codes() -> None:
    with pytest.raises(ValidationError):
        Role(code="janitor", name_ar="x", name_en="x").clean()
    Role(code="nurse", name_ar="x", name_en="x").clean()
    assert str(Role.objects.get(code="nurse")) == "Nurse"


def test_role_permission_clean_and_uniqueness() -> None:
    role = Role.objects.get(code="nurse")
    with pytest.raises(ValidationError):
        RolePermission(role=role, code="nope.nothing", allowed=True).clean()
    rp = RolePermission.objects.create(role=role, code="core.view_audit", allowed=True)
    rp.clean()
    assert str(rp).endswith("core.view_audit=allow")
    with pytest.raises(IntegrityError), transaction.atomic():
        RolePermission.objects.create(role=role, code="core.view_audit", allowed=False)


# --- Reference data -----------------------------------------------------------------------


def test_reference_models(make_user: Any) -> None:
    dept = Department.objects.create(code="GEN", name_ar="الطب العام", name_en="General")
    room = Room.objects.create(code="R1", name_ar="غرفة ١", name_en="Room 1", department=dept)
    doctor = DoctorProfile.objects.create(
        user=make_user("drx", full_name_en="X"), department=dept, specialty_en="GP"
    )
    reason = ReasonCode.objects.create(
        category="cancellation", code="PATIENT_REFUSED", label_ar="رفض المريض", label_en="Refused"
    )
    assert str(dept) == "General"
    assert str(room) == "Room 1"
    assert str(doctor) == "Dr. X"
    assert str(reason) == "cancellation/PATIENT_REFUSED"
    assert dept.rooms.get() == room
    assert dept.doctors.get() == doctor
    with pytest.raises(IntegrityError), transaction.atomic():
        ReasonCode.objects.create(
            category="cancellation", code="PATIENT_REFUSED", label_ar="x", label_en="x"
        )
    # Same code in another category is fine.
    ReasonCode.objects.create(category="refund", code="PATIENT_REFUSED", label_ar="x", label_en="x")


def test_notification(make_user: Any) -> None:
    user = make_user("notified")
    note = Notification.objects.create(user=user, kind="result_ready", payload={"visit": 1})
    assert str(note) == f"result_ready -> {user.pk}"
    assert user.notifications.filter(read_at__isnull=True).count() == 1


def test_sequence_str() -> None:
    assert str(Sequence(code="INV", year=2026, last_value=5)) == "INV-2026: 5"


def test_auth_event_str() -> None:
    event = AuthEvent.objects.create(kind=AuthEventKind.LOGOUT, username="u")
    assert str(event).startswith("logout u @ ")
