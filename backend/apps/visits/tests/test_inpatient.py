"""Minimal inpatient for the nursing screens (FEATURES 10.5): admit (on an open visit or a
new inpatient visit), the bed board, transfer, nightly bed charges that reach the invoice,
discharge, bed status, and two admissions or transfers racing for one bed."""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.core.models import Room
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.payments.tests import fin
from apps.visits import services as vs
from apps.visits.models import Admission, Bed, BedCharge, BedStay, Visit
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def nurse():
    return fin.staff("nurse")


@pytest.fixture
def doctor():
    return b.doctor()


def _ward(code: str = "W", beds: int = 2, *, price: str = "30000.00") -> list[Bed]:
    dept = b.department()
    room = Room.objects.create(
        department=dept, code=f"{code}{b.n()}", name_ar="عنبر", name_en="Ward"
    )
    svc = fin.priced("bed", price, department=dept)
    return [
        Bed.objects.create(
            code=f"{room.code}-{i}",
            name_ar=f"سرير {i}",
            name_en=f"Bed {i}",
            room=room,
            bed_service=svc,
        )
        for i in range(1, beds + 1)
    ]


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


# --- admit ----------------------------------------------------------------------------------


def test_admit_without_a_visit_opens_an_inpatient_visit(nurse, doctor) -> None:
    beds = _ward()
    patient = b.patient()
    adm = vs.admit_patient(patient, bed=beds[0], doctor=doctor, actor=nurse, diagnosis="  CAP ")
    visit = Visit.objects.get(pk=adm.visit_id)
    assert visit.visit_type == "inpatient"
    assert visit.status == "open"
    assert visit.patient == patient
    room = beds[0].room
    assert room is not None
    assert visit.department == room.department
    assert visit.doctor == doctor
    # An inpatient visit has no consultation fee line and no queue token.
    assert not ServiceLine.objects.filter(visit=visit).exists()
    assert adm.admitted_by == nurse
    assert adm.admitting_doctor == doctor
    assert adm.admission_diagnosis == "CAP"
    # The perform-first exception the nights are given under is documented (invariant 1, 4).
    assert adm.authorization is not None
    assert adm.authorization.authorized_by == nurse
    beds[0].refresh_from_db()
    assert beds[0].status == "occupied"


def test_admit_on_an_open_visit_of_the_patient(nurse, doctor) -> None:
    beds = _ward()
    patient = b.patient()
    visit = b.visit(patient, department=b.department())
    adm = vs.admit_patient(patient, visit=visit, bed=beds[0], doctor=doctor, actor=nurse)
    assert adm.visit_id == visit.pk
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(b.patient(), visit=visit, bed=beds[1], doctor=doctor, actor=nurse)
    assert _code(exc) == "VISIT_PATIENT_MISMATCH"


def test_admit_refusals(nurse, doctor) -> None:
    beds = _ward(beds=3)
    patient = b.patient()
    vs.admit_patient(patient, bed=beds[0], doctor=doctor, actor=nurse)
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(patient, bed=beds[1], doctor=doctor, actor=nurse)
    assert _code(exc) == "PATIENT_ALREADY_ADMITTED"
    # A refused admission leaves no inpatient visit behind.
    assert Visit.objects.filter(patient=patient).count() == 1
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(b.patient(), bed=beds[0], doctor=doctor, actor=nurse)
    assert _code(exc) == "BED_NOT_AVAILABLE"
    vs.set_bed_status(beds[2], status="maintenance", actor=nurse)
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(b.patient(), bed=beds[2], doctor=doctor, actor=nurse)
    assert _code(exc) == "BED_NOT_AVAILABLE"
    sale = b.visit(b.patient(), visit_type="pharmacy_sale")
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(sale.patient, visit=sale, bed=beds[1], doctor=doctor, actor=nurse)
    assert _code(exc) == "VISIT_NOT_ADMITTABLE"
    inactive = _ward(beds=1)[0]
    Bed.objects.filter(pk=inactive.pk).update(active=False)
    with pytest.raises(DomainError) as exc:
        vs.admit_patient(b.patient(), bed=inactive, doctor=doctor, actor=nurse)
    assert _code(exc) == "BED_NOT_AVAILABLE"


# --- bed status -----------------------------------------------------------------------------


def test_bed_status_toggles_only_free_beds(nurse, doctor) -> None:
    beds = _ward()
    assert vs.set_bed_status(beds[0], status="maintenance", actor=nurse).status == "maintenance"
    assert vs.set_bed_status(beds[0], status="available", actor=nurse).status == "available"
    vs.admit_patient(b.patient(), bed=beds[1], doctor=doctor, actor=nurse)
    with pytest.raises(DomainError) as exc:
        vs.set_bed_status(beds[1], status="maintenance", actor=nurse)
    assert _code(exc) == "BED_OCCUPIED"
    with pytest.raises(DomainError) as exc:
        vs.set_bed_status(beds[0], status="occupied", actor=nurse)
    assert _code(exc) == "INVALID_BED_STATUS"


# --- the board ------------------------------------------------------------------------------


def test_board_groups_beds_by_ward_with_occupants_and_nights(nurse, doctor) -> None:
    beds = _ward(beds=3)
    vs.set_bed_status(beds[2], status="maintenance", actor=nurse)
    patient = b.patient(full_name_en="Huda Ahmed")
    adm = vs.admit_patient(
        patient,
        bed=beds[0],
        doctor=doctor,
        actor=nurse,
        at=timezone.now() - timedelta(days=2),
    )
    board = vs.bed_board()
    ward = next(w for w in board.wards if w.room is not None and w.room == beds[0].room)
    assert [v.bed.pk for v in ward.beds] == [bd.pk for bd in beds]
    occupied = ward.beds[0]
    assert occupied.admission is not None
    assert occupied.admission.pk == adm.pk
    assert occupied.nights_charged == 0
    assert occupied.nights_due == 2
    # Discharging today charges the two passed nights (today is not a night yet).
    assert occupied.nights_at_discharge == 2
    assert ward.beds[1].admission is None
    assert ward.beds[2].bed.status == "maintenance"
    assert board.nights_due >= 2
    counts = board.counts
    assert counts["occupied"] >= 1
    assert counts["maintenance"] >= 1
    assert counts["available"] >= 1


def test_same_day_admission_charges_one_night_at_discharge(nurse, doctor) -> None:
    beds = _ward()
    vs.admit_patient(b.patient(), bed=beds[0], doctor=doctor, actor=nurse)
    view = next(v for w in vs.bed_board().wards for v in w.beds if v.bed.pk == beds[0].pk)
    assert (view.nights_due, view.nights_at_discharge) == (0, 1)


# --- charges --------------------------------------------------------------------------------


def test_due_nights_are_charged_once_and_reach_the_invoice(nurse, doctor) -> None:
    beds = _ward(price="30000.00")
    adm = vs.admit_patient(
        b.patient(),
        bed=beds[0],
        doctor=doctor,
        actor=nurse,
        at=timezone.now() - timedelta(days=2),
    )
    created = vs.charge_due_bed_nights(actor=nurse)
    assert [c.admission_id for c in created] == [adm.pk, adm.pk]
    assert vs.charge_due_bed_nights(actor=nurse) == []  # idempotent
    lines = list(ServiceLine.objects.filter(visit=adm.visit).order_by("id"))
    assert len(lines) == 2
    for ln in lines:
        # Given under the admission's authorization, performed, waiting for the cashier.
        assert (ln.billing_status, ln.fulfilment_status) == ("unbilled", "performed")
        assert ln.authorization_id == adm.authorization_id
        assert ln.order_source == "bed_charge"
    cashier = fin.staff("cashier")
    inv = fin.invoice(adm.visit, cashier)
    assert inv.status == "approved"
    assert inv.patient_total == D("60000.00")
    assert {ln.billing_status for ln in ServiceLine.objects.filter(visit=adm.visit)} == {"invoiced"}


def test_transfer_moves_the_occupant_and_charges_the_new_bed_from_then(nurse, doctor) -> None:
    ward = _ward(beds=1, price="30000.00")
    private = _ward(beds=1, price="60000.00")
    adm = vs.admit_patient(
        b.patient(),
        bed=ward[0],
        doctor=doctor,
        actor=nurse,
        at=timezone.now() - timedelta(days=2),
    )
    vs.transfer_bed(adm, bed=private[0], actor=nurse, at=timezone.now() - timedelta(days=1))
    ward[0].refresh_from_db()
    private[0].refresh_from_db()
    assert (ward[0].status, private[0].status) == ("available", "occupied")
    vs.charge_due_bed_nights(actor=nurse)
    services = [
        c.service_line.service_id
        for c in BedCharge.objects.filter(admission=adm).order_by("charge_date")
    ]
    assert services == [ward[0].bed_service_id, private[0].bed_service_id]
    with pytest.raises(DomainError) as exc:
        vs.transfer_bed(adm, bed=private[0], actor=nurse)
    assert _code(exc) == "SAME_BED"


def test_discharge_charges_the_rest_frees_the_bed_and_closes_the_visit(nurse, doctor) -> None:
    beds = _ward()
    adm = vs.admit_patient(
        b.patient(),
        bed=beds[0],
        doctor=doctor,
        actor=nurse,
        at=timezone.now() - timedelta(days=1),
    )
    out = vs.discharge(adm, actor=nurse, summary="improved")
    assert out.status == "discharged"
    assert out.discharged_by == nurse
    assert BedCharge.objects.filter(admission=adm).count() == 1
    beds[0].refresh_from_db()
    assert beds[0].status == "available"
    assert Visit.objects.get(pk=adm.visit_id).status == "closed"
    assert not BedStay.objects.filter(admission=adm, ended_at__isnull=True).exists()
    with pytest.raises(DomainError) as exc:
        vs.discharge(adm, actor=nurse)
    assert _code(exc) == "NOT_ADMITTED"
    with pytest.raises(DomainError) as exc:
        vs.transfer_bed(adm, bed=beds[1], actor=nurse)
    assert _code(exc) == "NOT_ADMITTED"


# --- concurrency ----------------------------------------------------------------------------


def _race(actions) -> list[str]:
    results: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(actions))

    def run(action) -> None:
        try:
            barrier.wait(timeout=10)
            action()
            outcome = "ok"
        except DomainError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=run, args=(a,)) for a in actions]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return sorted(results)


@pytest.mark.django_db(transaction=True)
def test_two_admissions_racing_for_one_bed_admit_one() -> None:
    fin.seed()
    doctor = b.doctor()
    nurses = [fin.staff("nurse") for _ in range(3)]
    bed = _ward(beds=1)[0]
    patients = [b.patient() for _ in nurses]
    results = _race(
        [
            (lambda n=n, p=p: vs.admit_patient(p, bed=bed, doctor=doctor, actor=n))
            for n, p in zip(nurses, patients, strict=True)
        ]
    )
    assert results == ["BED_NOT_AVAILABLE"] * 2 + ["ok"], results
    assert Admission.objects.filter(status="admitted").count() == 1
    assert BedStay.objects.filter(bed=bed, ended_at__isnull=True).count() == 1
    # The losers left no inpatient visit behind.
    assert Visit.objects.filter(visit_type="inpatient").count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_transfers_racing_for_one_bed_move_one() -> None:
    fin.seed()
    doctor = b.doctor()
    nurse = fin.staff("nurse")
    beds = _ward(beds=3)
    earlier = timezone.now() - timedelta(hours=2)
    first = vs.admit_patient(b.patient(), bed=beds[0], doctor=doctor, actor=nurse, at=earlier)
    second = vs.admit_patient(b.patient(), bed=beds[1], doctor=doctor, actor=nurse, at=earlier)
    target = beds[2]
    n1, n2 = fin.staff("nurse"), fin.staff("nurse")
    results = _race(
        [
            lambda: vs.transfer_bed(first, bed=target, actor=n1),
            lambda: vs.transfer_bed(second, bed=target, actor=n2),
        ]
    )
    assert results == ["BED_NOT_AVAILABLE", "ok"], results
    assert BedStay.objects.filter(bed=target, ended_at__isnull=True).count() == 1
    target.refresh_from_db()
    assert target.status == "occupied"
