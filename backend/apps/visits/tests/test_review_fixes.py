"""Regression tests for the Phase 1 review: inpatient nights under a documented exception,
one open admission per patient, coverage changes, payer contracts and audit context.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.visits import services as vs
from apps.visits.models import Admission, Bed
from domain.errors import DomainError

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def clerk(make_user):
    return make_user(roles=["receptionist"])


@pytest.fixture
def ward():
    svc = b.service(kind="bed")
    return [
        Bed.objects.create(code=f"RV{i}", name_ar=f"سرير {i}", name_en=f"Bed {i}", bed_service=svc)
        for i in (1, 2)
    ]


def test_bed_nights_are_performed_under_the_admissions_authorization(clerk, ward) -> None:
    """Review: bed nights were plain requested lines, never performed and with no
    perform-first authorization, so every leakage report listed them."""
    doctor = b.doctor()
    v = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    adm = vs.admit(
        v, doctor=doctor, bed=ward[0], actor=clerk, at=timezone.now() - timedelta(days=2)
    )
    assert adm.patient_id == v.patient_id
    assert adm.authorization is not None
    assert adm.authorization.authorized_by == clerk
    assert adm.authorization.reason_note.startswith(f"inpatient stay {adm.number}")
    charges = vs.charge_bed_days(adm, actor=clerk)
    assert charges
    for charge in charges:
        line = ServiceLine.objects.get(pk=charge.service_line_id)
        assert (line.billing_status, line.fulfilment_status) == ("unbilled", "performed")
        assert line.authorization_id == adm.authorization_id
        assert orders.line_state(line) == "performed"
    assert not orders.worklist("bed").exists()


def test_a_patient_holds_one_open_admission(clerk, ward) -> None:
    doctor = b.doctor()
    patient = b.patient()
    v1 = vs.create_visit(patient=patient, actor=clerk, department=b.department())
    v2 = vs.create_visit(patient=patient, actor=clerk, department=b.department())
    vs.admit(v1, doctor=doctor, bed=ward[0], actor=clerk)
    with pytest.raises(DomainError) as exc:
        vs.admit(v2, doctor=doctor, bed=ward[1], actor=clerk)
    assert exc.value.code == "PATIENT_ALREADY_ADMITTED"
    # The database refuses it too (the race the review found).
    b.db_rejects(
        lambda: Admission.objects.create(
            number=f"ADM-X-{b.n()}",
            visit=v2,
            patient=patient,
            admitting_doctor=doctor,
            admitted_at=timezone.now(),
            admitted_by=clerk,
        ),
        "visits_admission_one_open_per_patient",
    )


def test_change_coverage_moves_unbilled_lines_to_the_new_payer(clerk) -> None:
    payer = b.payer(requires_card_number=False)
    patient = b.patient()
    coverage = patients.add_coverage(patient, payer=payer, actor=clerk)
    v = vs.create_visit(
        patient=patient, actor=clerk, department=b.department(), use_default_coverage=False
    )
    (line,) = orders.create_service_lines(v, [{"service": b.service("lab")}], clerk)
    assert line.payer_id is None
    with pytest.raises(DomainError) as exc:
        vs.change_coverage(v, actor=clerk, note=" ", coverage=coverage)
    assert exc.value.code == "REASON_REQUIRED"
    vs.change_coverage(v, actor=clerk, note="card shown after ordering", coverage=coverage)
    line.refresh_from_db()
    v.refresh_from_db()
    assert (v.payer_id, line.payer_id) == (payer.pk, payer.pk)


def test_expired_payer_contract_is_refused_for_a_visit(clerk) -> None:
    payer = b.payer(
        requires_card_number=False,
        contract_start=timezone.localdate() - timedelta(days=400),
        contract_end=timezone.localdate() - timedelta(days=1),
    )
    patient = b.patient()
    coverage = patients.add_coverage(patient, payer=payer, actor=clerk)
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, department=b.department(), coverage=coverage)
    assert exc.value.code == "PAYER_CONTRACT_EXPIRED"


def test_converting_a_contact_booking_records_who_did_it(clerk) -> None:
    """Review: the patient re-assignment of a booking was written outside any audit context."""
    doctor = b.doctor()
    appt = vs.book_appointment(
        doctor=doctor,
        starts_at=timezone.now() + timedelta(hours=2),
        actor=clerk,
        contact_name="Sara",
        contact_phone="0912000000",
    )
    patient = b.patient()
    vs.convert_appointment(appt, actor=clerk, patient=patient)
    events = django_apps.get_model("visits", "AppointmentEvent")
    event = events.objects.filter(pgh_obj=appt, patient=patient).order_by("pgh_id").first()
    assert event is not None
    assert event.pgh_context is not None
    assert event.pgh_context.metadata["user"] == clerk.pk
