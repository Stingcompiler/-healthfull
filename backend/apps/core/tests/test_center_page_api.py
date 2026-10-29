"""``/api/core/center-page`` and ``/api/core/announcements``: the fixed sections of the public
center page, kept by holders of ``core.manage_public_site`` (``core.manage_settings`` until ADR
0029 B), validated and audited."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pghistory.models
import pytest
from django.utils import timezone

from apps.core.models import Announcement, CenterPage, Department, DoctorProfile, User
from conftest import ApiClient

pytestmark = pytest.mark.django_db

WEEK = [{"weekday": d, "closed": d == 4, "opens": "08:00", "closes": "16:00"} for d in range(7)]


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.content
    assert response.json()["code"] == code, response.json()


@pytest.fixture
def admin(make_user: Any) -> User:
    return make_user("pageboss", roles=["admin"])


@pytest.fixture
def client(api_client: ApiClient, admin: User) -> ApiClient:
    assert api_client.login("pageboss").status_code == 200
    return api_client


@pytest.fixture
def cashier_client(make_user: Any) -> ApiClient:
    make_user("pagetill", roles=["cashier"])
    api = ApiClient()
    assert api.login("pagetill").status_code == 200
    return api


def _body(**fields: Any) -> dict[str, Any]:
    return {
        "about_ar": "رعاية أولية",
        "about_en": "Primary care",
        "hours": WEEK,
        "whatsapp": "0912 345 678",
        "email": "info@nile.example",
        "directions_ar": "",
        "directions_en": "",
        "show_about": True,
        "show_hours": True,
        "show_departments": True,
        "show_doctors": True,
        "show_announcements": True,
        "show_contact": True,
        "show_address": True,
        "hidden_department_ids": [],
        "hidden_doctor_ids": [],
        **fields,
    }


def test_defaults_show_every_section(client: ApiClient) -> None:
    body = client.get("/api/core/center-page").json()
    assert body["hours"] == []
    assert all(body[k] for k in body if k.startswith("show_"))


def test_save_round_trip_normalizes_and_audits(client: ApiClient, admin: User) -> None:
    dept = Department.objects.create(code="CP1", name_ar="قسم", name_en="Dept")
    response = client.request(
        "PUT", "/api/core/center-page", _body(hidden_department_ids=[dept.pk, dept.pk])
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["whatsapp"] == "249912345678"
    assert body["hidden_department_ids"] == [dept.pk]
    assert body["hours"][4] == {"weekday": 4, "closed": True, "opens": None, "closes": None}
    assert body["hours"][0] == {"weekday": 0, "closed": False, "opens": "08:00", "closes": "16:00"}
    events = pghistory.models.Events.objects.references(CenterPage.load())
    assert events.exists()
    context = events.order_by("-pgh_created_at").first()
    assert context is not None
    assert context.pgh_context["user"] == admin.pk
    assert context.pgh_context["reason"] == "center page"


@pytest.mark.parametrize(
    ("fields", "status", "code"),
    [
        ({"hours": WEEK[:6]}, 409, "CENTER_HOURS_INVALID"),
        (
            {
                "hours": [
                    *WEEK[:6],
                    {"weekday": 6, "closed": False, "opens": "10:00", "closes": "09:00"},
                ]
            },
            409,
            "CENTER_HOURS_INVALID",
        ),
        ({"whatsapp": "12"}, 409, "CENTER_WHATSAPP_INVALID"),
        ({"hidden_doctor_ids": [987654]}, 409, "CENTER_PAGE_UNKNOWN_ITEM"),
        ({"email": "not-an-email"}, 422, "VALIDATION_ERROR"),
    ],
)
def test_bad_values_are_refused(
    client: ApiClient, fields: dict[str, Any], status: int, code: str
) -> None:
    _error(client.request("PUT", "/api/core/center-page", _body(**fields)), status, code)
    assert CenterPage.load().hours == []  # nothing saved


def test_hidden_doctor_must_exist(client: ApiClient, make_user: Any) -> None:
    doctor_user = make_user("drpage", roles=["doctor"])
    dept = Department.objects.create(code="CP2", name_ar="قسم", name_en="Dept")
    doctor = DoctorProfile.objects.create(user=doctor_user, department=dept)
    response = client.request("PUT", "/api/core/center-page", _body(hidden_doctor_ids=[doctor.pk]))
    assert response.status_code == 200, response.content
    assert response.json()["hidden_doctor_ids"] == [doctor.pk]


def test_announcements_crud(client: ApiClient, admin: User) -> None:
    today = timezone.localdate()
    created = client.post(
        "/api/core/announcements",
        {"title_ar": "إغلاق العيد", "body_ar": "المركز مغلق", "ends_on": str(today)},
    )
    assert created.status_code == 201, created.content
    row = created.json()
    assert row["shown_today"] is True
    assert Announcement.objects.get(pk=row["id"]).created_by == admin

    hidden = client.request("PATCH", f"/api/core/announcements/{row['id']}", {"active": False})
    assert hidden.status_code == 200
    assert hidden.json()["shown_today"] is False

    later = client.request(
        "PATCH",
        f"/api/core/announcements/{row['id']}",
        {"active": True, "starts_on": str(today + timedelta(days=2)), "ends_on": None},
    )
    assert later.status_code == 200, later.content
    assert later.json()["ends_on"] is None
    assert later.json()["shown_today"] is False

    listed = client.get("/api/core/announcements").json()
    assert [a["id"] for a in listed] == [row["id"]]
    events = pghistory.models.Events.objects.references(Announcement.objects.get(pk=row["id"]))
    assert events.count() >= 3


def test_announcement_rules(client: ApiClient) -> None:
    _error(
        client.post("/api/core/announcements", {"body_en": "x"}), 409, "ANNOUNCEMENT_TITLE_REQUIRED"
    )
    _error(
        client.post(
            "/api/core/announcements",
            {"title_en": "x", "starts_on": "2026-10-10", "ends_on": "2026-10-09"},
        ),
        409,
        "ANNOUNCEMENT_DATES_INVALID",
    )
    made = client.post(
        "/api/core/announcements", {"title_en": "x", "starts_on": str(date(2026, 10, 10))}
    )
    assert made.status_code == 201
    _error(
        client.request(
            "PATCH", f"/api/core/announcements/{made.json()['id']}", {"ends_on": "2026-10-01"}
        ),
        409,
        "ANNOUNCEMENT_DATES_INVALID",
    )
    _error(
        client.request("PATCH", f"/api/core/announcements/{made.json()['id']}", {"title_en": ""}),
        409,
        "ANNOUNCEMENT_TITLE_REQUIRED",
    )


def test_needs_manage_public_site(cashier_client: ApiClient) -> None:
    _error(cashier_client.get("/api/core/center-page"), 403, "PERMISSION_DENIED")
    _error(
        cashier_client.request("PUT", "/api/core/center-page", _body()), 403, "PERMISSION_DENIED"
    )
    _error(cashier_client.get("/api/core/announcements"), 403, "PERMISSION_DENIED")
    _error(
        cashier_client.post("/api/core/announcements", {"title_en": "x"}), 403, "PERMISSION_DENIED"
    )
    _error(
        cashier_client.request("PATCH", "/api/core/announcements/1", {"active": False}),
        403,
        "PERMISSION_DENIED",
    )


def test_manage_settings_alone_no_longer_opens_the_center_page(make_user: Any) -> None:
    """A role granted only ``core.manage_settings`` (and denied the new code) is refused."""
    from apps.core.models import Role, RolePermission

    role = Role.objects.get(code="receptionist")
    RolePermission.objects.create(role=role, code="core.manage_settings", allowed=True)
    make_user("desk-settings", roles=["receptionist"])
    api = ApiClient()
    assert api.login("desk-settings").status_code == 200
    assert api.get("/api/core/policy").status_code == 200
    _error(api.get("/api/core/center-page"), 403, "PERMISSION_DENIED")
    RolePermission.objects.create(role=role, code="core.manage_public_site", allowed=True)
    assert api.get("/api/core/center-page").status_code == 200
