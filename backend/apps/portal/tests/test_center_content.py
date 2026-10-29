"""The website content in the public answer (ADR 0029 H, Phase 2): images served only while the
website is on and only when shown, service and insurer names without prices, approved
testimonials only, FAQ, facilities, reasons and policies, each behind its switch."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.catalog.models import Payer, PriceItem, Service
from apps.core import models as core_models
from apps.core.models import (
    CenterFaq,
    CenterMedia,
    CenterPage,
    DoctorProfile,
    PublicSiteSettings,
    User,
)
from apps.portal.tests.conftest import PortalClient
from domain.tests.test_center_content import png

pytestmark = pytest.mark.django_db

URL = "/api/portal/center-page"
IMAGE_KEYS = {"id", "url", "alt_ar", "alt_en", "width", "height"}


@pytest.fixture
def author(seeded: None) -> User:
    return User.objects.get(username="admin")


@pytest.fixture
def media_root(settings: Any, tmp_path: Any) -> Any:
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _media(author: User, kind: str, **fields: Any) -> CenterMedia:
    from django.core.files.base import ContentFile

    data = png(3, 2)
    row = CenterMedia(
        kind=kind,
        content_type="image/png",
        width=3,
        height=2,
        size_bytes=len(data),
        created_by=author,
        **fields,
    )
    row.file.save(f"{kind}-test.png", ContentFile(data), save=False)
    row.save()
    return row


def _get() -> dict[str, Any]:
    response = PortalClient().get(URL)
    assert response.status_code == 200, response.content
    return response.json()


def _page(**fields: Any) -> None:
    CenterPage.load()
    CenterPage.objects.filter(pk=1).update(**fields)


def _testimonial(author: User, *, approved: bool, active: bool = True, text: str) -> Any:
    from django.utils import timezone

    return core_models.Testimonial.objects.create(
        text_en=text,
        author_en="A visitor",
        created_by=author,
        active=active,
        approved_by=author if approved else None,
        approved_at=timezone.now() if approved else None,
    )


def test_full_content_and_pinned_shapes(author: User, media_root: Any) -> None:
    hero = _media(author, "hero", alt_en="Front door")
    _media(author, "gallery", alt_en="Waiting room")
    _media(author, "gallery", alt_en="Hidden", active=False)
    _page(
        hero_title_en="Care close to home",
        facilities=[{"name_ar": "", "name_en": "Laboratory"}],
        reasons=[{"title_ar": "", "title_en": "Open late", "text_ar": "", "text_en": "To 10 pm"}],
        accessibility_en="Step-free entrance",
        privacy_en="Your data stays here",
        cancellation_policy_en="Cancel a day before",
        maps_url="https://maps.app.goo.gl/abc",
    )
    CenterFaq.objects.create(question_en="Parking?", answer_en="Yes", created_by=author)
    CenterFaq.objects.create(question_en="Hidden?", answer_en="No", created_by=author, active=False)
    shown = _testimonial(author, approved=True, text="Kind staff")
    _testimonial(author, approved=False, text="Waiting for approval")
    _testimonial(author, approved=True, active=False, text="Taken down")

    body = _get()
    assert body["hero_title_en"] == "Care close to home"
    assert body["hero_image"]["id"] == hero.pk
    assert set(body["hero_image"]) == IMAGE_KEYS
    assert body["hero_image"]["url"].startswith(f"/api/portal/center-media/{hero.pk}?v=")
    assert [g["alt_en"] for g in body["gallery"]] == ["Waiting room"]
    assert body["facilities"] == [{"name_ar": "", "name_en": "Laboratory"}]
    assert body["reasons"][0]["title_en"] == "Open late"
    assert [f["question_en"] for f in body["faq"]] == ["Parking?"]
    assert set(body["faq"][0]) == {"id", "question_ar", "question_en", "answer_ar", "answer_en"}
    # Only approved and active testimonials reach the public.
    assert [t["id"] for t in body["testimonials"]] == [shown.pk]
    assert set(body["testimonials"][0]) == {"id", "text_ar", "text_en", "author_ar", "author_en"}
    assert body["maps_url"] == "https://maps.app.goo.gl/abc"
    assert body["cancellation_policy_en"] == "Cancel a day before"
    text = json.dumps(body)
    assert "Waiting for approval" not in text
    assert "Taken down" not in text


def test_services_and_insurers_by_name_never_prices(author: User) -> None:
    body = _get()
    dept_id = body["departments"][0]["id"]
    service = (
        Service.objects.filter(department_id=dept_id, active=True)
        .exclude(kind="consultation")
        .first()
    ) or Service.objects.create(
        code="SITE-X", name_ar="أشعة", name_en="X-ray", kind="procedure", department_id=dept_id
    )
    Service.objects.filter(pk=service.pk).update(show_on_site=True)
    Payer.objects.filter(pk__in=Payer.objects.values("pk")[:1]).update(show_on_site=True)
    payer = Payer.objects.filter(show_on_site=True).first()
    assert payer is not None
    body = _get()
    dept = next(d for d in body["departments"] if d["id"] == dept_id)
    assert {"id": service.pk, "name_ar": service.name_ar, "name_en": service.name_en} in dept[
        "services"
    ]
    for d in body["departments"]:
        for s in d["services"]:
            assert set(s) == {"id", "name_ar", "name_en"}
    assert body["insurance"] == [
        {"id": payer.pk, "name_ar": payer.name_ar, "name_en": payer.name_en}
    ]
    text = json.dumps(body, ensure_ascii=False).lower()
    for word in ("price", "fee", "amount", "contract", "consultation"):
        assert word not in text, word
    prices = {str(p) for p in PriceItem.objects.values_list("unit_price", flat=True) if p}
    for price in prices:
        assert f'"{price}"' not in text
    # Switched off, the names go.
    _page(show_services=False, show_insurance=False)
    body = _get()
    assert all(d["services"] == [] for d in body["departments"])
    assert body["insurance"] == []


def test_hidden_department_hides_its_services(author: User) -> None:
    body = _get()
    dept_id = body["departments"][0]["id"]
    service = Service.objects.create(
        code="SITE-Y", name_ar="خدمة", name_en="Service Y", kind="procedure", department_id=dept_id
    )
    Service.objects.filter(pk=service.pk).update(show_on_site=True)
    _page(hidden_department_ids=[dept_id])
    assert "Service Y" not in json.dumps(_get())


def test_doctor_profile_on_the_page(author: User, media_root: Any) -> None:
    doctor_id = _get()["doctors"][0]["id"]
    photo = _media(author, "doctor", alt_en="Portrait")
    DoctorProfile.objects.filter(pk=doctor_id).update(
        qualifications_en="MBBS", bio_en="Twenty years", photo=photo
    )
    doctor = next(d for d in _get()["doctors"] if d["id"] == doctor_id)
    assert doctor["qualifications_en"] == "MBBS"
    assert doctor["bio_en"] == "Twenty years"
    assert set(doctor["photo"]) == IMAGE_KEYS
    image = PortalClient().get(doctor["photo"]["url"])
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image["Cache-Control"] == "public, max-age=3600"
    assert image["X-Content-Type-Options"] == "nosniff"
    # A hidden doctor's photo is not served.
    _page(hidden_doctor_ids=[doctor_id])
    assert PortalClient().get(f"/api/portal/center-media/{photo.pk}").status_code == 404


def test_media_is_served_only_while_shown_and_the_site_is_on(author: User, media_root: Any) -> None:
    row = _media(author, "gallery")
    client = PortalClient()
    url = f"/api/portal/center-media/{row.pk}"
    assert client.get(url).status_code == 200
    CenterMedia.objects.filter(pk=row.pk).update(active=False)
    missing = client.get(url)
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    CenterMedia.objects.filter(pk=row.pk).update(active=True)
    PublicSiteSettings.objects.filter(pk=1).update(site_enabled=False)
    off = client.get(url)
    assert off.status_code == 404
    assert off.json()["code"] == "SITE_DISABLED"
    assert client.get("/api/portal/center-media/999999").status_code == 404


def test_media_reads_count_against_the_address(
    author: User, media_root: Any, settings: Any
) -> None:
    row = _media(author, "gallery")
    settings.PORTAL_PAGE_IP_MAX = 1
    client = PortalClient()
    assert client.get(f"/api/portal/center-media/{row.pk}").status_code == 200
    assert client.get(f"/api/portal/center-media/{row.pk}").status_code == 429


def test_switches_hide_their_sections(author: User, media_root: Any) -> None:
    _media(author, "gallery")
    _page(
        facilities=[{"name_ar": "", "name_en": "Lab"}],
        privacy_en="p",
        cancellation_policy_en="c",
        show_facilities=False,
        show_policies=False,
        show_faq=False,
        show_testimonials=False,
        show_about=False,
    )
    CenterFaq.objects.create(question_en="Q", answer_en="A", created_by=author)
    _testimonial(author, approved=True, text="Kind")
    body = _get()
    for key in ("facilities", "faq", "testimonials", "gallery"):
        assert body[key] == [], key
    for key in ("privacy_en", "cancellation_policy_en"):
        assert body[key] == "", key
