"""Portal booking under the Phase 3 rules (ADR 0029 A2, A7, A8, B, C): approval makes a
request that holds its slot, doctors must be offered online, time off is never offered, and
the patient reschedules their own confirmed booking."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import DoctorProfile, PublicSiteSettings, User
from apps.portal.tests.conftest import PortalClient
from apps.visits import services as vs
from apps.visits.models import Appointment, AppointmentStatus

pytestmark = pytest.mark.django_db


def _doctor(username: str = "doctor") -> DoctorProfile:
    return User.objects.get(username=username).doctor_profile


def _settings(**fields: Any) -> None:
    PublicSiteSettings.load()
    PublicSiteSettings.objects.filter(pk=PublicSiteSettings.SINGLETON_PK).update(**fields)


def _slots(client: PortalClient, doctor_id: int, skip_days: int = 0) -> list[dict[str, Any]]:
    days = client.get(f"/api/portal/doctors/{doctor_id}/days").json()
    day = days[min(skip_days, len(days) - 1)]
    body = client.get(f"/api/portal/doctors/{doctor_id}/slots?on={day}").json()
    slots: list[dict[str, Any]] = body["slots"]
    return slots


def _book(client: PortalClient, doctor_id: int, start: str) -> Any:
    return client.post("/api/portal/appointments", {"doctor_id": doctor_id, "starts_at": start})


def test_with_approval_a_booking_is_a_request_that_holds_the_slot(
    signed_in: dict[str, PortalClient],
) -> None:
    _settings(require_approval=True, request_ttl_hours=24, min_review_minutes=30)
    client = signed_in["a"]
    doctor = _doctor()
    slot = _slots(client, doctor.pk, skip_days=3)[0]
    response = _book(client, doctor.pk, slot["starts_at"])
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "requested"
    assert body["display_status"] == "awaiting_approval"
    assert body["can_cancel"] is True
    assert body["can_reschedule"] is False
    row = Appointment.objects.get(pk=body["id"])
    assert row.source == "portal"
    assert row.expires_at is not None
    assert row.expires_at <= row.created_at + timedelta(hours=24, seconds=1)
    # Held: another patient is refused, and the slot is no longer offered.
    again = _book(signed_in["b"], doctor.pk, slot["starts_at"])
    assert again.status_code == 409
    starts = {s["starts_at"] for s in _slots(client, doctor.pk, skip_days=3)}
    assert slot["starts_at"] not in starts
    # Listed as upcoming, counted against the limit; cancellable by the patient.
    upcoming = client.get("/api/portal/appointments").json()
    assert body["id"] in {a["id"] for a in upcoming["upcoming"]}
    assert upcoming["rules"]["require_approval"] is True
    cancelled = client.post(f"/api/portal/appointments/{body['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["display_status"] == "cancelled_by_you"


def test_approval_on_keeps_the_review_window_free(signed_in: dict[str, PortalClient]) -> None:
    """While approval is on, no slot is offered closer than lead + review window."""
    _settings(require_approval=True, lead_minutes=60, min_review_minutes=120)
    client = signed_in["a"]
    doctor = _doctor()
    earliest = timezone.now() + timedelta(minutes=180)
    for slot in _slots(client, doctor.pk, skip_days=0):
        start = parse_datetime(slot["starts_at"])
        assert start is not None
        assert start >= earliest - timedelta(seconds=5)


def test_review_window_longer_than_the_request_life_refuses(
    signed_in: dict[str, PortalClient],
) -> None:
    _settings(require_approval=True, request_ttl_hours=1, min_review_minutes=120)
    client = signed_in["a"]
    doctor = _doctor()
    slot = _slots(client, doctor.pk, skip_days=5)[0]
    response = _book(client, doctor.pk, slot["starts_at"])
    assert response.status_code == 409
    assert response.json()["code"] == "ONLINE_REVIEW_WINDOW_TOO_SHORT"


def test_staff_approval_and_rejection_show_to_the_patient(
    signed_in: dict[str, PortalClient],
) -> None:
    _settings(require_approval=True)
    client = signed_in["a"]
    doctor = _doctor()
    first, second = (
        _slots(client, doctor.pk, skip_days=4)[:1] + _slots(client, doctor.pk, skip_days=5)[:1]
    )
    one = _book(client, doctor.pk, first["starts_at"]).json()
    two = _book(client, doctor.pk, second["starts_at"]).json()
    clerk = User.objects.get(username="reception")
    vs.approve_online_booking(Appointment.objects.get(pk=one["id"]), actor=clerk)
    vs.reject_online_booking(Appointment.objects.get(pk=two["id"]), actor=clerk, note="full")
    listed = client.get("/api/portal/appointments").json()
    shown = {a["id"]: a["display_status"] for a in listed["upcoming"] + listed["past"]}
    assert shown[one["id"]] == "confirmed"
    assert shown[two["id"]] == "declined"


def test_doctors_not_offered_online_are_not_listed_nor_bookable(
    signed_in: dict[str, PortalClient],
) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    slot = _slots(client, doctor.pk, skip_days=2)[0]
    DoctorProfile.objects.filter(pk=doctor.pk).update(online_bookable=False)
    assert doctor.pk not in {d["id"] for d in client.get("/api/portal/doctors").json()}
    assert client.get(f"/api/portal/doctors/{doctor.pk}/days").status_code == 404
    assert _book(client, doctor.pk, slot["starts_at"]).status_code == 404


def test_time_off_is_never_offered(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    doctor = _doctor()
    slots = _slots(client, doctor.pk, skip_days=3)
    start = parse_datetime(slots[0]["starts_at"])
    assert start is not None
    admin = User.objects.get(username="admin")
    vs.add_time_off(
        admin, doctor.pk, starts_at=start, ends_at=start + timedelta(hours=1), reason_en="Away"
    )
    offered = [parse_datetime(s["starts_at"]) for s in _slots(client, doctor.pk, skip_days=3)]
    assert all(s is not None and not (start <= s < start + timedelta(hours=1)) for s in offered)
    refused = _book(client, doctor.pk, slots[0]["starts_at"])
    assert refused.status_code == 409


# --- reschedule -----------------------------------------------------------------------------


def test_reschedule_moves_the_booking_and_links_it(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    client = signed_in["a"]
    old_id = world["a"]["appointment"]["id"]
    old = Appointment.objects.get(pk=old_id)
    target = _slots(client, old.doctor_id, skip_days=6)[0]
    response = client.post(
        f"/api/portal/appointments/{old_id}/reschedule", {"starts_at": target["starts_at"]}
    )
    assert response.status_code == 201, response.content
    new = response.json()
    assert new["status"] == "booked"
    assert new["display_status"] == "confirmed"
    old.refresh_from_db()
    assert old.status == AppointmentStatus.RESCHEDULED
    moved = Appointment.objects.get(pk=new["id"])
    assert moved.rescheduled_from_id == old_id
    assert moved.source == old.source
    listed = client.get("/api/portal/appointments").json()
    assert {a["id"]: a["display_status"] for a in listed["past"]}[old_id] == "moved"
    # The old row is closed: moving it again is refused.
    again = client.post(
        f"/api/portal/appointments/{old_id}/reschedule", {"starts_at": target["starts_at"]}
    )
    assert again.status_code == 409
    assert again.json()["code"] == "APPOINTMENT_NOT_BOOKED"


def test_reschedule_follows_approval(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    _settings(require_approval=True)
    client = signed_in["a"]
    old_id = world["a"]["appointment"]["id"]
    doctor_id = Appointment.objects.get(pk=old_id).doctor_id
    target = _slots(client, doctor_id, skip_days=7)[0]
    response = client.post(
        f"/api/portal/appointments/{old_id}/reschedule", {"starts_at": target["starts_at"]}
    )
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "requested"


def test_reschedule_rules(signed_in: dict[str, PortalClient], world: dict[str, Any]) -> None:
    client = signed_in["a"]
    old_id = world["a"]["appointment"]["id"]
    doctor_id = Appointment.objects.get(pk=old_id).doctor_id
    target = _slots(client, doctor_id, skip_days=8)[0]
    url = f"/api/portal/appointments/{old_id}/reschedule"
    _settings(reschedule_allowed=False)
    off = client.post(url, {"starts_at": target["starts_at"]})
    assert off.status_code == 409
    assert off.json()["code"] == "PORTAL_RESCHEDULE_DISABLED"
    assert client.get("/api/portal/appointments").json()["upcoming"][0]["can_reschedule"] is False
    _settings(reschedule_allowed=True, reschedule_cutoff_hours=3)
    Appointment.objects.filter(pk=old_id).update(
        starts_at=timezone.now() + timedelta(hours=2),
        ends_at=timezone.now() + timedelta(hours=2, minutes=15),
    )
    late = client.post(url, {"starts_at": target["starts_at"]})
    assert late.status_code == 409
    assert late.json()["code"] == "PORTAL_RESCHEDULE_TOO_LATE"
    assert late.json()["details"] == {"cutoff_hours": 3}
    assert Appointment.objects.get(pk=old_id).status == AppointmentStatus.BOOKED
    # Another patient's booking is not found; a slot that is not offered is refused.
    other = signed_in["b"].post(url, {"starts_at": target["starts_at"]})
    assert other.status_code == 404
    Appointment.objects.filter(pk=old_id).update(
        starts_at=timezone.now() + timedelta(days=2),
        ends_at=timezone.now() + timedelta(days=2, minutes=15),
    )
    bad = parse_datetime(target["starts_at"])
    assert bad is not None
    odd = client.post(url, {"starts_at": (bad + timedelta(minutes=7)).isoformat()})
    assert odd.status_code == 409
    assert odd.json()["code"] == "PORTAL_SLOT_UNAVAILABLE"
    assert Appointment.objects.get(pk=old_id).status == AppointmentStatus.BOOKED


def test_reschedule_needs_booking_switched_on(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    _settings(online_booking_enabled=False)
    old_id = world["a"]["appointment"]["id"]
    response = signed_in["a"].post(
        f"/api/portal/appointments/{old_id}/reschedule",
        {"starts_at": (timezone.now() + timedelta(days=3)).isoformat()},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ONLINE_BOOKING_DISABLED"
