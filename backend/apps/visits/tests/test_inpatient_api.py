"""``/api/visits/inpatient`` contract (FEATURES 10.5): bed board, admit, transfer, nightly
charges, discharge and bed status; the roles that may not act (403 sweep); error codes."""

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
from apps.visits.models import Admission, Bed, BedCharge, BedStay
from conftest import ApiClient

pytestmark = pytest.mark.django_db

URL = "/api/visits/inpatient"


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _client(make_user: Any, role: str) -> ApiClient:
    user = make_user(roles=[role])
    api = ApiClient()
    assert api.login(user.username).status_code == 200
    return api


def _beds(n: int = 2) -> list[Bed]:
    dept = b.department()
    room = Room.objects.create(
        department=dept, code=f"WA{b.n()}", name_ar="عنبر أ", name_en="Ward A"
    )
    svc = fin.priced("bed", "30000.00", department=dept)
    return [
        Bed.objects.create(
            code=f"{room.code}-{i}",
            name_ar=f"سرير {i}",
            name_en=f"Bed {i}",
            room=room,
            bed_service=svc,
        )
        for i in range(1, n + 1)
    ]


def test_nurse_admits_transfers_charges_and_discharges(make_user: Any) -> None:
    beds = _beds(2)
    doctor = b.doctor()
    patient = b.patient(full_name_en="Fatima Omer")
    nurse = _client(make_user, "nurse")

    r = nurse.post(
        f"{URL}/admissions",
        {
            "patient_id": patient.pk,
            "bed_id": beds[0].pk,
            "doctor_id": doctor.pk,
            "diagnosis": "Malaria",
        },
    )
    assert r.status_code == 201, r.content
    adm = r.json()
    assert adm["status"] == "admitted"
    assert adm["bed"]["id"] == beds[0].pk
    assert adm["patient"]["full_name_en"] == "Fatima Omer"
    assert adm["diagnosis"] == "Malaria"
    assert adm["nights_charged"] == 0

    board = nurse.get(f"{URL}/board").json()
    ward = next(w for w in board["wards"] if w["room"] and w["room"]["id"] == beds[0].room_id)
    first, second = ward["beds"]
    assert first["status"] == "occupied"
    assert first["occupant"]["number"] == adm["number"]
    assert first["occupant"]["nights_at_discharge"] == 1
    assert second["occupant"] is None
    assert "price" not in str(board)
    assert "30000" not in str(board)

    r = nurse.post(f"{URL}/admissions/{adm['id']}/transfer", {"bed_id": beds[0].pk})
    assert r.status_code == 409
    assert r.json()["code"] == "SAME_BED"
    r = nurse.post(f"{URL}/admissions/{adm['id']}/transfer", {"bed_id": beds[1].pk})
    assert r.status_code == 200, r.content
    assert r.json()["bed"]["id"] == beds[1].pk

    # A night passes: the charge run adds it as a line waiting for the cashier.
    yesterday = timezone.now() - timedelta(days=1)
    Admission.objects.filter(pk=adm["id"]).update(admitted_at=yesterday)
    first_stay = BedStay.objects.filter(admission_id=adm["id"]).order_by("started_at").first()
    assert first_stay is not None
    BedStay.objects.filter(pk=first_stay.pk).update(started_at=yesterday)
    r = nurse.post(f"{URL}/charge-due", {})
    assert r.status_code == 200
    assert r.json() == {"charged": 1, "admissions": 1}
    assert nurse.post(f"{URL}/charge-due", {}).json() == {"charged": 0, "admissions": 0}
    line = BedCharge.objects.get(admission_id=adm["id"]).service_line
    assert (line.billing_status, line.fulfilment_status) == ("unbilled", "performed")

    r = nurse.post(f"{URL}/admissions/{adm['id']}/discharge", {"summary": "Improved"})
    assert r.status_code == 200, r.content
    out = r.json()
    assert out["status"] == "discharged"
    assert out["discharge_summary"] == "Improved"
    assert out["discharged_by"] is not None
    assert out["nights_charged"] == 1
    r = nurse.post(f"{URL}/admissions/{adm['id']}/discharge", {})
    assert r.status_code == 409
    assert r.json()["code"] == "NOT_ADMITTED"
    assert nurse.get(f"{URL}/admissions/{adm['id']}").json()["status"] == "discharged"


def test_admit_on_an_existing_visit_and_errors(make_user: Any) -> None:
    beds = _beds(2)
    doctor = b.doctor()
    patient = b.patient()
    visit = b.visit(patient, department=b.department())
    nurse = _client(make_user, "nurse")
    body = {"patient_id": patient.pk, "visit_id": visit.pk, "bed_id": beds[0].pk}
    r = nurse.post(f"{URL}/admissions", {**body, "doctor_id": doctor.pk})
    assert r.status_code == 201
    assert r.json()["visit_id"] == visit.pk
    r = nurse.post(
        f"{URL}/admissions",
        {"patient_id": b.patient().pk, "bed_id": beds[0].pk, "doctor_id": doctor.pk},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "BED_NOT_AVAILABLE"
    r = nurse.post(
        f"{URL}/admissions",
        {
            "patient_id": b.patient().pk,
            "visit_id": visit.pk,
            "bed_id": beds[1].pk,
            "doctor_id": doctor.pk,
        },
    )
    assert r.json()["code"] == "VISIT_PATIENT_MISMATCH"
    r = nurse.post(
        f"{URL}/admissions",
        {"patient_id": 999999, "bed_id": beds[1].pk, "doctor_id": doctor.pk},
    )
    assert r.status_code == 404


def test_bed_status(make_user: Any) -> None:
    beds = _beds(1)
    nurse = _client(make_user, "nurse")
    r = nurse.post(f"{URL}/beds/{beds[0].pk}/status", {"status": "maintenance"})
    assert r.status_code == 200
    beds[0].refresh_from_db()
    assert beds[0].status == "maintenance"
    assert nurse.post(f"{URL}/beds/{beds[0].pk}/status", {"status": "occupied"}).status_code == 422
    nurse.post(f"{URL}/beds/{beds[0].pk}/status", {"status": "available"})
    vs.admit_patient(b.patient(), bed=beds[0], doctor=b.doctor(), actor=fin.staff("nurse"))
    r = nurse.post(f"{URL}/beds/{beds[0].pk}/status", {"status": "maintenance"})
    assert r.status_code == 409
    assert r.json()["code"] == "BED_OCCUPIED"


#: (role, operations it must be refused). Board reads need visits.view, which nearly every
#: role has; the writes are the guarded part.
FORBIDDEN = {
    "cashier": {"admit", "transfer", "discharge", "status", "charge"},
    "pharmacist": {"admit", "transfer", "discharge", "status", "charge"},
    "lab_tech": {"admit", "transfer", "discharge", "status", "charge"},
    "accountant": {"admit", "transfer", "discharge", "status", "charge"},
    "receptionist": {"transfer", "discharge", "status", "charge"},
    "doctor": {"transfer", "status", "charge"},
}


@pytest.mark.parametrize("role", sorted(FORBIDDEN))
def test_roles_without_the_permission_get_403(make_user: Any, role: str) -> None:
    beds = _beds(2)
    adm = vs.admit_patient(b.patient(), bed=beds[0], doctor=b.doctor(), actor=fin.staff("nurse"))
    api = _client(make_user, role)
    calls = {
        "admit": (
            f"{URL}/admissions",
            {"patient_id": b.patient().pk, "bed_id": beds[1].pk, "doctor_id": b.doctor().pk},
        ),
        "transfer": (f"{URL}/admissions/{adm.pk}/transfer", {"bed_id": beds[1].pk}),
        "discharge": (f"{URL}/admissions/{adm.pk}/discharge", {}),
        "status": (f"{URL}/beds/{beds[1].pk}/status", {"status": "maintenance"}),
        "charge": (f"{URL}/charge-due", {}),
    }
    for name in FORBIDDEN[role]:
        path, body = calls[name]
        r = api.post(path, body)
        assert r.status_code == 403, (role, name, r.status_code)
        assert r.json()["code"] == "PERMISSION_DENIED"
    adm.refresh_from_db()
    assert adm.status == "admitted"
    assert Admission.objects.count() == 1
    assert not ServiceLine.objects.filter(order_source="bed_charge").exists()


def test_charge_command(make_user: Any) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    beds = _beds(1)
    nurse = fin.staff("nurse", username="ward_nurse")
    fin.staff("cashier", username="till")
    vs.admit_patient(
        b.patient(),
        bed=beds[0],
        doctor=b.doctor(),
        actor=nurse,
        at=timezone.now() - timedelta(days=2),
    )
    with pytest.raises(CommandError):
        call_command("charge_bed_nights", "--as", "till")
    call_command("charge_bed_nights", "--as", "ward_nurse")
    assert BedCharge.objects.count() == 2
