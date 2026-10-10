"""``POST /api/visits/inpatient/admissions/{id}/cancel`` (ADR 0018): the nurse cancels an
admission made in error with a second person's credentials; error codes; the roles that may
not (403 sweep)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.core.models import Room
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.payments.tests import fin
from apps.visits import services as vs
from apps.visits.models import Admission, Bed
from conftest import TEST_PASSWORD, ApiClient

pytestmark = pytest.mark.django_db

URL = "/api/visits/inpatient"


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _client(user: Any) -> ApiClient:
    api = ApiClient()
    assert api.login(user.username).status_code == 200
    return api


def _admission(days: int = 0) -> Admission:
    dept = b.department()
    room = Room.objects.create(department=dept, code=f"WC{b.n()}", name_ar="ع", name_en="W")
    bed = Bed.objects.create(
        code=f"{room.code}-1",
        name_ar="س",
        name_en="B",
        room=room,
        bed_service=fin.priced("bed", "30000.00", department=dept),
    )
    nurse = fin.staff("nurse")
    adm = vs.admit_patient(
        b.patient(),
        bed=bed,
        doctor=b.doctor(),
        actor=nurse,
        at=timezone.now() - timedelta(days=days),
    )
    if days:
        vs.charge_bed_days(adm, actor=nurse)
    return adm


def test_nurse_cancels_with_a_managers_credentials(make_user: Any) -> None:
    adm = _admission(days=1)
    nurse = make_user(roles=["nurse"])
    manager = make_user(roles=["manager"])
    board = _client(nurse).get(f"{URL}/board").json()
    occupant = next(
        bed["occupant"]
        for ward in board["wards"]
        for bed in ward["beds"]
        if bed["occupant"] and bed["occupant"]["admission_id"] == adm.pk
    )
    assert occupant["nights_invoiced"] == 0
    r = _client(nurse).post(
        f"{URL}/admissions/{adm.pk}/cancel",
        {
            "reason_code": "WRONG_PATIENT",
            "note": "admitted on the wrong file",
            "approver": {"username": manager.username, "password": TEST_PASSWORD},
        },
    )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "WRONG_PATIENT"
    assert body["cancelled_by"]["id"] == nurse.pk
    assert body["cancel_approved_by"]["id"] == manager.pk
    assert body["cancel_note"] == "admitted on the wrong file"
    assert body["cancelled_at"] is not None
    assert "price" not in str(body)
    night = ServiceLine.objects.get(bed_charge__admission=adm)
    assert night.fulfilment_status == "cancelled"


def test_error_codes(make_user: Any) -> None:
    adm = _admission()
    nurse = make_user(roles=["nurse"])
    other_nurse = make_user(roles=["nurse"])
    api = _client(nurse)
    path = f"{URL}/admissions/{adm.pk}/cancel"

    def post(body: dict[str, Any]) -> tuple[int, str]:
        r = api.post(path, {"reason_code": "WRONG_PATIENT", **body})
        return r.status_code, r.json()["code"]

    assert post({}) == (409, "SECOND_APPROVER_REQUIRED")
    own = {"username": nurse.username, "password": TEST_PASSWORD}
    assert post({"approver": own}) == (409, "SECOND_APPROVER_REQUIRED")
    wrong = {"username": other_nurse.username, "password": "not-the-password"}
    assert post({"approver": wrong}) == (409, "APPROVER_INVALID")
    peer = {"username": other_nurse.username, "password": TEST_PASSWORD}
    assert post({"approver": peer}) == (409, "APPROVER_NOT_PERMITTED")
    manager = make_user(roles=["manager"])
    ok = {"username": manager.username, "password": TEST_PASSWORD}
    assert post({"approver": ok, "reason_code": "OTHER"}) == (409, "REASON_NOTE_REQUIRED")
    assert post({"approver": ok, "reason_code": "PATIENT_LEFT"}) == (409, "REASON_UNKNOWN")
    assert api.post(f"{URL}/admissions/999999/cancel", {"reason_code": "X"}).status_code == 404
    # The nurse's own session survives a wrong approver password (409, never 401).
    assert api.get(f"{URL}/board").status_code == 200
    adm.refresh_from_db()
    assert adm.status == "admitted"


def test_invoiced_nights_answer_409_with_the_count(make_user: Any) -> None:
    adm = _admission(days=2)
    fin.invoice(adm.visit, fin.staff("cashier"))
    nurse = make_user(roles=["nurse"])
    manager = make_user(roles=["manager"])
    r = _client(nurse).post(
        f"{URL}/admissions/{adm.pk}/cancel",
        {
            "reason_code": "WRONG_PATIENT",
            "approver": {"username": manager.username, "password": TEST_PASSWORD},
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == "ADMISSION_NIGHTS_INVOICED"
    assert r.json()["details"]["count"] == 2


@pytest.mark.parametrize(
    "role",
    [
        "receptionist",
        "doctor",
        "cashier",
        "cashier_supervisor",
        "pharmacist",
        "lab_tech",
        "lab_supervisor",
        "accountant",
    ],
)
def test_roles_without_the_permission_get_403(make_user: Any, role: str) -> None:
    adm = _admission()
    manager = make_user(roles=["manager"])
    r = _client(make_user(roles=[role])).post(
        f"{URL}/admissions/{adm.pk}/cancel",
        {
            "reason_code": "WRONG_PATIENT",
            "approver": {"username": manager.username, "password": TEST_PASSWORD},
        },
    )
    assert r.status_code == 403, (role, r.status_code)
    assert r.json()["code"] == "PERMISSION_DENIED"
    adm.refresh_from_db()
    assert adm.status == "admitted"
