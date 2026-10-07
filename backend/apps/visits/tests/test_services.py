"""Visit services: visits, follow-up rule, queue, appointments, minimal inpatient."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.patients import services as ps
from apps.visits import services as vs
from apps.visits.models import (
    Admission,
    Appointment,
    Bed,
    BedCharge,
    BedStay,
    DoctorSchedule,
    QueueEntry,
    Visit,
)
from domain.errors import DomainError

pytestmark = pytest.mark.django_db

FIN_READY = importlib.util.find_spec("apps.orders.services") is not None
awaiting_fin = pytest.mark.xfail(
    not FIN_READY, reason="awaiting financial engine", raises=ModuleNotFoundError, strict=True
)


@pytest.fixture
def clerk(make_user):
    return make_user(roles=["receptionist"])


@pytest.fixture
def doctor():
    """A doctor without a consultation fee service (creating visits needs no orders call)."""
    return b.doctor()


@pytest.fixture
def fee_doctor():
    d = b.doctor()
    d.consultation_service = b.service(kind="consultation")
    d.save()
    return d


@pytest.fixture
def patient():
    return b.patient(full_name_ar="سلمى علي", sex="female")


def _days_ago(visit: Visit, days: int) -> Visit:
    Visit.objects.filter(pk=visit.pk).update(created_at=timezone.now() - timedelta(days=days))
    visit.refresh_from_db()
    return visit


def _fee_line(visit: Visit, **extra) -> ServiceLine:
    svc = b.service(kind="consultation")
    return b.service_line(visit, svc, order_source="consultation_fee", **extra)


def _settle(line: ServiceLine) -> None:
    now = timezone.now()
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced", invoiced_at=now)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="settled", settled_at=now)


# --- visits ---------------------------------------------------------------------------------


def test_create_visit_numbers_queues_and_defaults_department(clerk, doctor, patient) -> None:
    v1 = vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    v2 = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    assert v1.number.startswith("VIS-")
    assert v1.number != v2.number
    assert v1.department == doctor.department
    assert v1.created_by == clerk
    tokens = list(QueueEntry.objects.order_by("token_no").values_list("visit_id", "token_no"))
    assert tokens == [(v1.pk, 1), (v2.pk, 2)]
    assert not ServiceLine.objects.filter(visit=v1).exists()


def test_emergency_visit_has_priority(clerk, doctor, patient) -> None:
    normal = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    urgent = vs.create_visit(patient=patient, actor=clerk, doctor=doctor, visit_type="emergency")
    order = [e.visit_id for e in vs.queue(department=doctor.department)]
    assert order == [urgent.pk, normal.pk]


def test_create_visit_validation(clerk, doctor, patient) -> None:
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk)
    assert exc.value.code == "DEPARTMENT_REQUIRED"
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, doctor=doctor, visit_type="bogus")
    assert exc.value.code == "INVALID_VISIT_TYPE"
    doctor.active = False
    doctor.save()
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    assert exc.value.code == "DOCTOR_INACTIVE"
    other = b.patient()
    patient.merged_into = other
    patient.is_active = False
    patient.save()
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, department=b.department())
    assert exc.value.code == "PATIENT_MERGED"


def test_visit_takes_default_coverage(clerk, doctor, patient) -> None:
    insurer = b.payer()
    cov = ps.add_coverage(patient, payer=insurer, actor=clerk, card_number="CARD-9")
    v = vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    assert (v.payer, v.coverage, v.card_number) == (insurer, cov, "CARD-9")
    cash = vs.create_visit(
        patient=patient, actor=clerk, department=b.department(), use_default_coverage=False
    )
    assert cash.payer is None
    assert cash.coverage is None


def test_invalid_coverage_is_refused(clerk, doctor, patient) -> None:
    insurer = b.payer(requires_card_number=False)
    expired = ps.add_coverage(
        patient,
        payer=insurer,
        actor=clerk,
        valid_from=date(2025, 1, 1),
        valid_to=timezone.localdate() - timedelta(days=1),
    )
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, doctor=doctor, coverage=expired)
    assert exc.value.code == "COVERAGE_INVALID"
    foreign = ps.add_coverage(b.patient(), payer=insurer, actor=clerk)
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=patient, actor=clerk, doctor=doctor, coverage=foreign)
    assert exc.value.code == "COVERAGE_INVALID"


# --- follow-up rule -------------------------------------------------------------------------


def test_follow_up_within_window(clerk, doctor, patient) -> None:
    policy = Policy.load()
    policy.follow_up_window_days = 7
    policy.follow_up_discount_percent = Decimal(50)
    policy.save()
    original = _days_ago(vs.create_visit(patient=patient, actor=clerk, doctor=doctor), 3)
    follow = vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    assert follow.visit_type == "follow_up"
    assert follow.follow_up_of == original
    assert vs.follow_up_discount_percent(follow) == Decimal(50)
    assert vs.follow_up_discount_percent(original) == Decimal(0)
    # A second follow-up still points at the original; the window counts from it.
    _days_ago(follow, 1)
    again = vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    assert again.follow_up_of == original
    _days_ago(original, 8)
    late = vs.create_visit(patient=patient, actor=clerk, doctor=doctor)
    assert late.visit_type == "new"
    assert late.follow_up_of is None


def test_follow_up_ignores_other_doctors_and_cancelled_visits(clerk, doctor, patient) -> None:
    other_doctor = b.doctor()
    _days_ago(vs.create_visit(patient=patient, actor=clerk, doctor=other_doctor), 1)
    assert vs.create_visit(patient=patient, actor=clerk, doctor=doctor).follow_up_of is None
    p2 = b.patient()
    first = vs.create_visit(patient=p2, actor=clerk, doctor=doctor)
    vs.cancel_visit(first, actor=clerk, reason_code="REGISTRATION_ERROR")
    assert vs.create_visit(patient=p2, actor=clerk, doctor=doctor).follow_up_of is None


def test_free_follow_up_has_no_consultation_line(clerk, fee_doctor, patient) -> None:
    policy = Policy.load()
    policy.follow_up_discount_percent = Decimal(100)
    policy.save()
    original = b.visit(patient, doctor=fee_doctor, department=fee_doctor.department)
    follow = vs.create_visit(patient=patient, actor=clerk, doctor=fee_doctor)
    assert follow.follow_up_of == original
    assert not ServiceLine.objects.filter(visit=follow).exists()
    # No fee due: the follow-up is ready for the doctor at once.
    assert [e.visit_id for e in vs.queue(department=fee_doctor.department)] == [follow.pk]


def test_follow_up_counts_merged_files(clerk, doctor, make_user) -> None:
    survivor, duplicate = b.patient(), b.patient()
    _days_ago(vs.create_visit(patient=duplicate, actor=clerk, doctor=doctor), 2)
    ps.merge_patients(duplicate, survivor, actor=make_user(roles=["manager"]), reason_note="dup")
    assert vs.create_visit(patient=survivor, actor=clerk, doctor=doctor).visit_type == "follow_up"


@awaiting_fin
def test_create_visit_adds_requested_consultation_line(clerk, fee_doctor, patient) -> None:
    v = vs.create_visit(patient=patient, actor=clerk, doctor=fee_doctor)
    line = ServiceLine.objects.get(visit=v)
    assert line.service == fee_doctor.consultation_service
    assert line.order_source == "consultation_fee"
    assert (line.billing_status, line.fulfilment_status) == ("unbilled", "pending")


# --- queue ----------------------------------------------------------------------------------


def test_queue_shows_only_paid_or_authorized_visits(clerk, doctor) -> None:
    unpaid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    paid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    authorized = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    _fee_line(unpaid)
    _settle(_fee_line(paid))
    from apps.orders.models import PerformAuthorization

    auth = PerformAuthorization.objects.create(
        visit=authorized,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=clerk,
        authorized_at=timezone.now(),
    )
    _fee_line(authorized, authorization=auth)
    dept = doctor.department
    assert [e.visit_id for e in vs.queue(department=dept)] == [paid.pk, authorized.pk]
    everyone = vs.queue(department=dept, include_not_ready=True)
    assert [(e.visit_id, e.blocked) for e in everyone] == [  # type: ignore[attr-defined]
        (unpaid.pk, True),
        (paid.pk, False),
        (authorized.pk, False),
    ]
    entry = QueueEntry.objects.get(visit=unpaid)
    with pytest.raises(DomainError) as exc:
        vs.call_patient(entry, actor=clerk)
    assert exc.value.code == "QUEUE_NOT_READY"
    # A revoked authorization no longer opens the door.
    PerformAuthorization.objects.filter(pk=auth.pk).update(
        revoked_at=timezone.now(), revoked_by=clerk
    )
    assert [e.visit_id for e in vs.queue(department=dept)] == [paid.pk]


def test_queue_transitions(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    entry = QueueEntry.objects.get(visit=v)
    entry = vs.call_patient(entry, actor=clerk)
    assert entry.status == "called"
    assert entry.called_by == clerk
    assert entry.called_at
    entry = vs.mark_no_show(entry, actor=clerk)
    entry = vs.requeue(entry, actor=clerk)
    assert entry.status == "waiting"
    entry = vs.start_consultation(entry, actor=clerk)
    assert entry.started_at
    with pytest.raises(DomainError) as exc:
        vs.cancel_queue_entry(entry, actor=clerk)
    assert exc.value.code == "QUEUE_TRANSITION_INVALID"
    entry = vs.finish_consultation(entry, actor=clerk)
    assert entry.status == "done"
    assert entry.done_at
    with pytest.raises(DomainError):
        vs.requeue(entry, actor=clerk)
    # Enqueuing twice is refused while the visit is active in the queue.
    v2 = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    with pytest.raises(DomainError) as exc:
        vs.enqueue(v2, actor=clerk)
    assert exc.value.code == "ALREADY_QUEUED"


def test_tokens_restart_per_department_and_day(clerk, doctor) -> None:
    other = b.doctor()
    a = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    c = vs.create_visit(patient=b.patient(), actor=clerk, doctor=other)
    assert QueueEntry.objects.get(visit=a).token_no == 1
    assert QueueEntry.objects.get(visit=c).token_no == 1
    tomorrow = timezone.localdate() + timedelta(days=1)
    QueueEntry.objects.filter(visit=a).update(status="done")
    later = vs.enqueue(a, actor=clerk, on=tomorrow)
    assert later.token_no == 1


@awaiting_fin
def test_finish_consultation_performs_the_fee_line(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    line = _fee_line(v)
    _settle(line)
    entry = vs.start_consultation(QueueEntry.objects.get(visit=v), actor=clerk)
    vs.finish_consultation(entry, actor=clerk)
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert line.performed_by == clerk


# --- visit close and cancel -----------------------------------------------------------------


def test_close_and_cancel_visit(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    closed = vs.close_visit(v, actor=clerk)
    assert closed.status == "closed"
    assert closed.closed_by == clerk
    with pytest.raises(DomainError) as exc:
        vs.close_visit(v, actor=clerk)
    assert exc.value.code == "VISIT_NOT_OPEN"

    v2 = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    with pytest.raises(DomainError) as exc:
        vs.cancel_visit(v2, actor=clerk, reason_code="NOPE")
    assert exc.value.code == "REASON_UNKNOWN"
    with pytest.raises(DomainError) as exc:
        vs.cancel_visit(v2, actor=clerk, reason_code="OTHER")
    assert exc.value.code == "REASON_NOTE_REQUIRED"
    cancelled = vs.cancel_visit(v2, actor=clerk, reason_code="OTHER", note="left early")
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_reason is not None
    assert cancelled.cancel_reason.code == "OTHER"
    assert cancelled.cancelled_by == clerk
    assert cancelled.cancel_note == "left early"
    assert QueueEntry.objects.get(visit=v2).status == "cancelled"


def test_visit_with_performed_work_cannot_be_cancelled(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    line = _fee_line(v)
    _settle(line)
    ServiceLine.objects.filter(pk=line.pk).update(
        fulfilment_status="performed", performed_at=timezone.now(), performed_by=clerk
    )
    with pytest.raises(DomainError) as exc:
        vs.cancel_visit(v, actor=clerk, reason_code="PATIENT_LEFT")
    assert exc.value.code == "VISIT_HAS_PERFORMED_WORK"


@awaiting_fin
def test_cancel_visit_cancels_open_lines(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    line = _fee_line(v)
    vs.cancel_visit(v, actor=clerk, reason_code="PATIENT_LEFT")
    line.refresh_from_db()
    assert line.fulfilment_status == "cancelled"
    assert line.cancel_reason is not None
    assert line.cancel_reason.code == "PATIENT_REFUSED"


# --- appointments ---------------------------------------------------------------------------


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    day = timezone.localdate() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.get_current_timezone())


def test_book_and_conflict(clerk, doctor, patient) -> None:
    a = vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, patient=patient)
    assert a.ends_at - a.starts_at == timedelta(minutes=15)
    assert a.department == doctor.department
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(
            doctor=doctor, starts_at=_at(1, 9, 10), actor=clerk, contact_name="Caller"
        )
    assert exc.value.code == "APPOINTMENT_CONFLICT"
    # Back to back is fine; another doctor at the same time is fine.
    vs.book_appointment(doctor=doctor, starts_at=_at(1, 9, 15), actor=clerk, contact_name="X")
    vs.book_appointment(doctor=b.doctor(), starts_at=_at(1, 9), actor=clerk, contact_name="Y")
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=_at(1, 10), actor=clerk)
    assert exc.value.code == "PATIENT_OR_CONTACT_REQUIRED"
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=_at(-1, 10), actor=clerk, contact_name="Late")
    assert exc.value.code == "APPOINTMENT_IN_PAST"
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(
            doctor=doctor,
            starts_at=_at(2, 10),
            ends_at=_at(2, 9),
            actor=clerk,
            contact_name="Z",
        )
    assert exc.value.code == "INVALID_SLOT"


def test_schedule_limits_and_slots(clerk, doctor) -> None:
    day = timezone.localdate() + timedelta(days=1)
    DoctorSchedule.objects.create(
        doctor=doctor,
        weekday=day.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_minutes=20,
    )
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=_at(1, 11), actor=clerk, contact_name="A")
    assert exc.value.code == "OUTSIDE_SCHEDULE"
    booked = vs.book_appointment(
        doctor=doctor, starts_at=_at(1, 9, 20), actor=clerk, contact_name="A"
    )
    assert booked.ends_at == _at(1, 9, 40)  # the schedule's slot length
    slots = vs.available_slots(doctor, day)
    assert slots == [(_at(1, 9), _at(1, 9, 20)), (_at(1, 9, 40), _at(1, 10))]
    assert vs.available_slots(doctor, day + timedelta(days=1)) == []


def test_reschedule_cancel_no_show_and_convert(clerk, doctor, patient) -> None:
    a = vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, patient=patient)
    moved = vs.reschedule_appointment(a, starts_at=_at(1, 11), actor=clerk)
    a.refresh_from_db()
    assert a.status == "rescheduled"
    assert moved.rescheduled_from == a
    assert moved.ends_at - moved.starts_at == timedelta(minutes=15)
    # The old slot is free again.
    vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, contact_name="New")
    with pytest.raises(DomainError) as exc:
        vs.cancel_appointment(a, actor=clerk)
    assert exc.value.code == "APPOINTMENT_NOT_BOOKED"

    visit = vs.convert_appointment(moved, actor=clerk)
    moved.refresh_from_db()
    assert moved.status == "arrived"
    assert visit.appointment == moved
    assert visit.patient == patient

    caller = vs.book_appointment(doctor=doctor, starts_at=_at(2, 9), actor=clerk, contact_name="C")
    with pytest.raises(DomainError) as exc:
        vs.convert_appointment(caller, actor=clerk)
    assert exc.value.code == "PATIENT_REQUIRED"
    newcomer = b.patient()
    visit2 = vs.convert_appointment(caller, actor=clerk, patient=newcomer)
    caller.refresh_from_db()
    assert caller.patient == newcomer
    assert visit2.patient == newcomer

    c = vs.book_appointment(doctor=doctor, starts_at=_at(3, 9), actor=clerk, contact_name="D")
    c = vs.cancel_appointment(c, actor=clerk, note="called to cancel")
    assert c.status == "cancelled"
    assert c.cancelled_by == clerk
    n = vs.book_appointment(doctor=doctor, starts_at=_at(3, 9), actor=clerk, contact_name="E")
    assert vs.mark_appointment_no_show(n, actor=clerk).status == "no_show"
    assert Appointment.objects.filter(status="booked").count() == 1


# --- inpatient ------------------------------------------------------------------------------


def test_bed_charge_dates() -> None:
    d0 = date(2026, 10, 1)
    assert vs.bed_charge_dates(d0, through=d0) == []
    assert vs.bed_charge_dates(d0, through=d0 + timedelta(days=2)) == [d0, d0 + timedelta(days=1)]
    # Same-day discharge is one day; otherwise the discharge date is not charged.
    assert vs.bed_charge_dates(d0, through=d0, discharged_on=d0) == [d0]
    assert vs.bed_charge_dates(
        d0, through=d0 + timedelta(days=3), discharged_on=d0 + timedelta(days=3)
    ) == [
        d0,
        d0 + timedelta(days=1),
        d0 + timedelta(days=2),
    ]


@pytest.fixture
def ward():
    svc = b.service(kind="bed")
    return [
        Bed.objects.create(code=f"BED{i}", name_ar=f"سرير {i}", name_en=f"Bed {i}", bed_service=svc)
        for i in (1, 2)
    ]


def test_admit_and_transfer(clerk, doctor, ward) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    adm = vs.admit(v, doctor=doctor, bed=ward[0], actor=clerk, diagnosis="pneumonia")
    assert adm.number.startswith("ADM-")
    ward[0].refresh_from_db()
    assert ward[0].status == "occupied"
    with pytest.raises(DomainError) as exc:
        vs.admit(v, doctor=doctor, bed=ward[1], actor=clerk)
    assert exc.value.code == "ALREADY_ADMITTED"
    other = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    with pytest.raises(DomainError) as exc:
        vs.admit(other, doctor=doctor, bed=ward[0], actor=clerk)
    assert exc.value.code == "BED_NOT_AVAILABLE"
    stay = vs.transfer_bed(adm, bed=ward[1], actor=clerk, at=timezone.now() + timedelta(hours=1))
    assert stay.bed == ward[1]
    ward[0].refresh_from_db()
    assert ward[0].status == "available"
    assert BedStay.objects.filter(admission=adm, ended_at__isnull=True).count() == 1
    with pytest.raises(DomainError) as exc:
        vs.transfer_bed(adm, bed=ward[1], actor=clerk)
    assert exc.value.code == "SAME_BED"
    # Nothing charged yet: nights are charged in arrears.
    assert not BedCharge.objects.filter(admission=adm).exists()


def test_bed_service_must_be_a_bed_day(clerk, doctor) -> None:
    wrong = Bed.objects.create(code="BX", name_ar="س", name_en="B", bed_service=b.service("lab"))
    v = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    with pytest.raises(DomainError) as exc:
        vs.admit(v, doctor=doctor, bed=wrong, actor=clerk)
    assert exc.value.code == "BED_SERVICE_INVALID"


@awaiting_fin
def test_bed_nights_are_charged_once_and_discharge_closes(clerk, doctor, ward) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    admitted_at = timezone.now() - timedelta(days=3)
    adm = vs.admit(v, doctor=doctor, bed=ward[0], actor=clerk, at=admitted_at)
    first = vs.charge_bed_days(adm, actor=clerk)
    assert [c.charge_date for c in first] == vs.bed_charge_dates(
        timezone.localdate(admitted_at), through=timezone.localdate()
    )
    assert vs.charge_bed_days(adm, actor=clerk) == []  # idempotent
    line = first[0].service_line
    assert line.order_source == "bed_charge"
    assert line.service == ward[0].bed_service
    vs.discharge(adm, actor=clerk, summary="improved")
    adm.refresh_from_db()
    v.refresh_from_db()
    assert adm.status == "discharged"
    assert v.status == "closed"
    assert BedCharge.objects.filter(admission=adm).count() == 3
    ward[0].refresh_from_db()
    assert ward[0].status == "available"


def test_admission_is_required_for_discharge(clerk, doctor, ward) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    adm = vs.admit(v, doctor=doctor, bed=ward[0], actor=clerk)
    Admission.objects.filter(pk=adm.pk).update(status="cancelled")
    with pytest.raises(DomainError) as exc:
        vs.discharge(adm, actor=clerk)
    assert exc.value.code == "NOT_ADMITTED"
