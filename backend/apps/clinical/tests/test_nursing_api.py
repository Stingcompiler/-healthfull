"""``/api/clinical/nursing`` contract (FEATURES 3.4, 10.3): the nurse's visits, the nursing
chart, nursing notes; vitals a nurse records reach the doctor's workspace; 403 sweep."""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.tests import builders as b
from apps.payments.tests import fin
from conftest import ApiClient

pytestmark = pytest.mark.django_db

URL = "/api/clinical/nursing"
FORBIDDEN_ROLES = [
    "receptionist",
    "cashier",
    "cashier_supervisor",
    "pharmacist",
    "lab_tech",
    "lab_supervisor",
    "accountant",
    "manager",
]


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _client(make_user: Any, role: str) -> ApiClient:
    user = make_user(roles=[role])
    api = ApiClient()
    assert api.login(user.username).status_code == 200
    return api


def test_nurse_finds_todays_visit_records_vitals_and_doctor_sees_them(make_user: Any) -> None:
    visit = b.visit(b.patient(full_name_en="Rania Kamal"), department=b.department())
    nurse = _client(make_user, "nurse")

    rows = nurse.get(f"{URL}/visits?q=rania").json()
    assert [r["visit"]["id"] for r in rows] == [visit.pk]
    assert rows[0]["vitals_count"] == 0
    assert rows[0]["admission"] is None

    r = nurse.post(
        f"/api/clinical/visits/{visit.pk}/vitals",
        {"temperature_c": "38.2", "bp_systolic": 120, "bp_diastolic": 80, "pulse_bpm": 96},
    )
    assert r.status_code == 201, r.content
    assert nurse.get(f"{URL}/visits?q=rania").json()[0]["vitals_count"] == 1

    doctor = _client(make_user, "doctor")
    ws = doctor.get(f"/api/clinical/visits/{visit.pk}/workspace").json()
    assert [v["temperature_c"] for v in ws["vitals"]] == ["38.2"]
    assert ws["vitals"][0]["pulse_bpm"] == 96


def test_chart_and_notes(make_user: Any) -> None:
    visit = b.visit(department=b.department())
    nurse = _client(make_user, "nurse")
    r = nurse.post(f"{URL}/visits/{visit.pk}/notes", {"text": "Calm, eating well"})
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "general"
    r = nurse.post(f"{URL}/visits/{visit.pk}/notes", {"text": "   ", "kind": "handover"})
    assert r.status_code == 409
    assert r.json()["code"] == "NOTE_EMPTY"
    assert nurse.post(f"{URL}/visits/{visit.pk}/notes", {"text": ""}).status_code == 422
    chart = nurse.get(f"{URL}/visits/{visit.pk}").json()
    assert [n["text"] for n in chart["notes"]] == ["Calm, eating well"]
    assert chart["notes"][0]["author"] is not None
    assert chart["vitals"] == []
    assert chart["procedures"] == []
    assert chart["admission"] is None
    assert nurse.get(f"{URL}/visits/999999").status_code == 404
    # A doctor reads the chart but writes no nursing notes.
    doctor = _client(make_user, "doctor")
    assert doctor.get(f"{URL}/visits/{visit.pk}").status_code == 200
    r = doctor.post(f"{URL}/visits/{visit.pk}/notes", {"text": "x"})
    assert r.status_code == 403


@pytest.mark.parametrize("role", FORBIDDEN_ROLES)
def test_roles_without_clinical_access_get_403(make_user: Any, role: str) -> None:
    visit = b.visit()
    api = _client(make_user, role)
    for method, path, body in (
        ("GET", f"{URL}/visits", None),
        ("GET", f"{URL}/visits/{visit.pk}", None),
        ("POST", f"{URL}/visits/{visit.pk}/notes", {"text": "x"}),
        ("POST", f"/api/clinical/visits/{visit.pk}/vitals", {"pulse_bpm": 80}),
    ):
        r = api.request(method, path, body)
        assert r.status_code == 403, (role, path, r.status_code)
        assert r.json()["code"] == "PERMISSION_DENIED"
