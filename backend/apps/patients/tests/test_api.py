"""``/api/patients`` contract: happy paths, permission denied and domain error codes."""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.tests import builders as b
from apps.patients import services as ps
from apps.patients.models import Patient, PatientMerge
from conftest import ApiClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk(make_user):
    return make_user("clerk", roles=["receptionist"])


@pytest.fixture
def client_as(make_user, api_client: ApiClient):
    def _login(*roles: str) -> ApiClient:
        user = make_user(roles=list(roles))
        response = api_client.login(user.username)
        assert response.status_code == 200, response.content
        return api_client

    return _login


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code
    return body


def _register(clerk: Any, **kw: Any) -> Patient:
    kw.setdefault("sex", "male")
    return ps.register_patient(ps.PatientData(**kw), actor=clerk, confirm_not_duplicate=True)


# --- create, duplicates, emergency ----------------------------------------------------------


def test_create_patient_and_duplicate_warning(client_as) -> None:
    api = client_as("receptionist")
    body = {"full_name_ar": "أحمد عثمان", "sex": "male", "phone": "0912345678"}
    created = api.post("/api/patients", body)
    assert created.status_code == 201, created.content
    first = created.json()
    assert first["file_no"].startswith("PT-")
    assert first["coverage"] is None
    assert first["is_incomplete"] is False

    # Same phone again: the live check lists the first file, and creating refuses.
    live = api.get("/api/patients/duplicates?phone=%2B249912345678")
    assert live.status_code == 200
    assert [d["patient"]["id"] for d in live.json()] == [first["id"]]
    assert live.json()[0]["reasons"] == ["phone"]
    refused = _error(
        api.post("/api/patients", {**body, "full_name_ar": "احمد عثمان"}),
        409,
        "DUPLICATE_PATIENT",
    )
    assert refused["details"]["candidates"][0]["id"] == first["id"]
    confirmed = api.post("/api/patients", {**body, "confirm_not_duplicate": True})
    assert confirmed.status_code == 201


def test_create_requires_a_name_and_permission(client_as) -> None:
    api = client_as("receptionist")
    _error(api.post("/api/patients", {"sex": "female"}), 409, "NAME_REQUIRED")
    assert api.post("/api/patients", {"full_name_en": "X", "sex": "unknown"}).status_code == 422


def test_doctor_cannot_register_a_full_file(client_as) -> None:
    api = client_as("doctor")
    response = api.post("/api/patients", {"full_name_en": "Sara Ali", "sex": "female"})
    _error(response, 403, "PERMISSION_DENIED")


def test_emergency_registration_then_completion(client_as) -> None:
    api = client_as("receptionist")
    created = api.post("/api/patients/emergency", {"name": "مجهول", "sex": "unknown"})
    assert created.status_code == 201, created.content
    file = created.json()
    assert file["is_incomplete"] is True
    assert file["sex"] == "unknown"

    listed = api.get("/api/patients?incomplete=true")
    assert [p["id"] for p in listed.json()["items"]] == [file["id"]]

    patch = {"sex": "male", "date_of_birth": "1990-01-02", "phone": "0911000111"}
    done = api.patch(f"/api/patients/{file['id']}", patch)
    assert done.status_code == 200, done.content
    assert done.json()["is_incomplete"] is False
    assert done.json()["date_of_birth"] == "1990-01-02"


# --- search, profile ------------------------------------------------------------------------


def test_search_is_paged_and_folds_arabic_variants(client_as, clerk) -> None:
    target = _register(clerk, full_name_ar="فاطمة إبراهيم", sex="female", phone="0915550001")
    _register(clerk, full_name_ar="عثمان الطيب", phone="0915550002")
    api = client_as("nurse")
    found = api.get("/api/patients?q=فاطمه ابراهيم")
    assert found.status_code == 200
    page = found.json()
    assert page["count"] == 1
    assert page["items"][0]["id"] == target.pk
    assert api.get(f"/api/patients?q={target.file_no}").json()["items"][0]["id"] == target.pk
    assert api.get("/api/patients?q=5550001").json()["count"] == 1
    paged = api.get("/api/patients?page_size=1&page=2").json()
    assert paged["page"] == 2
    assert len(paged["items"]) == 1


def test_profile_shows_allergies_and_merged_into(client_as, clerk) -> None:
    keep = _register(clerk, full_name_ar="سلمى عوض", sex="female")
    api = client_as("receptionist")
    body = api.get(f"/api/patients/{keep.pk}").json()
    assert body["patient"]["id"] == keep.pk
    assert body["merged_into"] is None
    assert body["allergies"] == []
    assert api.get("/api/patients/999999").status_code == 404


# --- merge ----------------------------------------------------------------------------------


def test_merge_needs_supervisor_and_reason(client_as, clerk) -> None:
    keep = _register(clerk, full_name_ar="محمد أحمد", phone="0912000010")
    dup = _register(clerk, full_name_ar="محمد احمد")
    payload = {"duplicate_id": dup.pk, "reason_code": "DUPLICATE_REGISTRATION", "note": "same"}

    reception = client_as("receptionist")
    _error(reception.post(f"/api/patients/{keep.pk}/merge", payload), 403, "PERMISSION_DENIED")

    manager = client_as("manager")
    _error(
        manager.post(f"/api/patients/{keep.pk}/merge", {**payload, "note": "  "}),
        409,
        "REASON_REQUIRED",
    )
    _error(
        manager.post(f"/api/patients/{keep.pk}/merge", {**payload, "duplicate_id": keep.pk}),
        409,
        "MERGE_SAME_FILE",
    )
    merged = manager.post(f"/api/patients/{keep.pk}/merge", payload)
    assert merged.status_code == 201, merged.content
    assert merged.json()["reason_code"] == "DUPLICATE_REGISTRATION"
    assert merged.json()["source"]["id"] == dup.pk
    assert PatientMerge.objects.filter(source=dup, target=keep).exists()

    history = manager.get(f"/api/patients/{dup.pk}/merges").json()
    assert history[0]["target"]["id"] == keep.pk
    profile = manager.get(f"/api/patients/{dup.pk}").json()
    assert profile["merged_into"]["id"] == keep.pk
    _error(manager.post(f"/api/patients/{keep.pk}/merge", payload), 409, "PATIENT_MERGED")


# --- coverage and balance -------------------------------------------------------------------


def test_coverage_crud(client_as, clerk) -> None:
    pat = _register(clerk, full_name_en="Omer Salih")
    insurer = b.payer(requires_card_number=True)
    api = client_as("receptionist")
    payers = api.get("/api/patients/payers").json()
    assert insurer.pk in [p["id"] for p in payers]

    _error(
        api.post(f"/api/patients/{pat.pk}/coverages", {"payer_id": insurer.pk}),
        409,
        "CARD_NUMBER_REQUIRED",
    )
    created = api.post(
        f"/api/patients/{pat.pk}/coverages",
        {"payer_id": insurer.pk, "card_number": "C-1", "patient_percent_override": "20.00"},
    )
    assert created.status_code == 201, created.content
    cov = created.json()
    assert cov["is_default"] is True
    assert cov["patient_percent_override"] == "20.00"
    assert (
        api.get(f"/api/patients?q={pat.file_no}").json()["items"][0]["coverage"]["id"]
        == (cov["id"])
    )

    edited = api.patch(f"/api/patients/coverages/{cov['id']}", {"card_number": "C-2"})
    assert edited.json()["card_number"] == "C-2"
    _error(
        api.patch(
            f"/api/patients/coverages/{cov['id']}",
            {"valid_from": "2026-05-01", "valid_to": "2026-04-01"},
        ),
        409,
        "INVALID_DATE_RANGE",
    )
    ended = api.post(f"/api/patients/coverages/{cov['id']}/end")
    assert ended.json()["active"] is False
    assert api.get(f"/api/patients/{pat.pk}/coverages").json() == []
    assert len(api.get(f"/api/patients/{pat.pk}/coverages?include_inactive=true").json()) == 1


def test_coverage_needs_permission(client_as, clerk) -> None:
    pat = _register(clerk, full_name_en="Omer Salih")
    api = client_as("doctor")
    response = api.post(f"/api/patients/{pat.pk}/coverages", {"payer_id": b.payer().pk})
    _error(response, 403, "PERMISSION_DENIED")


def test_balance_is_for_cashiers_only(client_as, clerk) -> None:
    pat = _register(clerk, full_name_en="Omer Salih")
    reception = client_as("receptionist")
    _error(reception.get(f"/api/patients/{pat.pk}/balance"), 403, "PERMISSION_DENIED")
    cashier = client_as("cashier")
    body = cashier.get(f"/api/patients/{pat.pk}/balance").json()
    assert body == {
        "credit": "0.00",
        "spendable": "0.00",
        "pending": "0.00",
        "outstanding": "0.00",
        "net": "0.00",
        "invoices": [],
    }
