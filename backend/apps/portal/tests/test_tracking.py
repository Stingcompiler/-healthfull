"""Patient tracking (public site Phase 5; plan section 5, ADR 0029 I): the visit timeline and
the portal inbox.

* A patient sees only their own visits and notices: anyone else's id answers 404.
* The timeline speaks the patient-facing families of ``domain.portal_status`` and leaks
  nothing internal (no prices but the patient's share of approved invoices, no staff notes,
  no unapproved result).
* Notices are written by the event's own service in the event's transaction: a rolled-back
  event leaves none. Booking changes of a file's bookings and result approvals write them;
  guest bookings (no file) never do.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest import mock

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.core.models import DoctorProfile, PublicSiteSettings, ReasonCode, User
from apps.lab import services as lab
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.portal.models import PatientNotice
from apps.portal.tests.conftest import PortalClient
from apps.visits import services as vs
from apps.visits.models import Appointment, AppointmentSource, AppointmentStatus

pytestmark = pytest.mark.django_db

#: Keys that would reveal more than the portal already shows (prices, payer shares, notes).
_FORBIDDEN_KEYS = {
    "unit_price",
    "gross",
    "discount",
    "payer_share",
    "payer",
    "price",
    "order_note",
    "performed_note",
    "cancel_note",
    "notes",
    "chief_complaint",
    "comment",
}


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _keys(item)
        return found
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


def _doctor(username: str = "doctor") -> DoctorProfile:
    return User.objects.get(username=username).doctor_profile


def _settings(**fields: Any) -> None:
    PublicSiteSettings.load()
    PublicSiteSettings.objects.filter(pk=PublicSiteSettings.SINGLETON_PK).update(**fields)


def _slot(client: PortalClient, doctor_id: int, skip_days: int) -> str:
    days = client.get(f"/api/portal/doctors/{doctor_id}/days").json()
    day = days[min(skip_days, len(days) - 1)]
    slots = client.get(f"/api/portal/doctors/{doctor_id}/slots?on={day}").json()["slots"]
    start: str = slots[0]["starts_at"]
    return start


def _book(client: PortalClient, skip_days: int) -> dict[str, Any]:
    doctor = _doctor()
    response = client.post(
        "/api/portal/appointments",
        {"doctor_id": doctor.pk, "starts_at": _slot(client, doctor.pk, skip_days)},
    )
    assert response.status_code == 201, response.content
    body: dict[str, Any] = response.json()
    return body


def _notices(patient_id: int, **filters: Any) -> list[PatientNotice]:
    return list(
        PatientNotice.objects.filter(patient_id=patient_id, **filters).order_by("created_at", "id")
    )


def _clerk() -> User:
    return User.objects.get(username="reception")


# --- the timeline ----------------------------------------------------------------------------


def test_timeline_speaks_patient_states_and_leaks_nothing_internal(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    w = world["a"]
    response = signed_in["a"].get(f"/api/portal/visits/{w['visit']['id']}/timeline")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["number"] == w["visit"]["number"]
    assert body["display_status"] == "at_center"
    orders = {o["line_id"]: o for o in body["orders"]}
    # The approved CBC reads "result published" and opens; the malaria test waiting for the
    # supervisor is in progress and never opens a result.
    assert orders[w["approved_line"]]["display_status"] == "result_published"
    assert orders[w["approved_line"]]["result_line_id"] == w["approved_line"]
    assert orders[w["draft_line"]]["display_status"] == "in_progress"
    assert orders[w["draft_line"]]["result_line_id"] is None
    # The prescription ordered after payment waits for the cashier.
    drug = next(o for o in body["orders"] if o["kind"] == "drug")
    assert drug["display_status"] == "pay_at_reception"
    # The paid invoice: the patient's share only, and "paid".
    [invoice] = body["invoices"]
    assert invoice["id"] == w["invoice"]["id"]
    assert invoice["display_status"] == "paid"
    assert invoice["outstanding"] == "0.00"
    assert not _keys(body) & _FORBIDDEN_KEYS


def test_timeline_and_visit_list_are_the_patients_own(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    for me, other in (("a", "b"), ("b", "a")):
        client = signed_in[me]
        listed = client.get("/api/portal/visits").json()
        assert [v["id"] for v in listed] == [world[me]["visit"]["id"]]
        response = client.get(f"/api/portal/visits/{world[other]['visit']['id']}/timeline")
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
    # Unknown id: the same answer.
    assert signed_in["a"].get("/api/portal/visits/999999/timeline").status_code == 404


def test_timeline_shows_the_booking_the_visit_came_from(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    w = world["a"]
    appointment = Appointment.objects.get(pk=w["appointment"]["id"])
    Appointment.objects.filter(pk=appointment.pk).update(starts_at=timezone.now())
    visit = vs.convert_appointment(appointment, actor=_clerk())
    body = signed_in["a"].get(f"/api/portal/visits/{visit.pk}/timeline").json()
    assert body["booking"]["id"] == appointment.pk
    assert body["booking"]["display_status"] == "received"
    assert body["display_status"] == "at_center"
    assert body["booking"]["doctor"]["id"] == appointment.doctor_id


def test_timeline_answers_portal_disabled_with_tracking_off(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    _settings(patient_tracking_enabled=False)
    for path in (
        f"/api/portal/visits/{world['a']['visit']['id']}/timeline",
        "/api/portal/visits",
        "/api/portal/notices",
    ):
        response = signed_in["a"].get(path)
        assert response.status_code == 409, path
        assert response.json()["code"] == "PORTAL_DISABLED"


# --- the inbox -------------------------------------------------------------------------------


def test_world_wrote_result_and_booking_notices(world: dict[str, dict[str, Any]]) -> None:
    w = world["a"]
    kinds = [n.kind for n in _notices(w["patient"]["id"])]
    assert kinds == ["result_published", "booking_confirmed"]
    result = _notices(w["patient"]["id"], kind="result_published")[0]
    assert result.service_line_id == w["approved_line"]
    assert result.payload["amended"] is False
    assert result.payload["test_en"]
    assert set(result.payload) == {"test_ar", "test_en", "amended"}
    assert result.channels == ["portal"]
    # The malaria result still waits for the supervisor: no notice about it.
    assert not PatientNotice.objects.filter(service_line_id=w["draft_line"]).exists()


def test_inbox_lists_own_notices_counts_unread_and_marks_read(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    client = signed_in["a"]
    body = client.get("/api/portal/notices").json()
    assert body["unread"] == 2
    ids = {n["id"] for n in body["items"]}
    assert ids == {n.pk for n in _notices(world["a"]["patient"]["id"])}
    result = next(n for n in body["items"] if n["kind"] == "result_published")
    assert result["result_line_id"] == world["a"]["approved_line"]
    booking = next(n for n in body["items"] if n["kind"] == "booking_confirmed")
    assert booking["appointment_id"] == world["a"]["appointment"]["id"]
    assert booking["result_line_id"] is None

    read = client.post(f"/api/portal/notices/{result['id']}/read")
    assert read.status_code == 200
    first_read = read.json()["read_at"]
    assert first_read is not None
    # Idempotent: reading again keeps the first time.
    assert client.post(f"/api/portal/notices/{result['id']}/read").json()["read_at"] == first_read
    assert client.get("/api/portal/notices").json()["unread"] == 1

    marked = client.post("/api/portal/notices/read-all").json()
    assert marked == {"marked": 1, "unread": 0}
    # B's inbox is untouched.
    assert signed_in["b"].get("/api/portal/notices").json()["unread"] == 2


def test_another_patients_notice_answers_404(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    theirs = world["b"]["notice_id"]
    response = signed_in["a"].post(f"/api/portal/notices/{theirs}/read")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert PatientNotice.objects.get(pk=theirs).read_at is None
    signed_in["a"].post("/api/portal/notices/read-all")
    assert PatientNotice.objects.get(pk=theirs).read_at is None


def test_a_notice_written_for_the_file_shows_in_the_inbox(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    a = Patient.objects.get(pk=world["a"]["patient"]["id"])
    with transaction.atomic():
        extra = patients.notify(a, "booking_expired", starts_at="2026-11-01T09:00:00+03:00")
    assert extra.pk in {n["id"] for n in signed_in["a"].get("/api/portal/notices").json()["items"]}


# --- booking notices -------------------------------------------------------------------------


def test_booking_changes_write_notices_for_the_file(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    _settings(require_approval=True, request_ttl_hours=24, min_review_minutes=30)
    client = signed_in["a"]
    pid = world["a"]["patient"]["id"]
    before = {n.pk for n in _notices(pid)}

    def new() -> list[PatientNotice]:
        rows = [n for n in _notices(pid) if n.pk not in before]
        before.update(n.pk for n in rows)
        return rows

    # Requested, then approved.
    one = _book(client, skip_days=3)
    [requested] = new()
    assert requested.kind == "booking_requested"
    assert requested.appointment_id == one["id"]
    assert requested.payload["display_status"] == "awaiting_approval"
    assert requested.payload["doctor_en"]
    vs.approve_online_booking(Appointment.objects.get(pk=one["id"]), actor=_clerk())
    [confirmed] = new()
    assert confirmed.kind == "booking_confirmed"

    # Moved by the patient: one "rescheduled" notice for the new time, waiting again.
    _settings(require_approval=True)
    target = _slot(client, _doctor().pk, skip_days=6)
    moved = client.post(f"/api/portal/appointments/{one['id']}/reschedule", {"starts_at": target})
    assert moved.status_code == 201, moved.content
    [rescheduled] = new()
    assert rescheduled.kind == "booking_rescheduled"
    assert rescheduled.appointment_id == moved.json()["id"]
    assert rescheduled.payload["awaiting_approval"] is True
    assert rescheduled.payload["from_starts_at"]

    # Declined by reception: the reason's label, never the note.
    vs.reject_online_booking(
        Appointment.objects.get(pk=moved.json()["id"]), actor=_clerk(), note="internal: full day"
    )
    [declined] = new()
    assert declined.kind == "booking_declined"
    reason = ReasonCode.objects.get(category="appointment_cancel", code="ONLINE_REJECTED")
    assert declined.payload["reason_en"] == reason.label_en
    assert "internal" not in str(declined.payload)

    # Cancelled by the patient.
    two = _book(client, skip_days=4)
    new()
    assert client.post(f"/api/portal/appointments/{two['id']}/cancel").status_code == 200
    [cancelled] = new()
    assert cancelled.kind == "booking_cancelled"
    assert cancelled.payload["by_you"] is True

    # Expired unanswered (the sweep).
    three = _book(client, skip_days=5)
    new()
    row = Appointment.objects.get(pk=three["id"])
    assert row.expires_at is not None
    vs.expire_requests(now=row.expires_at + timedelta(minutes=1))
    [expired] = new()
    assert expired.kind == "booking_expired"
    assert expired.appointment_id == three["id"]


def test_a_guest_booking_writes_no_notice(seeded: None) -> None:
    doctor = _doctor()
    DoctorProfile.objects.filter(pk=doctor.pk).update(online_bookable=True)
    slots: list[Any] = []
    day = timezone.localdate() + timedelta(days=2)
    while not slots:
        day += timedelta(days=1)
        slots = vs.available_slots(doctor, day, now=timezone.now())
    before = PatientNotice.objects.count()
    guest = vs.book_appointment(
        doctor=doctor,
        starts_at=slots[0][0],
        actor=_clerk(),
        contact_name="Guest Visitor",
        contact_phone="0912000111",
        source=AppointmentSource.GUEST,
        expires_at=timezone.now() + timedelta(hours=12),
    )
    vs.approve_online_booking(guest, actor=_clerk())
    vs.cancel_appointment(guest, actor=_clerk(), reason_code="PATIENT_REQUEST", note="x")
    assert PatientNotice.objects.count() == before


# --- same transaction: a rolled-back event leaves no notice ---------------------------------


class _Rollback(Exception):
    pass


def test_rolled_back_approval_leaves_no_notice(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    _settings(require_approval=True, request_ttl_hours=24, min_review_minutes=30)
    booked = _book(signed_in["a"], skip_days=3)
    appointment = Appointment.objects.get(pk=booked["id"])
    count = PatientNotice.objects.count()
    seen: list[int] = []

    def approve_then_fail() -> None:
        with transaction.atomic():
            vs.approve_online_booking(appointment, actor=_clerk())
            # Written in the event's transaction, not after commit.
            seen.append(PatientNotice.objects.count())
            raise _Rollback

    with pytest.raises(_Rollback):
        approve_then_fail()
    assert seen == [count + 1]
    assert PatientNotice.objects.count() == count
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.REQUESTED


def test_a_failing_approval_of_a_result_leaves_no_notice(
    world: dict[str, dict[str, Any]],
) -> None:
    line = ServiceLine.objects.get(pk=world["a"]["draft_line"])
    supervisor = User.objects.get(username="labsup")
    with (
        mock.patch.object(lab, "_notify_result", side_effect=DatabaseError("boom")),
        pytest.raises(DatabaseError),
    ):
        lab.approve_results(line, actor=supervisor)
    assert not PatientNotice.objects.filter(service_line=line).exists()
    # Approved for real: one notice, after the approval committed.
    lab.approve_results(line, actor=supervisor)
    [notice] = PatientNotice.objects.filter(service_line=line)
    assert notice.kind == "result_published"


def test_a_failing_booking_write_leaves_no_notice(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    """The cancel's own write fails after the notice was written: neither survives."""
    appointment = Appointment.objects.get(pk=world["a"]["appointment"]["id"])
    count = PatientNotice.objects.count()
    with (
        mock.patch.object(vs, "_notices", side_effect=lambda: _ExplodingNotices()),
        pytest.raises(DatabaseError),
    ):
        vs.cancel_appointment(appointment, actor=_clerk(), reason_code="DOCTOR_UNAVAILABLE")
    assert PatientNotice.objects.count() == count
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.BOOKED


class _ExplodingNotices:
    """Writes the notice, then fails as if the rest of the event's work broke."""

    @staticmethod
    def booking_changed(appointment: Appointment) -> None:
        from apps.portal import notices

        notices.booking_changed(appointment)
        assert PatientNotice.objects.filter(appointment=appointment).exists()
        raise DatabaseError("the event failed after its notice")


# --- the notice row itself ------------------------------------------------------------------


def test_notify_needs_a_transaction_and_a_known_channel(world: dict[str, dict[str, Any]]) -> None:
    a = Patient.objects.get(pk=world["a"]["patient"]["id"])
    # Tests run inside a transaction; outside one (autocommit) the writer refuses.
    outside = mock.Mock(in_atomic_block=False)
    with (
        mock.patch("apps.portal.notices.transaction.get_connection", return_value=outside),
        pytest.raises(RuntimeError, match="transaction"),
    ):
        patients.notify(a, "booking_expired")
    with pytest.raises(ValueError, match="sms"), transaction.atomic():
        patients.notify(a, "booking_expired", channels=("sms",))


def test_a_notice_never_changes_but_its_read_time_once(world: dict[str, dict[str, Any]]) -> None:
    notice = PatientNotice.objects.get(pk=world["a"]["notice_id"])
    with pytest.raises(DatabaseError), transaction.atomic():
        PatientNotice.objects.filter(pk=notice.pk).update(payload={"test_en": "changed"})
    with pytest.raises(DatabaseError), transaction.atomic():
        PatientNotice.objects.filter(pk=notice.pk).delete()
    now = timezone.now()
    PatientNotice.objects.filter(pk=notice.pk).update(read_at=now)
    with pytest.raises(DatabaseError), transaction.atomic():
        PatientNotice.objects.filter(pk=notice.pk).update(read_at=None)
