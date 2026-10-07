"""Visits, queue, appointments and minimal inpatient (FEATURES 2, 10.5)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.visits.models import Admission, Appointment, Bed, BedCharge, BedStay, QueueEntry, Visit

pytestmark = pytest.mark.django_db


def test_visit_cancellation_is_documented() -> None:
    v = b.visit()
    b.db_rejects(
        lambda: Visit.objects.filter(pk=v.pk).update(status="cancelled"),
        "visits_visit_cancel_documented",
    )
    Visit.objects.filter(pk=v.pk).update(
        status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=b.user(),
        cancel_reason=b.reason("visit_cancel"),
    )


def test_visit_coverage_needs_a_payer_and_closing_a_time() -> None:
    from apps.patients.models import PatientCoverage

    v = b.visit()
    cov = PatientCoverage.objects.create(patient=v.patient, payer=b.payer())
    b.db_rejects(
        lambda: Visit.objects.filter(pk=v.pk).update(coverage=cov),
        "visits_visit_coverage_has_payer",
    )
    b.db_rejects(
        lambda: Visit.objects.filter(pk=v.pk).update(status="closed"),
        "visits_visit_closed_has_time",
    )


def test_queue_tokens_and_one_active_entry_per_visit() -> None:
    v = b.visit()
    dept = b.department()
    today = timezone.localdate()
    QueueEntry.objects.create(visit=v, department=dept, queue_date=today, token_no=1)
    with pytest.raises(IntegrityError, match="visits_queue_token_unique"), transaction.atomic():
        QueueEntry.objects.create(visit=b.visit(), department=dept, queue_date=today, token_no=1)
    with (
        pytest.raises(IntegrityError, match="visits_queue_one_active_per_visit"),
        transaction.atomic(),
    ):
        QueueEntry.objects.create(visit=v, department=dept, queue_date=today, token_no=2)
    QueueEntry.objects.filter(visit=v).update(status="done")
    QueueEntry.objects.create(visit=v, department=dept, queue_date=today, token_no=3)


def test_appointment_slot_and_person() -> None:
    doc = b.doctor()
    start = timezone.now()
    common = {"doctor": doc, "department": doc.department, "created_by": b.user()}
    with (
        pytest.raises(IntegrityError, match="visits_appointment_positive_slot"),
        transaction.atomic(),
    ):
        Appointment.objects.create(contact_name="Sara", starts_at=start, ends_at=start, **common)
    with pytest.raises(IntegrityError, match="visits_appointment_has_person"), transaction.atomic():
        Appointment.objects.create(starts_at=start, ends_at=start + timedelta(minutes=15), **common)


def test_bed_is_occupied_by_one_stay_and_charged_once_a_day() -> None:
    bed_service = b.service(kind="bed")
    bed = Bed.objects.create(code="B1", name_ar="سرير", name_en="Bed 1", bed_service=bed_service)
    doc = b.doctor()

    def admit() -> Admission:
        v = b.visit(visit_type="inpatient")
        return Admission.objects.create(
            number=f"ADM-{b.n()}",
            visit=v,
            patient=v.patient,
            admitting_doctor=doc,
            admitted_at=timezone.now(),
            admitted_by=b.user(),
        )

    first = admit()
    stay = BedStay.objects.create(
        admission=first, bed=bed, started_at=timezone.now(), created_by=b.user()
    )
    with pytest.raises(IntegrityError, match="visits_bedstay_bed_free"), transaction.atomic():
        BedStay.objects.create(
            admission=admit(), bed=bed, started_at=timezone.now(), created_by=b.user()
        )
    today = timezone.localdate()
    BedCharge.objects.create(
        admission=first,
        bed_stay=stay,
        charge_date=today,
        service_line=b.service_line(first.visit, bed_service),
    )
    with pytest.raises(IntegrityError, match="visits_bedcharge_once_per_day"), transaction.atomic():
        BedCharge.objects.create(
            admission=first,
            bed_stay=stay,
            charge_date=today,
            service_line=b.service_line(first.visit, bed_service),
        )
    b.db_rejects(
        lambda: Admission.objects.filter(pk=first.pk).update(status="discharged"),
        "visits_admission_discharge_documented",
    )
