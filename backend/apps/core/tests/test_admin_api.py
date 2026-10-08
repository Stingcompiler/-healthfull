"""``/api/core`` administration: users, roles, matrix, center, policy, departments, doctors,
reason codes, numbering and print templates (FEATURES 0.2, 0.3, 13.1-13.7).

Each endpoint: happy path, permission denied, and its domain error codes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.core.models import (
    AuthEvent,
    AuthEventKind,
    CenterProfile,
    DoctorProfile,
    Policy,
    ReasonCode,
    RolePermission,
    User,
)
from apps.core.permissions import effective_permissions
from conftest import TEST_PASSWORD, ApiClient

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Blue-Lantern-4821"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _put(api: ApiClient, path: str, data: Any) -> Any:
    return api.request("PUT", path, data)


def client_user_id(api: ApiClient) -> int:
    return int(api.get("/api/auth/me").json()["id"])


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


@pytest.fixture
def admin(make_user: Any) -> User:
    return make_user("boss", roles=["admin"])


@pytest.fixture
def client(api_client: ApiClient, admin: User) -> ApiClient:
    assert api_client.login("boss").status_code == 200
    return api_client


@pytest.fixture
def cashier_client(make_user: Any) -> ApiClient:
    make_user("till", roles=["cashier"])
    api = ApiClient()
    assert api.login("till").status_code == 200
    return api


# --- Users ------------------------------------------------------------------------------


def test_create_user_then_log_in_must_change_password(client: ApiClient) -> None:
    response = client.post(
        "/api/core/users",
        {
            "username": "nadia",
            "full_name_ar": "نادية",
            "full_name_en": "Nadia",
            "roles": ["cashier", "receptionist"],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["roles"] == ["cashier", "receptionist"]
    assert body["must_change_password"] is True
    assert body["locked"] is False

    fresh = ApiClient()
    login = fresh.login("nadia", NEW_PASSWORD)
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    _error(fresh.get("/api/core/reason-codes"), 403, "PASSWORD_CHANGE_REQUIRED")


def test_create_user_errors(client: ApiClient, make_user: Any) -> None:
    make_user("taken", roles=["nurse"])
    base = {"roles": ["nurse"], "password": NEW_PASSWORD}
    _error(client.post("/api/core/users", {**base, "username": "TAKEN"}), 409, "USERNAME_TAKEN")
    weak = client.post("/api/core/users", {**base, "username": "weak", "password": "123456"})
    body = _error(weak, 409, "PASSWORD_INVALID")
    assert body["details"]["messages"]
    _error(
        client.post("/api/core/users", {**base, "username": "x", "roles": []}),
        422,
        "VALIDATION_ERROR",
    )


def test_users_endpoints_need_manage_users(cashier_client: ApiClient, admin: User) -> None:
    body = _error(cashier_client.get("/api/core/users"), 403, "PERMISSION_DENIED")
    assert body["details"]["permission"] == "core.manage_users"
    _error(
        cashier_client.post(f"/api/core/users/{admin.pk}/unlock", {"reason": "x"}),
        403,
        "PERMISSION_DENIED",
    )


def test_list_users_filters(client: ApiClient, make_user: Any) -> None:
    make_user("ward1", roles=["nurse"], full_name_en="Amna Nurse")
    make_user("gone", roles=["nurse"], is_active=False)
    page = client.get("/api/core/users?role=nurse&active=true").json()
    assert [u["username"] for u in page["items"]] == ["ward1"]
    page = client.get("/api/core/users?q=amna").json()
    assert page["count"] == 1
    assert page["items"][0]["username"] == "ward1"


def test_update_user_roles_and_last_admin(client: ApiClient, admin: User, make_user: Any) -> None:
    nurse = make_user("n1", roles=["nurse"])
    response = client.patch(f"/api/core/users/{nurse.pk}", {"roles": ["nurse", "doctor"]})
    assert response.status_code == 200
    assert response.json()["roles"] == ["doctor", "nurse"]

    _error(client.patch(f"/api/core/users/{admin.pk}", {"roles": ["manager"]}), 409, "LAST_ADMIN")
    _error(
        client.patch(f"/api/core/users/{admin.pk}", {"is_active": False}),
        409,
        "CANNOT_DEACTIVATE_SELF",
    )
    make_user("second", roles=["admin"])
    assert (
        client.patch(f"/api/core/users/{admin.pk}", {"roles": ["admin", "manager"]}).status_code
        == 200
    )


def test_superuser_is_protected(client: ApiClient) -> None:
    root = User.objects.create_superuser("rootx", password=TEST_PASSWORD)
    _error(
        client.post(f"/api/core/users/{root.pk}/reset-password", {"new_password": NEW_PASSWORD}),
        409,
        "SUPERUSER_PROTECTED",
    )


def test_reset_password_forces_change_and_ends_sessions(client: ApiClient, make_user: Any) -> None:
    nurse = make_user("n2", roles=["nurse"])
    other = ApiClient()
    assert other.login("n2").status_code == 200
    response = client.post(
        f"/api/core/users/{nurse.pk}/reset-password", {"new_password": NEW_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert other.get("/api/auth/me").status_code == 401
    assert AuthEvent.objects.filter(user=nurse, kind=AuthEventKind.PASSWORD_RESET).exists()
    assert ApiClient().login("n2", NEW_PASSWORD).status_code == 200


def test_unlock_with_reason(client: ApiClient, make_user: Any) -> None:
    locked = make_user(
        "n3",
        roles=["nurse"],
        failed_login_count=5,
        locked_until=timezone.now() + timedelta(minutes=10),
    )
    assert client.get(f"/api/core/users/{locked.pk}").json()["locked"] is True
    _error(
        client.post(f"/api/core/users/{locked.pk}/unlock", {"reason": "  "}), 409, "REASON_REQUIRED"
    )
    response = client.post(f"/api/core/users/{locked.pk}/unlock", {"reason": "Called the desk"})
    assert response.status_code == 200
    assert response.json()["locked"] is False
    event = AuthEvent.objects.get(user=locked, kind=AuthEventKind.ACCOUNT_UNLOCKED)
    assert event.details["reason"] == "Called the desk"
    _error(
        client.post(f"/api/core/users/{locked.pk}/unlock", {"reason": "again"}),
        409,
        "USER_NOT_LOCKED",
    )


# --- Roles and the permission matrix ------------------------------------------------------


def test_roles_list_counts_active_users(client: ApiClient) -> None:
    rows = {r["code"]: r for r in client.get("/api/core/roles").json()}
    assert len(rows) == 11
    assert rows["admin"]["user_count"] >= 1


def test_matrix_toggle_changes_effective_permissions(client: ApiClient, make_user: Any) -> None:
    reception = make_user("desk", roles=["receptionist"])
    matrix = client.get("/api/core/permissions/matrix").json()
    row = next(p for p in matrix["permissions"] if p["code"] == "core.manage_settings")
    assert "receptionist" not in row["granted_roles"]
    assert "core.manage_settings" not in effective_permissions(reception)

    change = {"role": "receptionist", "code": "core.manage_settings", "allowed": True}
    response = _put(
        client, "/api/core/permissions/matrix", {"changes": [change], "reason": "pilot"}
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["changed"] == [change]
    row = next(p for p in body["permissions"] if p["code"] == "core.manage_settings")
    assert "receptionist" in row["granted_roles"]
    assert row["overridden_roles"] == ["receptionist"]
    assert "core.manage_settings" in effective_permissions(reception)

    desk = ApiClient()
    assert desk.login("desk").status_code == 200
    assert desk.get("/api/core/policy").status_code == 200

    # Back to the default: the override row goes away.
    change["allowed"] = False
    _put(client, "/api/core/permissions/matrix", {"changes": [change], "reason": "pilot over"})
    assert not RolePermission.objects.filter(code="core.manage_settings").exists()
    assert desk.get("/api/core/policy").status_code == 403
    from django.apps import apps

    event_model = apps.get_model("core", "RolePermissionEvent")
    events = list(event_model.objects.order_by("pgh_id"))
    assert [e.pgh_label for e in events] == ["insert", "delete"]
    assert events[0].pgh_context.metadata["reason"] == "permission matrix: pilot"
    assert events[0].pgh_context.metadata["user"] == client_user_id(client)


def test_matrix_errors(client: ApiClient, cashier_client: ApiClient) -> None:
    def put(path: str, data: Any) -> Any:
        return _put(client, path, data)

    url = "/api/core/permissions/matrix"
    protect = {"role": "admin", "code": "core.manage_roles", "allowed": False}
    _error(put(url, {"changes": [protect], "reason": "x"}), 409, "PERMISSION_PROTECTED")
    unknown = {"role": "admin", "code": "nope.never", "allowed": True}
    _error(put(url, {"changes": [unknown], "reason": "x"}), 409, "PERMISSION_UNKNOWN")
    a = {"role": "nurse", "code": "catalog.view", "allowed": True}
    _error(
        put(url, {"changes": [a, {**a, "allowed": False}], "reason": "x"}),
        409,
        "MATRIX_CHANGE_CONFLICT",
    )
    _error(put(url, {"changes": [a], "reason": "   "}), 409, "REASON_REQUIRED")
    _error(cashier_client.get(url), 403, "PERMISSION_DENIED")


# --- Center profile, logo, policy -----------------------------------------------------------


def test_center_profile_and_logo(client: ApiClient, settings: Any, tmp_path: Any) -> None:
    settings.MEDIA_ROOT = str(tmp_path)
    data = {
        "name_ar": "مركز النيل",
        "name_en": "Nile Center",
        "address": "Khartoum",
        "phone": "0912345678",
        "registration_no": "R-1",
        "tax_no": "T-1",
        "digits": "latin",
    }
    response = _put(client, "/api/core/center", data)
    assert response.status_code == 200
    assert response.json()["name_en"] == "Nile Center"
    assert response.json()["has_logo"] is False

    from django.core.files.uploadedfile import SimpleUploadedFile

    token = client.csrftoken or client.fetch_csrf()
    upload = client.django.post(
        "/api/core/center/logo",
        {"file": SimpleUploadedFile("logo.png", PNG, content_type="image/png")},
        headers={"X-CSRFToken": token},
    )
    assert upload.status_code == 200, upload.content
    body = upload.json()
    assert body["has_logo"] is True
    assert body["logo_url"].startswith("/api/core/center/logo?v=")
    name = CenterProfile.load().logo.name
    assert name.startswith("center/logo-")
    assert name.endswith(".png")
    assert (tmp_path / name).exists()

    image = client.get("/api/core/center/logo")
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image.content == PNG

    bad = client.django.post(
        "/api/core/center/logo",
        {
            "file": SimpleUploadedFile(
                "x.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml"
            )
        },
        headers={"X-CSRFToken": token},
    )
    _error(bad, 409, "LOGO_INVALID_TYPE")

    removed = client.request("DELETE", "/api/core/center/logo")
    assert removed.status_code == 200
    assert removed.json()["has_logo"] is False
    assert client.get("/api/core/center/logo").status_code == 404


def test_center_needs_manage_settings(cashier_client: ApiClient) -> None:
    _error(cashier_client.get("/api/core/center"), 403, "PERMISSION_DENIED")
    assert cashier_client.get("/api/core/center/logo").status_code == 404


def _policy_body(**over: Any) -> dict[str, Any]:
    body = {
        "allow_partial_payment": True,
        "pending_transfer_alert_days": 5,
        "partial_dispense_remainder": "refund",
        "show_estimated_cost": False,
        "follow_up_window_days": 10,
        "follow_up_discount_percent": "50.00",
        "discount_limit_percent": {"cashier": 5, "manager": 100},
        "session_idle_minutes": 240,
        "perform_first_roles": ["manager", "cashier_supervisor", "manager"],
    }
    body.update(over)
    return body


def test_policy_update_and_validation(client: ApiClient) -> None:
    response = _put(client, "/api/core/policy", _policy_body())
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["default_pay_first"] is True
    assert body["perform_first_roles"] == ["cashier_supervisor", "manager"]
    assert Policy.load().follow_up_window_days == 10

    _error(
        _put(client, "/api/core/policy", _policy_body(session_idle_minutes=2)),
        422,
        "VALIDATION_ERROR",
    )
    _error(
        _put(client, "/api/core/policy", _policy_body(discount_limit_percent={"cashier": 150})),
        422,
        "VALIDATION_ERROR",
    )
    _error(
        _put(client, "/api/core/policy", _policy_body(perform_first_roles=["ghost"])),
        422,
        "VALIDATION_ERROR",
    )


# --- Departments, rooms, doctors and schedules ----------------------------------------------


def test_departments_rooms_doctors_schedule(client: ApiClient, make_user: Any) -> None:
    dept = client.post(
        "/api/core/departments", {"code": "ENT", "name_ar": "الأنف والأذن", "name_en": "ENT"}
    )
    assert dept.status_code == 201
    dept_id = dept.json()["id"]
    _error(
        client.post("/api/core/departments", {"code": "ENT", "name_ar": "x", "name_en": "x"}),
        409,
        "DEPARTMENT_CODE_TAKEN",
    )
    room = client.post(
        "/api/core/rooms",
        {"code": "ENT-1", "name_ar": "غرفة", "name_en": "Room 1", "department_id": dept_id},
    )
    assert room.status_code == 201
    room_id = room.json()["id"]
    assert room.json()["department_code"] == "ENT"

    user = make_user("drent", roles=["nurse"])
    _error(
        client.post("/api/core/doctors", {"user_id": user.pk, "department_id": dept_id}),
        409,
        "DOCTOR_ROLE_REQUIRED",
    )
    client.patch(f"/api/core/users/{user.pk}", {"roles": ["doctor"]})
    doctor = client.post(
        "/api/core/doctors",
        {"user_id": user.pk, "department_id": dept_id, "specialty_en": "ENT surgeon"},
    )
    assert doctor.status_code == 201, doctor.content
    doctor_id = doctor.json()["id"]

    sessions = [
        {
            "weekday": 5,
            "start_time": "08:00",
            "end_time": "12:00",
            "slot_minutes": 20,
            "room_id": room_id,
        },
        {"weekday": 5, "start_time": "12:00", "end_time": "14:00", "slot_minutes": 15},
    ]
    saved = _put(client, f"/api/core/doctors/{doctor_id}/schedule", {"sessions": sessions})
    assert saved.status_code == 200, saved.content
    schedule = saved.json()["schedule"]
    assert [(s["weekday"], s["start_time"]) for s in schedule] == [(5, "08:00:00"), (5, "12:00:00")]
    assert schedule[0]["room_code"] == "ENT-1"

    overlap = [*sessions, {"weekday": 5, "start_time": "11:00", "end_time": "13:00"}]
    body = _error(
        _put(client, f"/api/core/doctors/{doctor_id}/schedule", {"sessions": overlap}),
        409,
        "SCHEDULE_OVERLAP",
    )
    assert body["details"]["weekday"] == 5
    assert DoctorProfile.objects.get(pk=doctor_id).schedules.count() == 2

    client.patch(f"/api/core/rooms/{room_id}", {"active": False})
    _error(
        _put(client, f"/api/core/doctors/{doctor_id}/schedule", {"sessions": sessions[:1]}),
        409,
        "ROOM_INACTIVE",
    )
    listed = client.get(f"/api/core/doctors?department_id={dept_id}").json()
    assert [d["username"] for d in listed] == ["drent"]
    depts = {d["code"]: d for d in client.get("/api/core/departments").json()}
    assert depts["ENT"]["room_count"] == 1
    assert depts["ENT"]["doctor_count"] == 1


def test_department_writes_need_permission(cashier_client: ApiClient) -> None:
    assert cashier_client.get("/api/core/departments").status_code == 200
    _error(
        cashier_client.post("/api/core/departments", {"code": "X", "name_ar": "x", "name_en": "x"}),
        403,
        "PERMISSION_DENIED",
    )
    _error(cashier_client.get("/api/core/doctors"), 403, "PERMISSION_DENIED")


# --- Reason codes ---------------------------------------------------------------------------


def test_reason_codes_crud(client: ApiClient, cashier_client: ApiClient) -> None:
    rows = cashier_client.get("/api/core/reason-codes?category=variance&active=true").json()
    assert rows
    assert all(r["category"] == "variance" for r in rows)

    created = client.post(
        "/api/core/reason-codes",
        {
            "category": "variance",
            "code": "TILL_JAM",
            "label_ar": "تعطل الدرج",
            "label_en": "Till jam",
        },
    )
    assert created.status_code == 201
    _error(
        client.post(
            "/api/core/reason-codes",
            {"category": "variance", "code": "TILL_JAM", "label_ar": "x", "label_en": "x"},
        ),
        409,
        "REASON_CODE_TAKEN",
    )
    reason_id = created.json()["id"]
    edited = client.patch(f"/api/core/reason-codes/{reason_id}", {"requires_note": True})
    assert edited.json()["requires_note"] is True

    _error(
        cashier_client.post(
            "/api/core/reason-codes",
            {"category": "variance", "code": "NOPE", "label_ar": "x", "label_en": "x"},
        ),
        403,
        "PERMISSION_DENIED",
    )


def test_last_active_reason_of_a_category_stays(client: ApiClient) -> None:
    active = list(ReasonCode.objects.filter(category="sample_reject", active=True).order_by("pk"))
    assert active
    for extra in active[1:]:
        assert (
            client.patch(f"/api/core/reason-codes/{extra.pk}", {"active": False}).status_code == 200
        )
    _error(
        client.patch(f"/api/core/reason-codes/{active[0].pk}", {"active": False}),
        409,
        "REASON_CATEGORY_EMPTY",
    )


# --- Numbering and print templates ----------------------------------------------------------


def test_sequences_view(client: ApiClient) -> None:
    from django.db import transaction

    from apps.core import services

    with transaction.atomic():
        services.next_number("INV")
    body = client.get("/api/core/sequences").json()
    year = timezone.localdate().year
    assert body["year"] == year
    inv = next(i for i in body["items"] if i["code"] == "INV")
    assert inv["last_value"] >= 1
    assert inv["next_number"].startswith(f"INV-{year}-")
    pt = next(i for i in body["items"] if i["code"] == "PT")
    assert pt["next_number"]


def test_print_templates(client: ApiClient, cashier_client: ApiClient) -> None:
    rows = client.get("/api/core/print-templates").json()
    assert len(rows) == 12
    assert all(not r["saved"] for r in rows)
    saved = _put(
        client,
        "/api/core/print-templates/invoice/a4",
        {"show_logo": False, "footer_ar": "شكراً", "footer_en": "Thank you"},
    )
    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert saved.json()["footer_en"] == "Thank you"
    assert _put(client, "/api/core/print-templates/nope/a4", {}).status_code == 422
    _error(cashier_client.get("/api/core/print-templates"), 403, "PERMISSION_DENIED")
