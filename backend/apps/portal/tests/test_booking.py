"""Booking and cancelling appointments on the portal (FEATURES 2.5, 15.2; ADR 0016)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import DoctorProfile, User
from apps.portal import services
from apps.portal.tests.conftest import PortalClient
from apps.visits.models import Appointment, AppointmentStatus

pytestmark = pytest.mark.django_db


def _doctor(username: str = "doctor") -> DoctorProfile:
    return User.objects.get(username=username).doctor_profile


def _free_slots(client: PortalClient, doctor_id: int, skip_days: int = 0) -> list[dict[str, Any]]:
    days = client.get(f"/api/portal/doctors/{doctor_id}/days").json()
    assert days, "the seeded doctor works every day"
    day = days[min(skip_days, len(days) - 1)]
    body = client.get(f"/api/portal/doctors/{doctor_id}/slots?on={day}").json()
    slots: list[dict[str, Any]] = body["slots"]
    return slots


def test_only_doctors_with_a_schedule_take_bookings(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    listed = {d["id"] for d in client.get("/api/portal/doctors").json()}
    assert _doctor().pk in listed
    unscheduled = DoctorProfile.objects.exclude(schedules__active=True).first()
    if unscheduled is None:  # every seeded doctor has hours: make one without
        from apps.core.tests import builders as b

        unscheduled = b.doctor()
    assert unscheduled.pk not in listed
    assert client.get(f"/api/portal/doctors/{unscheduled.pk}/days").status_code == 404
    response = client.post(
        "/api/portal/appointments",
        {
            "doctor_id": unscheduled.pk,
            "starts_at": (timezone.now() + timedelta(days=2)).isoformat(),
        },
    )
    assert response.status_code == 404


def test_slots_are_future_free_and_beyond_the_lead_time(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    days = client.get(f"/api/portal/doctors/{doctor.pk}/days").json()
    taken = {
        a.starts_at
        for a in Appointment.objects.filter(doctor=doctor, status=AppointmentStatus.BOOKED)
    }
    earliest = timezone.now() + timedelta(minutes=60)
    for day in days[:3]:
        for slot in client.get(f"/api/portal/doctors/{doctor.pk}/slots?on={day}").json()["slots"]:
            start = parse_datetime(slot["starts_at"])
            assert start is not None
            assert start >= earliest
            assert start not in taken
    assert len(days) <= 31


def test_book_a_free_slot(signed_in: dict[str, PortalClient], world: dict[str, Any]) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    slot = _free_slots(client, doctor.pk, skip_days=3)[0]
    response = client.post(
        "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": slot["starts_at"]}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "booked"
    assert body["can_cancel"] is True
    booked = Appointment.objects.get(pk=body["id"])
    assert booked.patient_id == world["a"]["patient"]["id"]
    assert booked.created_by.username == services.PORTAL_ACTOR_USERNAME
    assert body["id"] in {
        a["id"] for a in client.get("/api/portal/appointments").json()["upcoming"]
    }
    # The slot is gone for everyone, and taking it again is refused.
    again = signed_in["b"].post(
        "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": slot["starts_at"]}
    )
    assert again.status_code == 409
    assert again.json()["code"] == "PORTAL_SLOT_UNAVAILABLE"


def test_a_time_off_the_schedule_is_refused(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    slot = _free_slots(client, doctor.pk, skip_days=2)[0]
    off = parse_datetime(slot["starts_at"])
    assert off is not None
    response = client.post(
        "/api/portal/appointments",
        {"doctor_id": doctor.pk, "starts_at": (off + timedelta(minutes=7)).isoformat()},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PORTAL_SLOT_UNAVAILABLE"


def test_one_booking_per_doctor_per_day(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    first, second = _free_slots(client, doctor.pk, skip_days=4)[:2]
    assert (
        client.post(
            "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": first["starts_at"]}
        ).status_code
        == 201
    )
    response = client.post(
        "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": second["starts_at"]}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PORTAL_ALREADY_BOOKED"


def test_open_bookings_are_limited(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]  # already holds one upcoming appointment
    doctor = _doctor()
    for skip in (5, 6):
        slot = _free_slots(client, doctor.pk, skip_days=skip)[0]
        assert (
            client.post(
                "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": slot["starts_at"]}
            ).status_code
            == 201
        )
    slot = _free_slots(client, doctor.pk, skip_days=7)[0]
    response = client.post(
        "/api/portal/appointments", {"doctor_id": doctor.pk, "starts_at": slot["starts_at"]}
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "PORTAL_BOOKING_LIMIT",
        "message": "Too many upcoming appointments are booked already",
        "details": {"limit": 3},
    }


def test_cancel_own_future_booking(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    client = signed_in["a"]
    appointment_id = world["a"]["appointment"]["id"]
    Appointment.objects.filter(pk=appointment_id).update(
        starts_at=timezone.now() + timedelta(days=2),
        ends_at=timezone.now() + timedelta(days=2, minutes=15),
    )
    response = client.post(f"/api/portal/appointments/{appointment_id}/cancel")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    row = Appointment.objects.select_related("cancel_reason", "cancelled_by").get(pk=appointment_id)
    assert row.cancel_reason is not None
    assert row.cancel_reason.code == "PATIENT_REQUEST"
    assert row.cancelled_by is not None
    assert row.cancelled_by.username == services.PORTAL_ACTOR_USERNAME
    again = client.post(f"/api/portal/appointments/{appointment_id}/cancel")
    assert again.status_code == 409
    assert again.json()["code"] == "APPOINTMENT_NOT_BOOKED"


def test_cancel_too_close_to_the_start_is_refused(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    appointment_id = world["a"]["appointment"]["id"]
    Appointment.objects.filter(pk=appointment_id).update(
        starts_at=timezone.now() + timedelta(minutes=90),
        ends_at=timezone.now() + timedelta(minutes=105),
    )
    listed = signed_in["a"].get("/api/portal/appointments").json()["upcoming"][0]
    assert listed["can_cancel"] is False
    response = signed_in["a"].post(f"/api/portal/appointments/{appointment_id}/cancel")
    assert response.status_code == 409
    assert response.json()["code"] == "PORTAL_CANCEL_TOO_LATE"
    assert response.json()["details"] == {"cutoff_hours": 2}
    assert Appointment.objects.get(pk=appointment_id).status == AppointmentStatus.BOOKED


def test_booking_payload_is_validated(signed_in: dict[str, PortalClient]) -> None:
    response = signed_in["a"].post("/api/portal/appointments", {"doctor_id": "x"})
    assert response.status_code == 422
