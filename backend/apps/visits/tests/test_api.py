"""``/api/visits`` contract: visits, queue board, waiting-room feed, token slip, appointments."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.core.models import UserRole
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.visits import services as vs
from apps.visits.models import Appointment, DoctorSchedule, QueueEntry, Visit
from conftest import ApiClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk(make_user):
    return make_user("clerk", roles=["receptionist"])


@pytest.fixture
def client_as(make_user, api_client: ApiClient):
    def _login(*roles: str) -> ApiClient:
        user = make_user(roles=list(roles))
        assert api_client.login(user.username).status_code == 200
        return api_client

    return _login


@pytest.fixture
def fee_doctor():
    d = b.doctor()
    d.consultation_service = b.service(kind="consultation")
    d.save()
    return d


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code
    return body


def _settle(line: ServiceLine) -> None:
    inv = b.draft_invoice(line.visit)
    b.invoice_line(inv, line=line)
    b.approve_invoice(inv)
    now = timezone.now()
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced", invoiced_at=now)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="settled", settled_at=now)


# --- visits ---------------------------------------------------------------------------------


def test_options_list_departments_doctors_and_reasons(client_as, fee_doctor) -> None:
    body = client_as("receptionist").get("/api/visits/options").json()
    assert fee_doctor.pk in [d["id"] for d in body["doctors"]]
    assert fee_doctor.department_id in [d["id"] for d in body["departments"]]
    assert "PATIENT_LEFT" in [r["code"] for r in body["cancel_reasons"]]
    assert body["follow_up_window_days"] >= 0


def test_create_visit_adds_fee_line_and_token_without_prices(client_as, fee_doctor) -> None:
    pat = b.patient()
    api = client_as("receptionist")
    created = api.post("/api/visits", {"patient_id": pat.pk, "doctor_id": fee_doctor.pk})
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["visit"]["number"].startswith("VIS-")
    assert body["visit"]["department"]["id"] == fee_doctor.department_id
    assert body["visit"]["payer"] is None
    [line] = body["lines"]
    assert line["order_source"] == "consultation_fee"
    assert line["state"] == "requested"
    assert not {"unit_price", "gross", "patient_share"} & set(line)
    assert body["queue_entry"]["token_no"] == 1
    assert body["queue_entry"]["ready"] is False
    assert body["queue_ready"] is False

    # A second visit with the same doctor inside the window is a follow-up.
    again = api.post("/api/visits", {"patient_id": pat.pk, "doctor_id": fee_doctor.pk}).json()
    assert again["visit"]["visit_type"] == "follow_up"
    assert again["visit"]["follow_up_of_id"] == body["visit"]["id"]

    today = timezone.localdate().isoformat()
    listed = api.get(f"/api/visits?day={today}&department_id={fee_doctor.department_id}")
    assert listed.json()["count"] == 2
    assert api.get(f"/api/visits?patient_id={pat.pk}").json()["count"] == 2
    detail = api.get(f"/api/visits/{body['visit']['id']}").json()
    assert detail["visit"]["id"] == body["visit"]["id"]


def test_create_visit_errors_and_permission(client_as) -> None:
    pat = b.patient()
    api = client_as("receptionist")
    _error(api.post("/api/visits", {"patient_id": pat.pk}), 409, "DEPARTMENT_REQUIRED")
    assert api.post("/api/visits", {"patient_id": 999999}).status_code == 404
    doctor_api = client_as("doctor")
    dept = b.department()
    response = doctor_api.post("/api/visits", {"patient_id": pat.pk, "department_id": dept.pk})
    _error(response, 403, "PERMISSION_DENIED")


def test_cancel_visit_with_reason(client_as, fee_doctor, clerk) -> None:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    api = client_as("receptionist")
    _error(
        api.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "NOPE"}), 409, "REASON_UNKNOWN"
    )
    _error(
        api.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "OTHER"}),
        409,
        "REASON_NOTE_REQUIRED",
    )
    done = api.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "PATIENT_LEFT"})
    assert done.status_code == 200, done.content
    body = done.json()
    assert body["visit"]["status"] == "cancelled"
    assert body["visit"]["cancel_reason"]["code"] == "PATIENT_LEFT"
    assert body["lines"][0]["state"] == "cancelled"
    assert QueueEntry.objects.get(visit=visit).status == "cancelled"
    _error(
        api.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "PATIENT_LEFT"}),
        409,
        "VISIT_NOT_OPEN",
    )


def test_reception_sees_and_cannot_cancel_a_billed_visit(client_as, clerk, fee_doctor) -> None:
    """Review: the front desk was offered 'Cancel visit' on paid visits and always got 403.

    The rows now say ``billed``; a receptionist (no billing.approve_credit_note) is refused
    without any change, and a cashier supervisor cancels it with the credit note.
    """
    visit = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    reception = client_as("receptionist")
    dept = fee_doctor.department_id
    [row] = reception.get(f"/api/visits/queue/board?department_id={dept}").json()
    assert row["billed"] is False
    assert reception.get(f"/api/visits/{visit.pk}").json()["visit"]["billed"] is False

    _settle(ServiceLine.objects.get(visit=visit))
    [row] = reception.get(f"/api/visits/queue/board?department_id={dept}").json()
    assert row["billed"] is True
    listed = reception.get(f"/api/visits?patient_id={visit.patient_id}").json()
    assert listed["items"][0]["billed"] is True

    response = reception.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "PATIENT_LEFT"})
    body = _error(response, 403, "PERMISSION_DENIED")
    assert body["details"]["permission"] == "billing.approve_credit_note"
    visit.refresh_from_db()
    assert visit.status == "open"
    assert ServiceLine.objects.get(visit=visit).billing_status == "settled"

    supervisor = client_as("cashier_supervisor")
    done = supervisor.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "PATIENT_LEFT"})
    assert done.status_code == 200, done.content
    assert done.json()["visit"]["status"] == "cancelled"
    assert ServiceLine.objects.get(visit=visit).billing_status == "credited"


def test_cancel_needs_permission(client_as, clerk, fee_doctor) -> None:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    api = client_as("nurse")
    response = api.post(f"/api/visits/{visit.pk}/cancel", {"reason_code": "PATIENT_LEFT"})
    _error(response, 403, "PERMISSION_DENIED")


def test_timeline_hides_money_from_doctors(client_as, clerk, fee_doctor) -> None:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    _settle(ServiceLine.objects.get(visit=visit))
    doctor = client_as("doctor").get(f"/api/visits/{visit.pk}/timeline").json()
    kinds = [e["kind"] for e in doctor]
    assert kinds[0] == "visit_created"
    assert "line_ordered" in kinds
    assert "invoice_approved" not in kinds
    assert doctor[0]["actor"]["id"] == clerk.pk
    cashier = client_as("cashier").get(f"/api/visits/{visit.pk}/timeline").json()
    assert "invoice_approved" in [e["kind"] for e in cashier]


# --- queue ----------------------------------------------------------------------------------


def test_board_call_next_and_moves(client_as, clerk, fee_doctor) -> None:
    unpaid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    paid = vs.create_visit(
        patient=b.patient(full_name_ar="عبد الله الطيب"), actor=clerk, doctor=fee_doctor
    )
    _settle(ServiceLine.objects.get(visit=paid))
    dept = fee_doctor.department_id
    api = client_as("receptionist")

    board = api.get(f"/api/visits/queue/board?department_id={dept}").json()
    assert [(r["visit_id"], r["ready"]) for r in board] == [(unpaid.pk, False), (paid.pk, True)]

    unpaid_entry = QueueEntry.objects.get(visit=unpaid)
    _error(
        api.post(f"/api/visits/queue/{unpaid_entry.pk}/move", {"action": "call"}),
        409,
        "QUEUE_NOT_READY",
    )
    called = api.post("/api/visits/queue/call-next", {"department_id": dept})
    assert called.status_code == 200, called.content
    assert called.json()["visit_id"] == paid.pk
    assert called.json()["status"] == "called"
    _error(api.post("/api/visits/queue/call-next", {"department_id": dept}), 409, "QUEUE_EMPTY")

    # The waiting room shows the called paid token with an abbreviated name only.
    display = api.get(f"/api/visits/queue/display?department_id={dept}").json()
    assert [e["token_no"] for e in display["serving"]] == [called.json()["token_no"]]
    assert display["serving"][0]["name_ar"] == "عبد الله ط."
    assert display["waiting"] == []
    assert "patient" not in display["serving"][0]

    entry_id = called.json()["id"]
    started = api.post(f"/api/visits/queue/{entry_id}/move", {"action": "start"}).json()
    assert started["status"] == "in_progress"
    # Finishing performs the fee line: the doctor's act, never the front desk's.
    _error(
        api.post(f"/api/visits/queue/{entry_id}/move", {"action": "finish"}),
        403,
        "PERMISSION_DENIED",
    )
    assert ServiceLine.objects.get(visit=paid).fulfilment_status == "pending"
    assert QueueEntry.objects.get(pk=entry_id).status == "in_progress"
    api = client_as("doctor")
    finished = api.post(f"/api/visits/queue/{entry_id}/move", {"action": "finish"}).json()
    assert finished["status"] == "done"
    line = ServiceLine.objects.get(visit=paid)
    assert line.fulfilment_status == "performed"
    assert UserRole.objects.filter(user=line.performed_by, role__code="doctor").exists()
    _error(
        api.post(f"/api/visits/queue/{entry_id}/move", {"action": "call"}),
        409,
        "QUEUE_TRANSITION_INVALID",
    )
    assert api.post(f"/api/visits/queue/{entry_id}/move", {"action": "x"}).status_code == 422


def test_finish_by_reception_or_nurse_is_refused(client_as, clerk, fee_doctor) -> None:
    """Review: a receptionist could finish a consultation and so perform the doctor's fee."""
    visit = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    _settle(ServiceLine.objects.get(visit=visit))
    entry = QueueEntry.objects.get(visit=visit)
    vs.start_consultation(vs.call_patient(entry, actor=clerk), actor=clerk)
    for role in ("receptionist", "nurse"):
        response = client_as(role).post(f"/api/visits/queue/{entry.pk}/move", {"action": "finish"})
        body = _error(response, 403, "PERMISSION_DENIED")
        assert body["details"]["permission"] == "visits.finish_consultation"
    line = ServiceLine.objects.get(visit=visit)
    assert (line.fulfilment_status, line.performed_by_id) == ("pending", None)


def test_token_slip_does_not_count_unpaid_tokens_ahead(client_as, clerk, fee_doctor) -> None:
    """Review: the slip counted unpaid tokens that call_next skips."""
    unpaid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    paid = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    mine = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    _settle(ServiceLine.objects.get(visit=paid))
    entry = QueueEntry.objects.get(visit=mine)
    body = client_as("receptionist").get(f"/api/visits/queue/{entry.pk}/token").json()
    assert body["entry"]["token_no"] == 3
    assert body["ahead"] == 1
    assert unpaid.pk != paid.pk


def test_token_slip(client_as, clerk, fee_doctor) -> None:
    first = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    second = vs.create_visit(patient=b.patient(), actor=clerk, doctor=fee_doctor)
    _settle(ServiceLine.objects.get(visit=first))
    entry = QueueEntry.objects.get(visit=second)
    body = client_as("receptionist").get(f"/api/visits/queue/{entry.pk}/token").json()
    assert body["entry"]["token_no"] == 2
    assert body["entry"]["visit_number"] == second.number
    assert body["ahead"] == 1
    assert "name_ar" in body["center"]
    assert first.pk != second.pk


def test_queue_permissions(client_as, fee_doctor) -> None:
    api = client_as("cashier")
    _error(api.get("/api/visits/queue/board"), 403, "PERMISSION_DENIED")
    _error(
        api.post("/api/visits/queue/call-next", {"department_id": fee_doctor.department_id}),
        403,
        "PERMISSION_DENIED",
    )


# --- appointments ---------------------------------------------------------------------------


def _schedule(doctor: Any) -> datetime:
    """Give the doctor clinic hours tomorrow 08:00-12:00 and return tomorrow 09:00."""
    day = timezone.localdate() + timedelta(days=1)
    DoctorSchedule.objects.create(
        doctor=doctor,
        weekday=day.weekday(),
        start_time=time(8, 0),
        end_time=time(12, 0),
        slot_minutes=30,
    )
    return datetime.combine(day, time(9, 0), tzinfo=timezone.get_current_timezone())


def test_appointment_book_conflict_reschedule_cancel(client_as, fee_doctor) -> None:
    start = _schedule(fee_doctor)
    pat = b.patient()
    api = client_as("receptionist")
    booked = api.post(
        "/api/visits/appointments",
        {"doctor_id": fee_doctor.pk, "starts_at": start.isoformat(), "patient_id": pat.pk},
    )
    assert booked.status_code == 201, booked.content
    appt = booked.json()
    assert appt["status"] == "booked"
    assert appt["visit_id"] is None
    assert datetime.fromisoformat(appt["ends_at"]) - start == timedelta(minutes=30)

    clash = _error(
        api.post(
            "/api/visits/appointments",
            {
                "doctor_id": fee_doctor.pk,
                "starts_at": (start + timedelta(minutes=15)).isoformat(),
                "contact_name": "Caller",
            },
        ),
        409,
        "APPOINTMENT_CONFLICT",
    )
    assert clash["details"]["appointments"] == [appt["id"]]
    _error(
        api.post(
            "/api/visits/appointments",
            {
                "doctor_id": fee_doctor.pk,
                "starts_at": start.replace(hour=13).isoformat(),
                "contact_name": "Caller",
            },
        ),
        409,
        "OUTSIDE_SCHEDULE",
    )

    day = start.date().isoformat()
    agenda = api.get(f"/api/visits/appointments/day?doctor_id={fee_doctor.pk}&day={day}").json()
    assert agenda["works"] is True
    assert [i["appointment"]["id"] for i in agenda["items"] if i["appointment"]] == [appt["id"]]
    assert len([i for i in agenda["items"] if i["appointment"] is None]) == 7

    edited = api.patch(f"/api/visits/appointments/{appt['id']}", {"notes": "fasting"}).json()
    assert edited["notes"] == "fasting"
    later = (start + timedelta(hours=1)).isoformat()
    moved = api.post(f"/api/visits/appointments/{appt['id']}/reschedule", {"starts_at": later})
    assert moved.status_code == 201, moved.content
    assert moved.json()["rescheduled_from_id"] == appt["id"]
    assert Appointment.objects.get(pk=appt["id"]).status == "rescheduled"

    upcoming = api.get(f"/api/visits/appointments/upcoming?patient_id={pat.pk}").json()
    assert [a["id"] for a in upcoming] == [moved.json()["id"]]

    cancel_url = f"/api/visits/appointments/{moved.json()['id']}/cancel"
    options = api.get("/api/visits/options").json()
    assert "PATIENT_REQUEST" in [r["code"] for r in options["appointment_cancel_reasons"]]
    _error(api.post(cancel_url, {"reason_code": ""}), 409, "REASON_REQUIRED")
    _error(api.post(cancel_url, {"reason_code": "PATIENT_LEFT"}), 409, "REASON_UNKNOWN")
    _error(api.post(cancel_url, {"reason_code": "OTHER", "note": " "}), 409, "REASON_NOTE_REQUIRED")
    cancelled = api.post(cancel_url, {"reason_code": "PATIENT_REQUEST", "note": "travelling"})
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_note"] == "travelling"
    assert cancelled.json()["cancel_reason"]["code"] == "PATIENT_REQUEST"


def test_check_in_converts_appointment_to_visit(client_as, fee_doctor, make_user) -> None:
    start = _schedule(fee_doctor)
    api = client_as("receptionist")
    appt = api.post(
        "/api/visits/appointments",
        {"doctor_id": fee_doctor.pk, "starts_at": start.isoformat(), "contact_name": "Caller"},
    ).json()
    _error(api.post(f"/api/visits/appointments/{appt['id']}/check-in", {}), 409, "PATIENT_REQUIRED")
    pat = b.patient()
    arrived = api.post(f"/api/visits/appointments/{appt['id']}/check-in", {"patient_id": pat.pk})
    assert arrived.status_code == 201, arrived.content
    visit = arrived.json()["visit"]
    assert visit["appointment_id"] == appt["id"]
    assert visit["patient"]["id"] == pat.pk
    assert Visit.objects.get(pk=visit["id"]).appointment_id == appt["id"]
    assert Appointment.objects.get(pk=appt["id"]).status == "arrived"
    _error(
        api.post(f"/api/visits/appointments/{appt['id']}/check-in", {"patient_id": pat.pk}),
        409,
        "APPOINTMENT_NOT_BOOKED",
    )


def test_doctor_reads_the_appointment_day_but_cannot_book(client_as, fee_doctor) -> None:
    """Review: the read-only day view needed manage_appointments, so doctors got 403."""
    start = _schedule(fee_doctor)
    api = client_as("doctor")
    day = start.date().isoformat()
    agenda = api.get(f"/api/visits/appointments/day?doctor_id={fee_doctor.pk}&day={day}")
    assert agenda.status_code == 200, agenda.content
    assert agenda.json()["works"] is True
    _error(
        api.post(
            "/api/visits/appointments",
            {"doctor_id": fee_doctor.pk, "starts_at": start.isoformat(), "contact_name": "X"},
        ),
        403,
        "PERMISSION_DENIED",
    )
    _error(
        client_as("cashier").post(
            "/api/visits/appointments",
            {"doctor_id": fee_doctor.pk, "starts_at": start.isoformat(), "contact_name": "X"},
        ),
        403,
        "PERMISSION_DENIED",
    )
