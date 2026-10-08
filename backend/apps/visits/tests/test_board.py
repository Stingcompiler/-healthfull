"""Reception board services (wave a): call next, waiting-room display, token slip,
appointment day view and edits, visit lists and the enriched timeline."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from apps.core.models import CenterProfile
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.patients import services as ps
from apps.visits import services as vs
from apps.visits.models import Appointment, DoctorSchedule, QueueEntry, Visit
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk(make_user):
    return make_user(roles=["receptionist"])


@pytest.fixture
def doctor():
    return b.doctor()


def _fee_line(visit: Visit) -> ServiceLine:
    return b.service_line(visit, b.service(kind="consultation"), order_source="consultation_fee")


def _settle(line: ServiceLine) -> None:
    inv = b.draft_invoice(line.visit)
    b.invoice_line(inv, line=line)
    b.approve_invoice(inv)
    now = timezone.now()
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced", invoiced_at=now)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="settled", settled_at=now)


def _entry(visit: Visit) -> QueueEntry:
    return QueueEntry.objects.get(visit=visit)


# --- call next ------------------------------------------------------------------------------


def test_call_next_calls_the_first_paid_waiting_token(clerk, doctor) -> None:
    unpaid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    _fee_line(unpaid)
    paid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    _settle(_fee_line(paid))
    later = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)  # no fee due

    called = vs.call_next(department=doctor.department, actor=clerk)
    assert called.visit_id == paid.pk
    assert called.status == "called"
    assert called.called_by == clerk
    # The unpaid token keeps its place but is skipped again.
    assert vs.call_next(department=doctor.department, actor=clerk).visit_id == later.pk
    with pytest.raises(DomainError) as exc:
        vs.call_next(department=doctor.department, actor=clerk)
    assert exc.value.code == "QUEUE_EMPTY"
    assert _entry(unpaid).status == "waiting"


def test_call_next_prefers_emergencies_and_respects_the_doctor(clerk, doctor) -> None:
    colleague = b.doctor(doctor.department)
    mine = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    theirs = vs.create_visit(patient=b.patient(), actor=clerk, doctor=colleague)
    urgent = vs.create_visit(
        patient=b.patient(), actor=clerk, doctor=colleague, visit_type="emergency"
    )
    assert vs.call_next(department=doctor.department, actor=clerk).visit_id == urgent.pk
    assert (
        vs.call_next(department=doctor.department, doctor=doctor, actor=clerk).visit_id == mine.pk
    )
    with pytest.raises(DomainError) as exc:
        vs.call_next(department=doctor.department, doctor=doctor, actor=clerk)
    assert exc.value.code == "QUEUE_EMPTY"
    assert vs.call_next(department=doctor.department, actor=clerk).visit_id == theirs.pk


# --- waiting-room display -------------------------------------------------------------------


def test_waiting_room_shows_abbreviated_names_of_ready_tokens(clerk, doctor) -> None:
    first = vs.create_visit(
        patient=b.patient(full_name_ar="أحمد محمد علي", full_name_en="Ahmed Mohamed Ali"),
        actor=clerk,
        doctor=doctor,
    )
    second = vs.create_visit(
        patient=b.patient(full_name_ar="فاطمة الزين", full_name_en=""),
        actor=clerk,
        doctor=doctor,
    )
    unpaid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    _fee_line(unpaid)
    vs.call_patient(_entry(first), actor=clerk)

    room = vs.waiting_room(department=doctor.department)
    assert [(e.token_no, e.name_ar, e.name_en, e.status) for e in room.serving] == [
        (1, "أحمد م.", "Ahmed M.", "called")
    ]
    assert [(e.token_no, e.name_ar, e.name_en) for e in room.waiting] == [
        (2, "فاطمة ز.", "فاطمة ز.")
    ]
    # The unpaid token is not announced; finished tokens leave the screen.
    assert unpaid.pk not in [e.visit_id for e in room.waiting + room.serving]
    vs.finish_consultation(vs.start_consultation(_entry(first), actor=clerk), actor=clerk)
    room = vs.waiting_room(department=doctor.department)
    assert room.serving == []
    assert [e.visit_id for e in room.waiting] == [second.pk]


def test_waiting_room_of_every_department(clerk, doctor) -> None:
    other = b.doctor()
    vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    vs.create_visit(patient=b.patient(), actor=clerk, doctor=other)
    room = vs.waiting_room()
    assert {e.department.pk for e in room.waiting} == {doctor.department_id, other.department_id}


# --- token slip -----------------------------------------------------------------------------


def test_token_slip_counts_tokens_ahead(clerk, doctor) -> None:
    center = CenterProfile.load()
    center.name_ar, center.name_en = "مركز النيل", "Nile Center"
    center.save()
    a = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    bb = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    c = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    vs.call_patient(_entry(a), actor=clerk)
    slip = vs.token_slip(_entry(c))
    assert slip.entry.token_no == 3
    assert slip.ahead == 2
    assert slip.center.name_en == "Nile Center"
    assert vs.token_slip(_entry(bb)).ahead == 1
    urgent = vs.create_visit(
        patient=b.patient(), actor=clerk, doctor=doctor, visit_type="emergency"
    )
    assert vs.token_slip(_entry(urgent)).ahead == 0
    assert vs.token_slip(_entry(c)).ahead == 3


# --- visit lists and view -------------------------------------------------------------------


def test_visit_list_filters_and_includes_merged_files(clerk, doctor, make_user) -> None:
    survivor, duplicate = b.patient(), b.patient()
    old = vs.create_visit(patient=duplicate, actor=clerk, doctor=doctor)
    Visit.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    today = vs.create_visit(patient=survivor, actor=clerk, department=b.department())
    ps.merge_patients(duplicate, survivor, actor=make_user(roles=["manager"]), reason_note="dup")

    assert [v.pk for v in vs.visit_list(patient=survivor)] == [today.pk, old.pk]
    assert [v.pk for v in vs.visit_list(on=timezone.localdate(), patient=survivor)] == [today.pk]
    assert [v.pk for v in vs.visit_list(department=doctor.department)] == [old.pk]
    assert [v.pk for v in vs.visit_list(doctor=doctor)] == [old.pk]
    vs.cancel_visit(today, actor=clerk, reason_code="REGISTRATION_ERROR")
    assert [v.pk for v in vs.visit_list(patient=survivor, status="open")] == [old.pk]


def test_visit_view_lists_lines_with_states(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    line = _fee_line(v)
    view = vs.visit_view(v)
    assert view.visit == v
    assert [(lv.line.pk, lv.state) for lv in view.lines] == [(line.pk, "requested")]
    assert view.queue_entry is not None
    assert view.queue_entry.token_no == 1
    assert view.queue_ready is False
    _settle(line)
    view = vs.visit_view(v)
    assert [lv.state for lv in view.lines] == ["paid"]
    assert view.queue_ready is True


def test_timeline_view_names_services_and_actors(clerk, doctor) -> None:
    v = vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor)
    line = _fee_line(v)
    items = vs.timeline_view(v, include_financial=False)
    kinds = [i.event.kind for i in items]
    assert kinds[0] == "visit_created"
    assert items[0].actor == clerk
    ordered = next(i for i in items if i.event.kind == "line_ordered")
    assert ordered.event.detail["service_code"] == line.service.code
    assert ordered.event.detail["service_name_en"] == line.service.name_en


def test_visit_options_list_active_reference_data(clerk, doctor) -> None:
    inactive = b.doctor()
    inactive.active = False
    inactive.save()
    options = vs.visit_options()
    assert doctor in options.doctors
    assert inactive not in options.doctors
    assert doctor.department in options.departments
    assert all(r.category == "visit_cancel" and r.active for r in options.cancel_reasons)
    assert {r.code for r in options.cancel_reasons} >= {"REGISTRATION_ERROR", "OTHER"}


# --- appointments ---------------------------------------------------------------------------


def _at(days: int, hour: int, minute: int = 0) -> datetime:
    day = timezone.localdate() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.get_current_timezone())


def test_appointment_day_merges_free_slots_and_bookings(clerk, doctor) -> None:
    day = timezone.localdate() + timedelta(days=1)
    DoctorSchedule.objects.create(
        doctor=doctor, weekday=day.weekday(), start_time=time(9), end_time=time(10), slot_minutes=20
    )
    patient = b.patient()
    booked = vs.book_appointment(
        doctor=doctor, starts_at=_at(1, 9, 20), actor=clerk, patient=patient
    )
    gone = vs.book_appointment(
        doctor=doctor, starts_at=_at(1, 9, 40), actor=clerk, contact_name="X"
    )
    vs.cancel_appointment(gone, actor=clerk, note="called to cancel")

    agenda = vs.appointment_day(doctor, day)
    assert agenda.works is True
    rows = [(i.starts_at, i.appointment.pk if i.appointment else None) for i in agenda.items]
    assert rows == [
        (_at(1, 9), None),
        (_at(1, 9, 20), booked.pk),
        (_at(1, 9, 40), None),
        (_at(1, 9, 40), gone.pk),
    ]
    off = vs.appointment_day(doctor, day + timedelta(days=1))
    assert off.works is False
    assert off.items == []


def test_appointment_day_hides_past_free_slots(clerk, doctor) -> None:
    today = timezone.localdate()
    DoctorSchedule.objects.create(
        doctor=doctor, weekday=today.weekday(), start_time=time(0), end_time=time(23, 59)
    )
    agenda = vs.appointment_day(doctor, today)
    now = timezone.now()
    assert agenda.items
    assert all(i.ends_at > now for i in agenda.items if i.appointment is None)


def test_cancel_appointment_needs_a_reason(clerk, doctor) -> None:
    appt = vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, contact_name="A")
    with pytest.raises(DomainError) as exc:
        vs.cancel_appointment(appt, actor=clerk, note="  ")
    assert exc.value.code == "REASON_REQUIRED"
    assert Appointment.objects.get(pk=appt.pk).status == "booked"
    done = vs.cancel_appointment(appt, actor=clerk, note="patient travelled")
    assert (done.status, done.cancel_note, done.cancelled_by) == (
        "cancelled",
        "patient travelled",
        clerk,
    )


def test_update_appointment_details(clerk, doctor) -> None:
    appt = vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, contact_name="A")
    updated = vs.update_appointment(
        appt, actor=clerk, notes="  bring old results ", contact_phone="0912345678"
    )
    assert (updated.notes, updated.contact_phone, updated.contact_name) == (
        "bring old results",
        "0912345678",
        "A",
    )
    with pytest.raises(DomainError) as exc:
        vs.update_appointment(appt, actor=clerk, contact_name=" ")
    assert exc.value.code == "PATIENT_OR_CONTACT_REQUIRED"
    vs.cancel_appointment(appt, actor=clerk, note="x")
    with pytest.raises(DomainError) as exc:
        vs.update_appointment(appt, actor=clerk, notes="late")
    assert exc.value.code == "APPOINTMENT_NOT_BOOKED"


def test_upcoming_appointments_of_a_person(clerk, doctor) -> None:
    patient = b.patient()
    first = vs.book_appointment(doctor=doctor, starts_at=_at(2, 9), actor=clerk, patient=patient)
    second = vs.book_appointment(doctor=doctor, starts_at=_at(1, 9), actor=clerk, patient=patient)
    vs.book_appointment(doctor=doctor, starts_at=_at(3, 9), actor=clerk, contact_name="Other")
    assert [a.pk for a in vs.upcoming_appointments(patient)] == [second.pk, first.pk]
