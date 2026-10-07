"""Audit trail: pghistory events, context, append-only protections (FEATURES 0.4)."""

from __future__ import annotations

from typing import Any

import pghistory
import pytest
from django.apps import apps
from django.db import DatabaseError, transaction

from apps.core.models import AuthEvent, AuthEventKind, Department, Policy, Role, User

pytestmark = pytest.mark.django_db

TRACKED = {
    "Role": {"insert", "update", "delete"},
    "User": {"insert", "update"},
    "UserRole": {"insert", "delete"},
    "RolePermission": {"insert", "update", "delete"},
    "CenterProfile": {"insert", "update"},
    "Policy": {"insert", "update"},
    "ReasonCode": {"insert", "update", "delete"},
    "Department": {"insert", "update", "delete"},
    "Room": {"insert", "update", "delete"},
    "DoctorProfile": {"insert", "update", "delete"},
}


def _event_model(name: str) -> Any:
    return apps.get_model("core", f"{name}Event")


def test_every_mutable_core_model_is_tracked() -> None:
    for name in TRACKED:
        assert _event_model(name) is not None


def test_department_lifecycle_is_recorded_with_context() -> None:
    DepartmentEvent = _event_model("Department")
    with pghistory.context(user=123, reason="setup", request_id="r-1"):
        dept = Department.objects.create(code="GEN", name_ar="عام", name_en="General")
        dept.name_en = "General Medicine"
        dept.save()
        dept_id = dept.pk
        dept.delete()
    events = list(DepartmentEvent.objects.filter(pgh_obj_id=dept_id).order_by("pgh_id"))
    assert [e.pgh_label for e in events] == ["insert", "update", "delete"]
    assert events[1].name_en == "General Medicine"
    assert events[0].pgh_context.metadata == {"user": 123, "reason": "setup", "request_id": "r-1"}
    assert len({e.pgh_context_id for e in events}) == 1


def test_no_op_save_creates_no_update_event() -> None:
    DepartmentEvent = _event_model("Department")
    dept = Department.objects.create(code="X", name_ar="x", name_en="x")
    dept.save()
    assert list(
        DepartmentEvent.objects.filter(pgh_obj_id=dept.pk).values_list("pgh_label", flat=True)
    ) == ["insert"]


def test_user_history_never_stores_password_hashes(make_user: Any) -> None:
    UserEvent = _event_model("User")
    field_names = {f.name for f in UserEvent._meta.get_fields()}
    assert "password" not in field_names
    assert "last_login" not in field_names
    assert "password_changed_at" in field_names

    user = make_user("hist")
    before = UserEvent.objects.filter(pgh_obj_id=user.pk).count()
    user.set_password("Another-Pass-55")
    user.save()
    events = UserEvent.objects.filter(pgh_obj_id=user.pk).order_by("pgh_id")
    assert events.count() == before + 1
    assert events.last().pgh_label == "update"


def test_login_bookkeeping_does_not_spam_user_history(make_user: Any) -> None:
    from django.utils import timezone

    UserEvent = _event_model("User")
    user = make_user("quiet")
    before = UserEvent.objects.filter(pgh_obj_id=user.pk).count()
    User.objects.filter(pk=user.pk).update(
        last_login=timezone.now(), failed_login_count=3, locked_until=timezone.now()
    )
    assert UserEvent.objects.filter(pgh_obj_id=user.pk).count() == before


def test_policy_changes_are_tracked() -> None:
    PolicyEvent = _event_model("Policy")
    policy = Policy.load()
    policy.allow_partial_payment = True
    policy.save()
    assert PolicyEvent.objects.filter(pgh_label="update").latest("pgh_id").allow_partial_payment


def test_role_assignment_is_tracked(make_user: Any) -> None:
    UserRoleEvent = _event_model("UserRole")
    user = make_user("roles", roles=["nurse"])
    user.user_roles.all().delete()
    labels = list(
        UserRoleEvent.objects.filter(user_id=user.pk)
        .order_by("pgh_id")
        .values_list("pgh_label", flat=True)
    )
    assert labels == ["insert", "delete"]


def test_history_rows_are_append_only() -> None:
    RoleEvent = _event_model("Role")
    Role.objects.filter(code="nurse").update(name_en="Registered nurse")
    event = RoleEvent.objects.filter(pgh_label="update").latest("pgh_id")
    with pytest.raises(DatabaseError, match="Cannot update or delete"), transaction.atomic():
        RoleEvent.objects.filter(pk=event.pk).update(name_en="tampered")
    with pytest.raises(DatabaseError, match="Cannot update or delete"), transaction.atomic():
        RoleEvent.objects.filter(pk=event.pk).delete()


def test_auth_events_are_append_only() -> None:
    event = AuthEvent.objects.create(kind=AuthEventKind.LOGIN_FAILED, username="x")
    with pytest.raises(DatabaseError, match="Cannot update or delete"), transaction.atomic():
        AuthEvent.objects.filter(pk=event.pk).update(username="y")
    with pytest.raises(DatabaseError, match="Cannot update or delete"), transaction.atomic():
        AuthEvent.objects.filter(pk=event.pk).delete()
    event.refresh_from_db()
    assert event.username == "x"


def test_audited_users_cannot_be_deleted(make_user: Any) -> None:
    from django.db.models import ProtectedError

    user = make_user("kept")
    AuthEvent.objects.create(kind=AuthEventKind.LOGOUT, user=user)
    with pytest.raises(ProtectedError):
        user.delete()
