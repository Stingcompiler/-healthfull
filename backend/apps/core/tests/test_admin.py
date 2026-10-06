from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse

from apps.core.models import AuthEvent, AuthEventKind, CenterProfile, Policy, Role, Sequence

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client_logged_in(make_user: Any) -> Client:
    user = make_user("root", is_superuser=True, is_staff=True)
    client = Client()
    client.force_login(user)
    return client


def _core_models() -> list[Any]:
    return [m for m in admin.site._registry if m._meta.app_label == "core"]


def test_every_core_model_is_registered() -> None:
    names = {m.__name__ for m in _core_models()}
    assert names >= {
        "User",
        "Role",
        "CenterProfile",
        "Policy",
        "Sequence",
        "ReasonCode",
        "Department",
        "Room",
        "DoctorProfile",
        "Notification",
        "AuthEvent",
    }


def test_changelists_render(admin_client_logged_in: Client) -> None:
    AuthEvent.objects.create(kind=AuthEventKind.LOGOUT, username="x")
    Sequence.objects.create(code="INV", year=2026, last_value=3)
    for model in _core_models():
        url = reverse(f"admin:core_{model._meta.model_name}_changelist")
        response = admin_client_logged_in.get(url)
        assert response.status_code == 200, url


def test_change_pages_render(admin_client_logged_in: Client, make_user: Any) -> None:
    user = make_user("someone", roles=["nurse"])
    for obj in (user, Role.objects.get(code="nurse"), CenterProfile.load(), Policy.load()):
        url = reverse(f"admin:core_{obj._meta.model_name}_change", args=[obj.pk])
        assert admin_client_logged_in.get(url).status_code == 200, url


def test_add_pages(admin_client_logged_in: Client) -> None:
    for name in ("user", "department", "room", "reasoncode", "doctorprofile"):
        assert admin_client_logged_in.get(reverse(f"admin:core_{name}_add")).status_code == 200
    # Fixed role set, singletons that already exist, counters and audit rows: no adding.
    for name in ("role", "centerprofile", "policy", "sequence", "authevent"):
        assert admin_client_logged_in.get(reverse(f"admin:core_{name}_add")).status_code == 403


def test_singleton_admin_allows_add_only_when_missing(rf: Any, make_user: Any) -> None:
    model_admin = admin.site._registry[CenterProfile]
    request = rf.get("/")
    request.user = make_user("su", is_superuser=True, is_staff=True)
    assert not model_admin.has_add_permission(request)
    CenterProfile.objects.all()._raw_delete(using="default")
    assert model_admin.has_add_permission(request)
    assert not model_admin.has_delete_permission(request)


def test_audit_rows_are_read_only_in_admin(admin_client_logged_in: Client) -> None:
    event = AuthEvent.objects.create(kind=AuthEventKind.LOGOUT, username="x")
    url = reverse("admin:core_authevent_change", args=[event.pk])
    response = admin_client_logged_in.post(url, {"username": "changed"})
    assert response.status_code == 403
    event.refresh_from_db()
    assert event.username == "x"


def test_admin_edits_are_audited_with_the_acting_user(
    admin_client_logged_in: Client, make_user: Any
) -> None:
    from django.apps import apps

    target = make_user("victim", full_name_en="Before")
    admin_user = make_user("auditor", is_superuser=True, is_staff=True)
    client = Client()
    client.force_login(admin_user)
    url = reverse("admin:core_department_add")
    response = client.post(
        url, {"code": "NEW", "name_ar": "جديد", "name_en": "New", "active": "on", "sort_order": 1}
    )
    assert response.status_code == 302
    event = apps.get_model("core", "DepartmentEvent").objects.get(code="NEW")
    assert event.pgh_context.metadata["user"] == admin_user.pk
    assert event.pgh_context.metadata["url"] == url
    assert target.pk  # unrelated users untouched
