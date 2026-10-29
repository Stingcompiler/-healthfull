"""Website content administration (ADR 0029 H, Phase 2): the new center page sections, images
(size cap, checked by content), FAQ, testimonials (shown only once approved, approval behind
``core.approve_testimonial``), doctors' website profiles, and the insurers and services shown by
name. Everything behind ``core.manage_public_site`` and tracked by pghistory."""

from __future__ import annotations

from typing import Any

import pghistory.models
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import Payer, Service
from apps.core import models as core_models
from apps.core.models import CenterFaq, CenterMedia, CenterPage, Department, DoctorProfile, User
from conftest import ApiClient
from domain.tests.test_center_content import jpeg, png, webp

pytestmark = pytest.mark.django_db


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


def _signed_in(make_user: Any, username: str, roles: list[str]) -> ApiClient:
    make_user(username, roles=roles)
    api = ApiClient()
    assert api.login(username).status_code == 200
    return api


@pytest.fixture
def admin(make_user: Any) -> ApiClient:
    return _signed_in(make_user, "siteadmin", ["admin"])


@pytest.fixture
def manager(make_user: Any) -> ApiClient:
    return _signed_in(make_user, "sitemanager", ["manager"])


@pytest.fixture
def editor(make_user: Any) -> ApiClient:
    """A receptionist granted the website (an editor who may not approve testimonials)."""
    role = core_models.Role.objects.get(code="receptionist")
    core_models.RolePermission.objects.create(
        role=role, code="core.manage_public_site", allowed=True
    )
    return _signed_in(make_user, "siteeditor", ["receptionist"])


@pytest.fixture
def media_root(settings: Any, tmp_path: Any) -> Any:
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def upload(api: ApiClient, data: bytes, *, kind: str = "gallery", name: str = "x.png") -> Any:
    return api.django.post(
        "/api/core/center-media",
        data={
            "file": SimpleUploadedFile(name, data, content_type="image/png"),
            "kind": kind,
            "alt_en": "The waiting room",
        },
        headers={"X-CSRFToken": api.csrftoken or api.fetch_csrf()},
    )


# --- center page fields --------------------------------------------------------------------


def _page_body(admin: ApiClient, **fields: Any) -> dict[str, Any]:
    body = admin.get("/api/core/center-page").json()
    body.pop("updated_at")
    body.update(fields)
    return body


def test_new_sections_are_saved_and_tracked(admin: ApiClient) -> None:
    body = _page_body(
        admin,
        hero_title_en="Care close to home",
        hero_text_ar="رعاية قريبة منك",
        facilities=[{"name_en": " Laboratory "}, {"name_ar": "صيدلية"}],
        reasons=[{"title_en": "Open late", "text_en": "Until 10 pm"}],
        accessibility_en="Step-free entrance",
        privacy_en="We keep your data on the center's server.",
        cancellation_policy_en="Cancel a day before.",
        maps_url=" https://maps.app.goo.gl/abc ",
        show_faq=False,
    )
    saved = admin.request("PUT", "/api/core/center-page", body)
    assert saved.status_code == 200, saved.content
    out = saved.json()
    assert out["facilities"] == [
        {"name_ar": "", "name_en": "Laboratory"},
        {"name_ar": "صيدلية", "name_en": ""},
    ]
    assert out["reasons"][0]["title_en"] == "Open late"
    assert out["maps_url"] == "https://maps.app.goo.gl/abc"
    assert out["show_faq"] is False
    page = CenterPage.load()
    assert page.hero_title_en == "Care close to home"
    events = pghistory.models.Events.objects.references(page)
    assert any(e.pgh_context and e.pgh_context.get("reason") == "center page" for e in events)


def test_row_caps_and_maps_link(admin: ApiClient) -> None:
    too_many = _page_body(admin, facilities=[{"name_en": f"F{i}"} for i in range(21)])
    assert admin.request("PUT", "/api/core/center-page", too_many).status_code == 422
    reasons = _page_body(admin, reasons=[{"title_en": f"R{i}"} for i in range(9)])
    assert admin.request("PUT", "/api/core/center-page", reasons).status_code == 422
    untitled = _page_body(admin, reasons=[{"text_en": "no title"}])
    _error(admin.request("PUT", "/api/core/center-page", untitled), 409, "CENTER_ROWS_INVALID")
    bad_map = _page_body(admin, maps_url="javascript:alert(1)")
    _error(admin.request("PUT", "/api/core/center-page", bad_map), 409, "CENTER_MAPS_URL_INVALID")


# --- images --------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [png(), jpeg(), webp()])
def test_real_images_are_stored_with_their_size(
    admin: ApiClient, media_root: Any, data: bytes
) -> None:
    response = upload(admin, data)
    assert response.status_code == 201, response.content
    row = response.json()
    assert row["kind"] == "gallery"
    assert row["width"] > 0
    assert row["height"] > 0
    assert row["size_bytes"] == len(data)
    # The file name and type come from the bytes, never from what the browser said.
    stored = CenterMedia.objects.get(pk=row["id"])
    assert stored.file.name.endswith(
        {"image/png": ".png", "image/jpeg": ".jpg"}.get(stored.content_type, ".webp")
    )
    preview = admin.get(row["url"])
    assert preview.status_code == 200
    assert preview.content == data
    assert preview["X-Content-Type-Options"] == "nosniff"


def test_images_over_2mb_are_refused(admin: ApiClient, media_root: Any) -> None:
    big = png() + b"\x00" * (2 * 1024 * 1024)
    _error(upload(admin, big), 409, "MEDIA_TOO_LARGE")
    assert not CenterMedia.objects.exists()


@pytest.mark.parametrize(
    "data",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"\x89PNG\r\n\x1a\n" + b"not really a png" * 4,
        png()[:-8],
        b"MZ\x90\x00 an executable",
    ],
)
def test_fake_images_are_refused_by_content(admin: ApiClient, media_root: Any, data: bytes) -> None:
    _error(upload(admin, data, name="photo.png"), 409, "MEDIA_INVALID_IMAGE")
    assert not CenterMedia.objects.exists()
    assert not list(media_root.rglob("*.*"))


def test_unknown_kind_is_refused(admin: ApiClient, media_root: Any) -> None:
    assert upload(admin, png(), kind="banner").status_code == 422


def test_image_edit_and_removal(
    admin: ApiClient, media_root: Any, django_capture_on_commit_callbacks: Any
) -> None:
    row = upload(admin, png(), kind="doctor").json()
    edited = admin.patch(f"/api/core/center-media/{row['id']}", {"alt_ar": "صورة", "active": False})
    assert edited.status_code == 200, edited.content
    assert edited.json()["active"] is False
    stored = CenterMedia.objects.get(pk=row["id"])
    path = media_root / stored.file.name
    assert path.exists()
    with django_capture_on_commit_callbacks(execute=True):
        removed = admin.request("DELETE", f"/api/core/center-media/{row['id']}")
    assert removed.status_code == 204
    assert not CenterMedia.objects.filter(pk=row["id"]).exists()
    assert not path.exists()
    assert pghistory.models.Events.objects.filter(pgh_obj_id=row["id"], pgh_label="delete").exists()


def test_image_count_is_capped(admin: ApiClient, media_root: Any, settings: Any) -> None:
    from apps.core import services

    first = upload(admin, png()).json()
    original = services.MEDIA_MAX_ROWS
    services.MEDIA_MAX_ROWS = 1
    try:
        _error(upload(admin, png()), 409, "MEDIA_LIMIT_REACHED")
    finally:
        services.MEDIA_MAX_ROWS = original
    assert CenterMedia.objects.count() == 1
    assert first["id"]


# --- FAQ -----------------------------------------------------------------------------------


def test_faq_needs_a_question_and_an_answer(admin: ApiClient) -> None:
    _error(admin.post("/api/core/center-faq", {"answer_en": "Yes"}), 409, "FAQ_QUESTION_REQUIRED")
    _error(
        admin.post("/api/core/center-faq", {"question_en": "Parking?"}), 409, "FAQ_ANSWER_REQUIRED"
    )
    made = admin.post("/api/core/center-faq", {"question_en": "Parking?", "answer_en": "Yes"})
    assert made.status_code == 201, made.content
    faq_id = made.json()["id"]
    assert (
        admin.patch(f"/api/core/center-faq/{faq_id}", {"sort_order": 3}).json()["sort_order"] == 3
    )
    assert admin.request("DELETE", f"/api/core/center-faq/{faq_id}").status_code == 204
    assert not CenterFaq.objects.exists()


# --- testimonials --------------------------------------------------------------------------


def test_testimonials_start_unapproved_and_only_an_approver_approves(
    editor: ApiClient, manager: ApiClient
) -> None:
    made = editor.post(
        "/api/core/testimonials", {"text_ar": "استقبال لطيف", "author_ar": "أم أحمد"}
    )
    assert made.status_code == 201, made.content
    row = made.json()
    assert row["approved"] is False
    url = f"/api/core/testimonials/{row['id']}/approve"
    body = _error(editor.post(url), 403, "PERMISSION_DENIED")
    assert body["details"] == {"permission": "core.approve_testimonial"}
    approved = manager.post(url)
    assert approved.status_code == 200, approved.content
    out = approved.json()
    assert out["approved"] is True
    assert out["approved_at"]
    assert out["approved_by_name"]
    stored = core_models.Testimonial.objects.get(pk=row["id"])
    assert stored.approved_by == User.objects.get(username="sitemanager")
    _error(manager.post(url), 409, "TESTIMONIAL_ALREADY_APPROVED")


def test_new_words_take_the_approval_back(editor: ApiClient, manager: ApiClient) -> None:
    row = editor.post("/api/core/testimonials", {"text_en": "Kind staff"}).json()
    manager.post(f"/api/core/testimonials/{row['id']}/approve")
    reordered = editor.patch(f"/api/core/testimonials/{row['id']}", {"sort_order": 2}).json()
    assert reordered["approved"] is True
    edited = editor.patch(f"/api/core/testimonials/{row['id']}", {"text_en": "Very kind staff"})
    assert edited.json()["approved"] is False
    assert edited.json()["approved_by_name"] is None


def test_testimonial_needs_words(editor: ApiClient) -> None:
    _error(
        editor.post("/api/core/testimonials", {"author_en": "A."}), 409, "TESTIMONIAL_TEXT_REQUIRED"
    )
    assert editor.post("/api/core/testimonials", {"text_en": "x" * 401}).status_code == 422


def test_a_database_row_cannot_claim_an_undocumented_approval(make_user: Any) -> None:
    from django.db import IntegrityError, transaction

    author = make_user("writer")
    with pytest.raises(IntegrityError), transaction.atomic():
        core_models.Testimonial.objects.create(
            text_en="x", created_by=author, approved_by=author, approved_at=None
        )


# --- doctors, insurers, services -----------------------------------------------------------


def _doctor(make_user: Any) -> DoctorProfile:
    dept = Department.objects.create(code="SITE-D", name_ar="قسم", name_en="Dept")
    user = make_user("drsite", full_name_en="Site Doctor", full_name_ar="طبيب")
    return DoctorProfile.objects.create(user=user, department=dept)


def test_doctor_website_profile(admin: ApiClient, make_user: Any, media_root: Any) -> None:
    doctor = _doctor(make_user)
    gallery = upload(admin, png(), kind="gallery").json()
    photo = upload(admin, png(), kind="doctor").json()
    url = f"/api/core/center-page/doctors/{doctor.pk}"
    _error(admin.patch(url, {"photo_id": gallery["id"]}), 409, "MEDIA_KIND_MISMATCH")
    _error(admin.patch(url, {"photo_id": 999999}), 409, "MEDIA_NOT_FOUND")
    assert admin.patch(url, {"bio_en": "x" * 401}).status_code == 422
    saved = admin.patch(
        url, {"qualifications_en": "MBBS, MD", "bio_en": "Twenty years", "photo_id": photo["id"]}
    )
    assert saved.status_code == 200, saved.content
    assert saved.json()["photo_id"] == photo["id"]
    cleared = admin.patch(url, {"photo_id": None})
    assert cleared.json()["photo_id"] is None
    assert cleared.json()["qualifications_en"] == "MBBS, MD"
    listed = admin.get("/api/core/center-page/doctors").json()
    assert any(d["id"] == doctor.pk for d in listed)


def test_payers_and_services_are_shown_by_name_only(admin: ApiClient) -> None:
    payer = Payer.objects.create(code="SITE-P", name_ar="تأمين", name_en="Insurer")
    service = Service.objects.create(
        code="SITE-S", name_ar="أشعة", name_en="X-ray", kind="procedure"
    )
    assert payer.show_on_site is False
    assert service.show_on_site is False
    out = admin.request(
        "PUT", f"/api/core/center-page/payers/{payer.pk}", {"show_on_site": True}
    ).json()
    assert out["show_on_site"] is True
    out = admin.request(
        "PUT", f"/api/core/center-page/services/{service.pk}", {"show_on_site": True}
    ).json()
    assert out["show_on_site"] is True
    services = admin.get("/api/core/center-page/services").json()
    row = next(s for s in services if s["id"] == service.pk)
    assert set(row) == {
        "id",
        "code",
        "name_ar",
        "name_en",
        "kind",
        "department_id",
        "department_ar",
        "department_en",
        "active",
        "show_on_site",
    }
    payers = admin.get("/api/core/center-page/payers").json()
    assert set(next(p for p in payers if p["id"] == payer.pk)) == {
        "id",
        "code",
        "name_ar",
        "name_en",
        "active",
        "show_on_site",
    }
    payer.refresh_from_db()
    events = pghistory.models.Events.objects.references(payer)
    assert any(e.pgh_context and e.pgh_context.get("reason") == "payer on website" for e in events)


# --- permissions ---------------------------------------------------------------------------

STAFF_ONLY = [
    ("GET", "/api/core/center-media"),
    ("GET", "/api/core/center-media/1/file"),
    ("PATCH", "/api/core/center-media/1"),
    ("DELETE", "/api/core/center-media/1"),
    ("GET", "/api/core/center-faq"),
    ("POST", "/api/core/center-faq"),
    ("GET", "/api/core/testimonials"),
    ("POST", "/api/core/testimonials"),
    ("POST", "/api/core/testimonials/1/approve"),
    ("GET", "/api/core/center-page/doctors"),
    ("PATCH", "/api/core/center-page/doctors/1"),
    ("GET", "/api/core/center-page/payers"),
    ("PUT", "/api/core/center-page/payers/1"),
    ("GET", "/api/core/center-page/services"),
    ("PUT", "/api/core/center-page/services/1"),
]


@pytest.mark.parametrize(("method", "path"), STAFF_ONLY)
def test_a_cashier_is_refused(make_user: Any, method: str, path: str) -> None:
    api = _signed_in(make_user, "sitetill", ["cashier"])
    body = {"show_on_site": True} if method == "PUT" else {}
    _error(api.request(method, path, body if method != "GET" else None), 403, "PERMISSION_DENIED")


def test_nobody_signed_in_is_refused() -> None:
    assert ApiClient().get("/api/core/center-media").status_code == 401
    assert ApiClient().get("/api/core/testimonials").status_code == 401


def test_new_models_are_history_tracked() -> None:
    from django.apps import apps

    names = {m.__name__ for m in apps.get_app_config("core").get_models()}
    for model in ("CenterMedia", "CenterFaq", "Testimonial"):
        assert f"{model}Event" in names, model
