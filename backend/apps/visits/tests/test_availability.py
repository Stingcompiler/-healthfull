"""Availability hardening (public site Phase 3, ADR 0029 C, E): online requests hold their
slot until they expire, doctor time off, and the database no-overlap backstop."""

from __future__ import annotations

import importlib
import threading
from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.visits import services as vs
from apps.visits.models import Appointment, AppointmentStatus, DoctorSchedule, DoctorTimeOff
from conftest import ApiClient
from domain.errors import DomainError

pytestmark = pytest.mark.django_db

migration = importlib.import_module(
    "apps.visits.migrations.0005_online_requests_time_off_no_overlap"
)


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    day = timezone.localdate() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.get_current_timezone())


@pytest.fixture
def clerk(make_user: Any) -> Any:
    return make_user(roles=["receptionist"])


@pytest.fixture
def doctor() -> Any:
    """A doctor working 9:00-12:00 every day in 15-minute slots."""
    d = b.doctor()
    for weekday in range(7):
        DoctorSchedule.objects.create(
            doctor=d, weekday=weekday, start_time=time(9), end_time=time(12), slot_minutes=15
        )
    return d


def _request(doctor: Any, clerk: Any, start: datetime, expires: datetime) -> Appointment:
    return vs.book_appointment(
        doctor=doctor,
        starts_at=start,
        actor=clerk,
        contact_name="caller",
        source="portal",
        expires_at=expires,
    )


# --- requests hold the slot ------------------------------------------------------------------


def test_a_request_holds_its_slot_until_it_expires(doctor: Any, clerk: Any) -> None:
    start = _at(2, 9)
    req = _request(doctor, clerk, start, timezone.now() + timedelta(hours=1))
    assert req.status == AppointmentStatus.REQUESTED
    assert start not in [s for s, _ in vs.available_slots(doctor, start.date())]
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=start, actor=clerk, contact_name="other")
    assert exc.value.code == "APPOINTMENT_CONFLICT"


def test_an_expired_request_frees_its_slot_lazily_under_the_doctor_lock(
    doctor: Any, clerk: Any
) -> None:
    start = _at(2, 9, 15)
    req = _request(doctor, clerk, start, timezone.now() + timedelta(hours=1))
    Appointment.objects.filter(pk=req.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    # The reads ignore it before any sweep ...
    assert start in [s for s, _ in vs.available_slots(doctor, start.date())]
    # ... and booking the slot expires it first, so the exclusion constraint is satisfied.
    booked = vs.book_appointment(doctor=doctor, starts_at=start, actor=clerk, contact_name="x")
    assert booked.status == AppointmentStatus.BOOKED
    req.refresh_from_db()
    assert req.status == AppointmentStatus.CANCELLED
    assert req.cancel_reason is not None
    assert req.cancel_reason.code == "ONLINE_REQUEST_EXPIRED"
    assert req.cancelled_by is not None


def test_maintenance_sweep_expires_due_requests(doctor: Any, clerk: Any) -> None:
    due = _request(doctor, clerk, _at(3, 9), timezone.now() + timedelta(hours=1))
    live = _request(doctor, clerk, _at(3, 10), timezone.now() + timedelta(hours=5))
    Appointment.objects.filter(pk=due.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert vs.expire_requests() == 1
    due.refresh_from_db()
    live.refresh_from_db()
    assert due.status == AppointmentStatus.CANCELLED
    assert live.status == AppointmentStatus.REQUESTED
    assert vs.expire_requests() == 0


def test_approve_records_who_and_when(doctor: Any, clerk: Any) -> None:
    req = _request(doctor, clerk, _at(2, 10), timezone.now() + timedelta(hours=1))
    approved = vs.approve_online_booking(req, actor=clerk)
    assert approved.status == AppointmentStatus.BOOKED
    assert approved.approved_by == clerk
    assert approved.approved_at is not None
    with pytest.raises(DomainError) as exc:
        vs.approve_online_booking(req, actor=clerk)
    assert exc.value.code == "APPOINTMENT_NOT_REQUESTED"


def test_an_expired_request_cannot_be_approved_even_before_the_sweep(
    doctor: Any, clerk: Any
) -> None:
    req = _request(doctor, clerk, _at(2, 10, 30), timezone.now() + timedelta(hours=1))
    Appointment.objects.filter(pk=req.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(DomainError) as exc:
        vs.approve_online_booking(req, actor=clerk)
    assert exc.value.code == "ONLINE_REQUEST_EXPIRED"


def test_reject_records_reason_note_actor_time(doctor: Any, clerk: Any) -> None:
    req = _request(doctor, clerk, _at(2, 11), timezone.now() + timedelta(hours=1))
    rejected = vs.reject_online_booking(req, actor=clerk, note="doctor is fully booked")
    assert rejected.status == AppointmentStatus.CANCELLED
    assert rejected.cancel_reason is not None
    assert rejected.cancel_reason.code == "ONLINE_REJECTED"
    assert rejected.cancel_note == "doctor is fully booked"
    assert rejected.cancelled_by == clerk
    assert rejected.cancelled_at is not None
    booked = vs.book_appointment(
        doctor=doctor, starts_at=_at(2, 11, 15), actor=clerk, contact_name="y"
    )
    with pytest.raises(DomainError) as exc:
        vs.reject_online_booking(booked, actor=clerk)
    assert exc.value.code == "APPOINTMENT_NOT_REQUESTED"


def test_refused_edges_from_requested(doctor: Any, clerk: Any) -> None:
    req = _request(doctor, clerk, _at(4, 9), timezone.now() + timedelta(hours=1))
    for action in (
        lambda: vs.mark_appointment_no_show(req, actor=clerk),
        lambda: vs.reschedule_appointment(req, starts_at=_at(4, 10), actor=clerk),
    ):
        with pytest.raises(DomainError) as exc:
            action()
        assert exc.value.code == "APPOINTMENT_NOT_BOOKED"
    with pytest.raises(DomainError) as exc:
        vs.create_visit(patient=b.patient(), actor=clerk, doctor=doctor, appointment=req)
    assert exc.value.code == "APPOINTMENT_NOT_BOOKED"
    # Cancelling a request (by the booker or on their behalf) is allowed.
    vs.cancel_appointment(req, actor=clerk, reason_code="PATIENT_REQUEST")


def test_the_request_needs_an_expiry_in_the_database(doctor: Any, clerk: Any) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Appointment.objects.create(
            doctor=doctor,
            department=doctor.department,
            contact_name="z",
            starts_at=_at(5, 9),
            ends_at=_at(5, 9, 15),
            status="requested",
            created_by=clerk,
        )


# --- time off --------------------------------------------------------------------------------


def test_time_off_removes_slots_and_refuses_bookings(doctor: Any, clerk: Any) -> None:
    held = vs.book_appointment(doctor=doctor, starts_at=_at(3, 10), actor=clerk, contact_name="a")
    view = vs.add_time_off(
        clerk, doctor.pk, starts_at=_at(3, 9, 30), ends_at=_at(3, 11), reason_en="Conference"
    )
    assert [a.pk for a in view.appointments] == [held.pk]  # kept, reported, never cancelled
    held.refresh_from_db()
    assert held.status == AppointmentStatus.BOOKED
    starts = [s for s, _ in vs.available_slots(doctor, _at(3, 9).date())]
    assert _at(3, 9) in starts
    assert _at(3, 9, 15) in starts
    assert not any(_at(3, 9, 30) <= s < _at(3, 11) for s in starts)
    assert _at(3, 11) in starts
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=_at(3, 10, 30), actor=clerk, contact_name="b")
    assert exc.value.code == "DOCTOR_TIME_OFF"
    vs.remove_time_off(clerk, view.time_off.pk)
    assert _at(3, 10, 30) in [s for s, _ in vs.available_slots(doctor, _at(3, 9).date())]


def test_time_off_rules(doctor: Any, clerk: Any) -> None:
    def add(start: datetime, end: datetime, reason: str = "Leave") -> Any:
        return vs.add_time_off(clerk, doctor.pk, starts_at=start, ends_at=end, reason_en=reason)

    add(_at(6, 9), _at(6, 12))
    cases: list[tuple[datetime, datetime, str, str]] = [
        (_at(6, 11), _at(6, 13), "Leave", "TIME_OFF_OVERLAP"),
        (_at(7, 10), _at(7, 9), "Leave", "TIME_OFF_INVALID_RANGE"),
        (_at(-2, 9), _at(-1, 9), "Leave", "TIME_OFF_IN_PAST"),
        (_at(8, 9), _at(8, 10), " ", "TIME_OFF_REASON_REQUIRED"),
    ]
    for start, end, reason, code in cases:
        with pytest.raises(DomainError) as exc:
            add(start, end, reason)
        assert exc.value.code == code
    add(_at(6, 12), _at(6, 13))  # back to back is fine (half-open ranges)


def test_time_off_overlap_is_refused_by_the_database(doctor: Any, clerk: Any) -> None:
    DoctorTimeOff.objects.create(
        doctor=doctor, starts_at=_at(9, 9), ends_at=_at(9, 12), reason_en="x", created_by=clerk
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        DoctorTimeOff.objects.create(
            doctor=doctor, starts_at=_at(9, 10), ends_at=_at(9, 11), reason_en="y", created_by=clerk
        )


def test_time_off_api_needs_permission_and_reports_bookings(
    make_user: Any, api_client: ApiClient, doctor: Any, clerk: Any
) -> None:
    vs.book_appointment(doctor=doctor, starts_at=_at(4, 10), actor=clerk, contact_name="a")
    receptionist = make_user(roles=["receptionist"])
    assert api_client.login(receptionist.username).status_code == 200
    body = {"starts_at": _at(4, 9).isoformat(), "ends_at": _at(4, 12).isoformat(), "reason_en": "x"}
    url = f"/api/visits/doctors/{doctor.pk}/time-off"
    assert api_client.post(url, body).status_code == 403
    admin = make_user(roles=["admin"])
    other = ApiClient()
    assert other.login(admin.username).status_code == 200
    created = other.post(url, body)
    assert created.status_code == 201, created.content
    assert len(created.json()["appointments"]) == 1
    listed = other.get(url).json()
    assert [r["id"] for r in listed] == [created.json()["time_off"]["id"]]
    clash = other.post(url, body)
    assert clash.status_code == 409
    assert clash.json()["code"] == "TIME_OFF_OVERLAP"
    removed = other.request("DELETE", f"/api/visits/time-off/{listed[0]['id']}")
    assert removed.status_code == 204
    assert other.get(url).json() == []


def test_online_booking_api_permission_and_actions(make_user: Any, doctor: Any, clerk: Any) -> None:
    req = _request(doctor, clerk, _at(2, 9, 45), timezone.now() + timedelta(hours=2))
    req2 = _request(doctor, clerk, _at(2, 11, 45), timezone.now() + timedelta(hours=2))
    nurse, reception = ApiClient(), ApiClient()
    assert nurse.login(make_user(roles=["nurse"]).username).status_code == 200
    assert reception.login(make_user(roles=["receptionist"]).username).status_code == 200
    assert nurse.post(f"/api/visits/online-bookings/{req.pk}/approve").status_code == 403
    ok = reception.post(f"/api/visits/online-bookings/{req.pk}/approve")
    assert ok.status_code == 200, ok.content
    assert ok.json()["status"] == "booked"
    assert ok.json()["approved_by"]["id"] is not None
    no_note = reception.post(
        f"/api/visits/online-bookings/{req2.pk}/reject", {"reason_code": "OTHER"}
    )
    assert no_note.status_code == 409
    assert no_note.json()["code"] == "REASON_NOTE_REQUIRED"
    rejected = reception.post(f"/api/visits/online-bookings/{req2.pk}/reject", {"note": "full"})
    assert rejected.status_code == 200
    assert rejected.json()["cancel_reason"]["code"] == "ONLINE_REJECTED"


# --- the database backstop -------------------------------------------------------------------


def test_direct_sql_insert_of_an_overlapping_row_is_refused(doctor: Any, clerk: Any) -> None:
    first = vs.book_appointment(doctor=doctor, starts_at=_at(2, 9), actor=clerk, contact_name="a")
    insert = """
        INSERT INTO visits_appointment
          (contact_name, contact_phone, doctor_id, department_id, starts_at, ends_at, status,
           source, expires_at, notes, created_by_id, created_at, updated_at, cancel_note)
        VALUES ('b', '', %s, %s, %s, %s, %s, 'staff', %s, '', %s, now(), now(), '')
    """

    def row(start: datetime, end: datetime, status: str) -> list[Any]:
        expires = timezone.now() + timedelta(hours=1) if status == "requested" else None
        return [doctor.pk, doctor.department_id, start, end, status, expires, clerk.pk]

    for status in ("booked", "requested"):
        with (
            pytest.raises(IntegrityError) as exc,
            transaction.atomic(),
            connection.cursor() as cur,
        ):
            cur.execute(insert, row(_at(2, 9, 5), _at(2, 9, 20), status))
        assert "visits_appointment_no_overlap" in str(exc.value)
    # Back to back is legal (half-open ranges).
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(insert, row(first.ends_at, _at(2, 9, 30), "booked"))


def test_a_writer_that_skips_the_lock_gets_appointment_conflict(
    doctor: Any, clerk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    vs.book_appointment(doctor=doctor, starts_at=_at(2, 10), actor=clerk, contact_name="a")
    monkeypatch.setattr(vs, "_check_slot", lambda *a, **k: None)
    with pytest.raises(DomainError) as exc:
        vs.book_appointment(doctor=doctor, starts_at=_at(2, 10), actor=clerk, contact_name="b")
    assert exc.value.code == "APPOINTMENT_CONFLICT"
    assert Appointment.objects.filter(doctor=doctor, status="booked").count() == 1


def test_no_overlap_precheck_names_conflicts_and_changes_nothing(doctor: Any, clerk: Any) -> None:
    with connection.cursor() as cursor:
        migration.verify_overlaps_absent(cursor)  # clean data: does not raise
        # Data as it could exist before the constraint (rolled back with the test). The ALTER
        # comes first: a table with pending deferred trigger events cannot be altered.
        cursor.execute(
            "ALTER TABLE visits_appointment DROP CONSTRAINT visits_appointment_no_overlap"
        )

    def row(name: str, start: datetime, end: datetime) -> Appointment:
        return Appointment.objects.create(
            doctor=doctor,
            department=doctor.department,
            contact_name=name,
            starts_at=start,
            ends_at=end,
            created_by=clerk,
        )

    a = row("a", _at(2, 9), _at(2, 9, 15))
    b2 = row("b", _at(2, 9, 5), _at(2, 9, 20))
    row("c", _at(2, 9, 20), _at(2, 9, 35))  # back to back with b: not a conflict
    with connection.cursor() as cursor:
        found = migration.overlaps(cursor)
        assert [(r[0], r[1], r[4]) for r in found] == [(doctor.pk, a.pk, b2.pk)]
        with pytest.raises(RuntimeError) as exc:
            migration.verify_overlaps_absent(cursor)
    message = str(exc.value)
    assert f"appointment {a.pk}" in message
    assert f"appointment {b2.pk}" in message
    assert f"doctor {doctor.pk}" in message
    assert "ADR 0029" in message
    assert Appointment.objects.filter(doctor=doctor, status="booked").count() == 3


@pytest.mark.django_db(transaction=True)
def test_eight_concurrent_bookings_of_one_slot_make_exactly_one_row(make_user: Any) -> None:
    clerks = [make_user(roles=["receptionist"]) for _ in range(8)]
    doc = b.doctor()
    start = _at(1, 10)
    results: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(clerks))

    def book(clerk: Any, online: bool) -> None:
        try:
            barrier.wait(timeout=10)
            vs.book_appointment(
                doctor=doc,
                starts_at=start,
                actor=clerk,
                contact_name=f"caller {clerk.pk}",
                expires_at=timezone.now() + timedelta(hours=1) if online else None,
            )
            outcome = "ok"
        except DomainError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=book, args=(c, i % 2 == 0)) for i, c in enumerate(clerks)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == ["APPOINTMENT_CONFLICT"] * 7 + ["ok"], results
    assert Appointment.objects.filter(doctor=doc, status__in=["booked", "requested"]).count() == 1
