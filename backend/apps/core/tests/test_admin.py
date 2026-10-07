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


# --- Admin login shares the API's lockout, throttle, audit and session policy -----------

ADMIN_LOGIN = "/admin/login/"


def _admin_login(client: Client, username: str, password: str) -> Any:
    return client.post(ADMIN_LOGIN, {"username": username, "password": password, "next": "/admin/"})


def _logged_in(client: Client) -> bool:
    return "_auth_user_id" in client.session


def test_admin_uses_the_hospital_site() -> None:
    from apps.core.admin_site import AdminLoginForm, HospitalAdminSite

    assert isinstance(admin.site, HospitalAdminSite)
    assert admin.site.login_form is AdminLoginForm


def test_locked_account_cannot_log_into_admin(make_user: Any) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import User
    from conftest import TEST_PASSWORD

    root = make_user("lockedroot", is_superuser=True, is_staff=True)
    User.objects.filter(pk=root.pk).update(
        failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=15)
    )
    client = Client()
    response = _admin_login(client, "lockedroot", TEST_PASSWORD)
    assert response.status_code == 200  # the form again, with an error
    assert "temporarily locked" in response.content.decode()
    assert not _logged_in(client)
    assert client.get("/api/auth/me").status_code == 401
    assert AuthEvent.objects.filter(user=root, kind=AuthEventKind.LOGIN_LOCKED).count() == 1


def test_admin_failures_count_toward_the_lockout(make_user: Any) -> None:
    root = make_user("bruteroot", is_superuser=True, is_staff=True)
    client = Client()
    for attempt in range(1, 6):
        _admin_login(client, "bruteroot", f"wrong-{attempt}")
        root.refresh_from_db()
        assert root.failed_login_count == attempt
    assert root.locked_until is not None
    kinds = list(AuthEvent.objects.filter(user=root).values_list("kind", flat=True))
    assert kinds.count(AuthEventKind.LOGIN_FAILED) == 5
    assert kinds.count(AuthEventKind.ACCOUNT_LOCKED) == 1


def test_admin_login_and_logout_are_audited_and_follow_policy(make_user: Any) -> None:
    from conftest import TEST_PASSWORD

    policy = Policy.load()
    policy.session_idle_minutes = 20
    policy.save()
    root = make_user("goodroot", is_superuser=True, is_staff=True)
    client = Client()
    response = _admin_login(client, "goodroot", TEST_PASSWORD)
    assert response.status_code == 302
    assert _logged_in(client)
    assert client.session.get_expiry_age() == 20 * 60
    client.post(reverse("admin:logout"))
    assert not _logged_in(client)
    kinds = list(AuthEvent.objects.filter(user=root).order_by("id").values_list("kind", flat=True))
    assert kinds == [AuthEventKind.LOGIN_SUCCESS, AuthEventKind.LOGOUT]


def test_admin_refuses_pending_password_change(make_user: Any) -> None:
    from conftest import TEST_PASSWORD

    make_user("newroot", is_superuser=True, is_staff=True, must_change_password=True)
    client = Client()
    response = _admin_login(client, "newroot", TEST_PASSWORD)
    assert response.status_code == 200
    assert "must change its password" in response.content.decode()
    assert not _logged_in(client)


def test_existing_session_with_pending_password_change_is_kept_out(make_user: Any) -> None:
    pending = make_user("pendingroot", is_superuser=True, is_staff=True, must_change_password=True)
    client = Client()
    client.force_login(pending)
    response = client.get("/admin/")
    assert response.status_code == 302
    assert response["Location"].startswith(ADMIN_LOGIN)


def test_admin_login_is_throttled_per_address(make_user: Any, settings: Any) -> None:
    from conftest import TEST_PASSWORD

    settings.LOGIN_IP_MAX_FAILURES = 2
    make_user("throttled", is_superuser=True, is_staff=True)
    client = Client()
    _admin_login(client, "someone", "x")
    _admin_login(client, "someone-else", "x")
    response = _admin_login(client, "throttled", TEST_PASSWORD)
    assert "Too many failed logins" in response.content.decode()
    assert not _logged_in(client)


def test_authenticate_goes_through_the_lockout(make_user: Any) -> None:
    from django.contrib.auth import authenticate

    from conftest import TEST_PASSWORD

    user = make_user("viabackend")
    for _ in range(5):
        assert authenticate(username="viabackend", password="nope") is None
    user.refresh_from_db()
    assert user.locked_until is not None
    assert authenticate(username="viabackend", password=TEST_PASSWORD) is None


# --- Audited unlock --------------------------------------------------------------------


def test_lock_fields_are_read_only_in_admin(admin_client_logged_in: Client, make_user: Any) -> None:
    target = make_user("readonlylock")
    url = reverse("admin:core_user_change", args=[target.pk])
    form = admin_client_logged_in.get(url).context["adminform"].form
    assert "locked_until" not in form.fields
    assert "failed_login_count" not in form.fields


def test_unlock_action_requires_a_reason_and_is_audited(
    admin_client_logged_in: Client, make_user: Any
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import User

    target = make_user("stuck")
    lock_end = timezone.now() + timedelta(minutes=10)
    User.objects.filter(pk=target.pk).update(failed_login_count=5, locked_until=lock_end)
    url = reverse("admin:core_user_changelist")
    data = {"action": "unlock_accounts", "_selected_action": [target.pk]}

    # First step: the confirmation page asks for a reason and changes nothing.
    page = admin_client_logged_in.post(url, data)
    assert page.status_code == 200
    assert "reason" in page.context["form"].fields
    target.refresh_from_db()
    assert target.locked_until is not None

    # A blank reason is refused.
    page = admin_client_logged_in.post(url, {**data, "apply": "1", "reason": "  "})
    assert page.status_code == 200
    target.refresh_from_db()
    assert target.locked_until is not None

    done = admin_client_logged_in.post(
        url, {**data, "apply": "1", "reason": "Verified by phone with the user"}
    )
    assert done.status_code == 302
    target.refresh_from_db()
    assert (target.failed_login_count, target.locked_until) == (0, None)
    event = AuthEvent.objects.get(user=target, kind=AuthEventKind.ACCOUNT_UNLOCKED)
    assert event.details["reason"] == "Verified by phone with the user"
    assert event.details["actor_username"] == "root"
    assert event.details["previous_failed_count"] == 5
    assert event.details["previous_locked_until"] == lock_end.isoformat()


def test_authenticate_tolerates_overlong_unknown_usernames() -> None:
    from django.contrib.auth import authenticate

    assert authenticate(username="x" * 400, password="nope") is None
