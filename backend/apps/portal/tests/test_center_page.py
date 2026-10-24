"""The public center page and logo (``/api/portal/center-page``, ``/center-logo``): no sign-in,
only public fields, only active announcements inside their dates, hidden items left out, and a
per-address limit like the receipt check."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core.models import (
    Announcement,
    CenterPage,
    CenterProfile,
    Department,
    DoctorProfile,
    User,
)
from apps.portal.models import PortalEvent, PortalEventKind
from apps.portal.tests.conftest import PortalClient
from apps.visits.models import DoctorSchedule

pytestmark = pytest.mark.django_db

URL = "/api/portal/center-page"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

TOP_KEYS = {
    "name_ar",
    "name_en",
    "logo_url",
    "about_ar",
    "about_en",
    "hours",
    "today",
    "departments",
    "doctors",
    "announcements",
    "phone",
    "phone_uri",
    "whatsapp",
    "email",
    "address",
    "directions_ar",
    "directions_en",
}
DOCTOR_KEYS = {
    "id",
    "name_ar",
    "name_en",
    "specialty_ar",
    "specialty_en",
    "department_id",
    "department_ar",
    "department_en",
    "clinic_days",
}

WEEK = [{"weekday": d, "closed": d == 4, "opens": "08:00", "closes": "20:00"} for d in range(7)]


def _profile(**fields: Any) -> CenterProfile:
    profile = CenterProfile.load()
    defaults = {
        "name_ar": "مركز النيل الطبي",
        "name_en": "Nile Medical Center",
        "address": "Khartoum 2, Street 15",
        "phone": "0183 123 456",
        "registration_no": "REG-SECRET-1",
        "tax_no": "TAX-SECRET-1",
    }
    for key, value in {**defaults, **fields}.items():
        setattr(profile, key, value)
    profile.save()
    return profile


def _page(**fields: Any) -> CenterPage:
    page = CenterPage.load()
    defaults = {
        "about_ar": "مركز للرعاية الأولية",
        "about_en": "Primary care center",
        "hours": WEEK,
        "whatsapp": "249912345678",
        "email": "info@nile.example",
        "directions_ar": "بجوار الجامع",
        "directions_en": "Next to the mosque",
    }
    for key, value in {**defaults, **fields}.items():
        setattr(page, key, value)
    page.save()
    return page


def _announce(author: User, **fields: Any) -> Announcement:
    return Announcement.objects.create(created_by=author, **{"title_en": "Notice", **fields})


@pytest.fixture
def author(seeded: None) -> User:
    return User.objects.filter(is_active=True).order_by("pk").first()  # type: ignore[return-value]


def _get(client: PortalClient | None = None) -> dict[str, Any]:
    response = (client or PortalClient()).get(URL)
    assert response.status_code == 200, response.content
    return response.json()


def test_no_sign_in_needed_and_never_cached(seeded: None) -> None:
    _profile()
    client = PortalClient()
    response = client.get(URL)
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "no-store"
    assert client.portal_cookie is None
    body = response.json()
    assert body["name_en"] == "Nile Medical Center"
    assert body["logo_url"] is None


def test_only_public_fields(seeded: None, author: User) -> None:
    _profile()
    _page()
    _announce(author, body_en="Closed on Eid")
    body = _get()
    assert set(body) == TOP_KEYS
    assert body["doctors"], "the seed has doctors with schedules"
    for doctor in body["doctors"]:
        assert set(doctor) == DOCTOR_KEYS
        assert doctor["clinic_days"]
        for day in doctor["clinic_days"]:
            assert set(day) == {"weekday", "starts", "ends"}
    for dept in body["departments"]:
        assert set(dept) == {"id", "name_ar", "name_en"}
    assert set(body["announcements"][0]) == {
        "id",
        "title_ar",
        "title_en",
        "body_ar",
        "body_en",
        "starts_on",
        "ends_on",
    }
    text = json.dumps(body, ensure_ascii=False)
    assert "SECRET" not in text  # registration and tax numbers stay off the public page
    for word in ("price", "fee", "amount", "username", "consultation"):
        assert word not in text.lower()
    # Staff are never named, except the doctors shown.
    shown = {d["name_en"] for d in body["doctors"]} | {d["name_ar"] for d in body["doctors"]}
    for user in User.objects.exclude(doctor_profile__isnull=False):
        for name in (user.display_name_en, user.display_name_ar, user.username):
            if name and name not in shown and len(name) > 3:
                assert name not in text, name
    assert body["phone_uri"] == "tel:0183123456"
    assert body["whatsapp"] == "249912345678"


def test_hours_and_today(seeded: None) -> None:
    _profile()
    _page()
    body = _get()
    assert [h["weekday"] for h in body["hours"]] == list(range(7))
    friday = body["hours"][4]
    assert friday == {"weekday": 4, "closed": True, "opens": None, "closes": None}
    today = body["today"]
    assert today["weekday"] == timezone.localdate().weekday()
    if today["weekday"] == 4:
        assert today["state"] == "closed_today"
    else:
        assert today["state"] in {"open", "opens_later", "closed_now"}
        assert (today["opens"], today["closes"]) == ("08:00", "20:00")


def test_only_active_announcements_inside_their_dates(seeded: None, author: User) -> None:
    today = timezone.localdate()
    shown = {
        _announce(author, title_en="open-ended").pk,
        _announce(author, title_en="ends today", ends_on=today).pk,
        _announce(author, title_en="starts today", starts_on=today).pk,
        _announce(author, title_en="window", starts_on=today - timedelta(days=1), ends_on=today).pk,
    }
    _announce(author, title_en="inactive", active=False)
    _announce(author, title_en="future", starts_on=today + timedelta(days=1))
    _announce(author, title_en="past", ends_on=today - timedelta(days=1))
    body = _get()
    assert {a["id"] for a in body["announcements"]} == shown


def test_announcements_follow_their_order(seeded: None, author: User) -> None:
    second = _announce(author, title_en="second", sort_order=2)
    first = _announce(author, title_en="first", sort_order=1)
    assert [a["id"] for a in _get()["announcements"]] == [first.pk, second.pk]


def test_hidden_department_hides_its_doctors(seeded: None) -> None:
    before = _get()
    doctor = before["doctors"][0]
    dept_id = doctor["department_id"]
    _page(hidden_department_ids=[dept_id])
    after = _get()
    assert dept_id not in {d["id"] for d in after["departments"]}
    assert all(d["department_id"] != dept_id for d in after["doctors"])


def test_hidden_doctor_is_left_out(seeded: None) -> None:
    before = _get()
    hidden = before["doctors"][0]["id"]
    _page(hidden_doctor_ids=[hidden])
    after = _get()
    assert hidden not in {d["id"] for d in after["doctors"]}
    assert len(after["doctors"]) == len(before["doctors"]) - 1


def test_inactive_items_and_old_schedules_are_left_out(seeded: None) -> None:
    body = _get()
    first, *_ = body["doctors"]
    profile = DoctorProfile.objects.get(pk=first["id"])
    DoctorSchedule.objects.filter(doctor=profile).update(
        valid_to=timezone.localdate() - timedelta(days=1)
    )
    dept = Department.objects.exclude(pk=first["department_id"]).first()
    assert dept is not None
    dept.active = False
    dept.save()
    after = _get()
    assert first["id"] not in {d["id"] for d in after["doctors"]}
    assert dept.pk not in {d["id"] for d in after["departments"]}


def test_hidden_sections_come_back_empty(seeded: None, author: User) -> None:
    _profile()
    _page(
        show_about=False,
        show_hours=False,
        show_departments=False,
        show_doctors=False,
        show_announcements=False,
        show_contact=False,
        show_address=False,
    )
    _announce(author)
    body = _get()
    assert body["name_en"] == "Nile Medical Center"  # identity always shows
    for key in ("about_ar", "about_en", "phone", "phone_uri", "whatsapp", "email", "address"):
        assert body[key] == "", key
    for key in ("directions_ar", "directions_en"):
        assert body[key] == "", key
    for key in ("hours", "departments", "doctors", "announcements"):
        assert body[key] == [], key
    assert body["today"] is None


def test_unpublished_hours_have_no_today(seeded: None) -> None:
    _page(hours=[])
    body = _get()
    assert body["hours"] == []
    assert body["today"] is None


def test_public_logo(seeded: None, settings: Any, tmp_path: Any) -> None:
    settings.MEDIA_ROOT = str(tmp_path)
    client = PortalClient()
    assert client.get("/api/portal/center-logo").status_code == 404
    profile = _profile()
    profile.logo.save("logo-test.png", ContentFile(PNG), save=True)
    body = _get()
    assert body["logo_url"].startswith("/api/portal/center-logo?v=")
    image = client.get(body["logo_url"])
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image["Cache-Control"] == "public, max-age=3600"
    assert image.content == PNG


def test_reads_are_rate_limited_per_address(seeded: None, settings: Any) -> None:
    settings.PORTAL_PAGE_IP_MAX = 2
    client = PortalClient()
    assert client.get(URL).status_code == 200
    assert client.get("/api/portal/center-logo").status_code == 404  # counts too
    refused = client.get(URL)
    assert refused.status_code == 429
    assert refused.json()["code"] == "RATE_LIMITED"
    assert refused.json()["details"]["retry_after_seconds"] > 0
    assert PortalEvent.objects.filter(kind=PortalEventKind.PAGE_THROTTLED).count() == 1


def test_staff_session_is_not_needed_or_used(seeded: None, api_client: Any) -> None:
    # A signed-in staff browser gets the same public answer as anyone.
    _profile()
    assert api_client.get(URL).status_code == 200
