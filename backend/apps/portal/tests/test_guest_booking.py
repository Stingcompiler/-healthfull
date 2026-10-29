"""Guest booking without a file and the reception inbox (ADR 0029 A9, C, D, E, F, G; Phase 4a).

Public reads, the booking POST with its Idempotency-Key and proof-of-work, every abuse cap,
the guest sign-in (uniform 401, lock, per-address 429), the guest's view, cancel and
reschedule (the access follows the booking chain), the three-way cookie isolation, the staff
inbox (list, approve, decline, cancel on behalf, decline all from a phone, link a file, new
PIN, WhatsApp links), and the retention sweep. A guest booking creates no patient file, visit,
order, invoice or payment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any
from urllib.parse import unquote

import pytest
from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from django.utils import timezone

from apps.billing.models import Invoice
from apps.core.models import DoctorProfile, Notification, PublicSiteSettings, User
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.patients.models import Patient
from apps.payments.models import Payment
from apps.portal import conf
from apps.portal import guest as guest_services
from apps.portal.models import (
    GuestBookingAccess,
    GuestSession,
    IdempotentRequest,
    PortalEvent,
    UsedChallenge,
)
from apps.portal.tests.conftest import PortalClient
from apps.visits.models import Appointment, AppointmentStatus, Visit
from conftest import ApiClient
from domain import proof_of_work as dpow

pytestmark = pytest.mark.django_db

PHONE = "0912345678"
PHONE_KEY = "249912345678"


def _settings(**fields: Any) -> None:
    PublicSiteSettings.load()
    PublicSiteSettings.objects.filter(pk=PublicSiteSettings.SINGLETON_PK).update(**fields)


@pytest.fixture
def site(seeded: None) -> None:
    """Online and guest booking on, approval on, an easy proof-of-work and room for many
    requests from the one test address (the cap tests lower what they test)."""
    _settings(
        online_booking_enabled=True,
        guest_booking_enabled=True,
        require_approval=True,
        pow_difficulty_bits=2,
        max_requests_per_address_day=1000,
        max_pending_per_doctor_day=200,
        max_guest_bookings_per_phone=10,
    )


@pytest.fixture
def staff(site: None, make_user: Any) -> ApiClient:
    make_user("front", roles=["receptionist"])
    client = ApiClient()
    assert client.login("front").status_code == 200
    return client


def _doctors(client: PortalClient) -> list[int]:
    response = client.get("/api/portal/doctors")
    assert response.status_code == 200, response.content
    return [d["id"] for d in response.json()]


def _slots(client: PortalClient, doctor_id: int, day_index: int = 1) -> list[str]:
    days = client.get(f"/api/portal/doctors/{doctor_id}/days").json()
    day = days[min(day_index, len(days) - 1)]
    body = client.get(f"/api/portal/doctors/{doctor_id}/slots?on={day}").json()
    return [s["starts_at"] for s in body["slots"]]


def _solved(client: PortalClient) -> tuple[str, str]:
    challenge = client.get("/api/portal/challenge")
    assert challenge.status_code == 200, challenge.content
    body = challenge.json()
    return body["challenge"], dpow.solve(body["challenge"], body["bits"])


def _body(
    client: PortalClient, doctor_id: int, start: str, *, phone: str = PHONE, name: str = "Amna Ali"
) -> dict[str, Any]:
    token, nonce = _solved(client)
    return {
        "doctor_id": doctor_id,
        "starts_at": start,
        "contact_name": name,
        "contact_phone": phone,
        "challenge": token,
        "nonce": nonce,
    }


def _post(client: PortalClient, body: dict[str, Any], key: str | None = None) -> Any:
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post("/api/portal/guest-bookings", body, headers=headers)


def _book(client: PortalClient, doctor_id: int, start: str, **kw: Any) -> Any:
    return _post(client, _body(client, doctor_id, start, **kw), str(uuid.uuid4()))


def _sign_in(client: PortalClient, reference: str, pin: str) -> Any:
    return client.post("/api/portal/guest-bookings/sign-in", {"reference": reference, "pin": pin})


def _counts() -> tuple[int, ...]:
    return (
        Patient.objects.count(),
        Visit.objects.count(),
        ServiceLine.objects.count(),
        Invoice.objects.count(),
        Payment.objects.count(),
    )


# --- public reads -----------------------------------------------------------------------


def test_the_booking_reads_are_public_and_show_only_free_times(site: None) -> None:
    anonymous = PortalClient()
    doctors = _doctors(anonymous)
    assert doctors
    days = anonymous.get(f"/api/portal/doctors/{doctors[0]}/days").json()
    body = anonymous.get(f"/api/portal/doctors/{doctors[0]}/slots?on={days[1]}").json()
    assert body["slots"]
    assert all(set(slot) == {"starts_at", "ends_at"} for slot in body["slots"])
    # A doctor who is not offered online is not readable either.
    hidden = DoctorProfile.objects.exclude(pk__in=doctors).first() or DoctorProfile.objects.get(
        pk=doctors[0]
    )
    DoctorProfile.objects.filter(pk=hidden.pk).update(online_bookable=False)
    assert anonymous.get(f"/api/portal/doctors/{hidden.pk}/days").status_code == 404


# --- booking ----------------------------------------------------------------------------


def test_a_guest_request_gets_a_reference_and_pin_once_and_creates_nothing_else(
    site: None,
) -> None:
    client = PortalClient()
    doctor = _doctors(client)[0]
    start = _slots(client, doctor)[0]
    before = _counts()
    response = _book(client, doctor, start, name="  Amna   Ali ")
    assert response.status_code == 201, response.content
    body = response.json()
    assert _counts() == before  # no patient, visit, order, invoice or payment
    assert body["status"] == "requested"
    assert body["display_status"] == "awaiting_approval"
    assert body["replayed"] is False
    assert len(body["pin"]) == 6
    assert body["pin"].isdigit()
    assert len(body["reference"].replace("-", "")) == 10
    assert body["share_url"].startswith("https://wa.me/?text=")
    assert body["pin"] not in unquote(body["share_url"])
    row = Appointment.objects.get(starts_at=datetime.fromisoformat(start), doctor_id=doctor)
    assert (row.source, row.patient_id, row.contact_name) == ("guest", None, "Amna Ali")
    assert row.status == AppointmentStatus.REQUESTED
    assert row.expires_at is not None
    access = GuestBookingAccess.objects.get(appointment=row)
    assert access.reference == body["reference"].replace("-", "")
    assert body["pin"] not in access.pin_hash
    assert check_password(body["pin"], access.pin_hash)
    assert PortalEvent.objects.filter(kind="guest_booking_created").count() == 1
    # Reception is told; the slot is held.
    assert Notification.objects.filter(
        kind="online_booking_requested", user__username="reception"
    ).exists()
    assert start not in _slots(client, doctor)


def test_without_approval_a_guest_booking_is_confirmed_at_once(site: None) -> None:
    _settings(require_approval=False)
    client = PortalClient()
    doctor = _doctors(client)[0]
    response = _book(client, doctor, _slots(client, doctor)[0])
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "booked"
    assert not Notification.objects.filter(kind="online_booking_requested").exists()


def test_a_retry_with_the_same_key_answers_the_same_booking(site: None, staff: ApiClient) -> None:
    client = PortalClient()
    doctor = _doctors(client)[0]
    body = _body(client, doctor, _slots(client, doctor)[0])
    key = str(uuid.uuid4())
    first = _post(client, body, key)
    assert first.status_code == 201, first.content
    again = _post(client, body, key)
    assert again.status_code == 201, again.content
    assert again.json() | {"replayed": False} == first.json()
    assert again.json()["replayed"] is True
    assert Appointment.objects.filter(source="guest").count() == 1
    assert IdempotentRequest.objects.count() == 1
    assert first.json()["pin"] not in str(IdempotentRequest.objects.get().body)
    # The same key with another body is refused; no key at all is a bad request.
    other = dict(body, contact_name="Someone Else")
    mismatch = _post(client, other, key)
    assert (mismatch.status_code, mismatch.json()["code"]) == (409, "IDEMPOTENCY_MISMATCH")
    missing = _post(client, _body(client, doctor, _slots(client, doctor)[0]))
    assert (missing.status_code, missing.json()["code"]) == (400, "IDEMPOTENCY_KEY_REQUIRED")
    # After staff issue a new PIN the replay no longer shows the old one.
    booking = Appointment.objects.get(source="guest")
    reissued = staff.post(
        f"/api/visits/online-bookings/{booking.pk}/reissue-pin", {"reason": "lost it"}
    )
    assert reissued.status_code == 200, reissued.content
    assert _post(client, body, key).json()["pin"] is None


def test_the_proof_of_work_must_be_solved_fresh_and_used_once(site: None) -> None:
    client = PortalClient()
    doctor = _doctors(client)[0]
    starts = _slots(client, doctor)
    body = _body(client, doctor, starts[0])
    wrong = next(str(n) for n in range(10_000) if not dpow.solves(body["challenge"], str(n), 2))
    bad = _post(client, dict(body, nonce=wrong), str(uuid.uuid4()))
    assert (bad.status_code, bad.json()["code"]) == (409, "POW_INVALID")
    assert _post(client, body, str(uuid.uuid4())).status_code == 201
    # The same solved challenge under a new key: spent.
    reused = _post(client, dict(body, starts_at=starts[1]), str(uuid.uuid4()))
    assert (reused.status_code, reused.json()["code"]) == (409, "POW_ALREADY_USED")
    # Expired, and weaker than the difficulty in force.
    old = dpow.issue(
        guest_services._pow_key(),
        challenge_id="00000000000000aa",
        expires=int(timezone.now().timestamp()) - 1,
        bits=2,
    )
    expired = _post(
        client,
        dict(body, challenge=old.token, nonce=dpow.solve(old.token, 2), starts_at=starts[2]),
        str(uuid.uuid4()),
    )
    assert (expired.status_code, expired.json()["code"]) == (409, "POW_EXPIRED")
    weak = _body(client, doctor, starts[2])
    _settings(pow_difficulty_bits=12)
    refused = _post(client, weak, str(uuid.uuid4()))
    assert (refused.status_code, refused.json()["code"]) == (409, "POW_INVALID")
    assert UsedChallenge.objects.count() == 1


def test_the_phone_cap_counts_every_typing_of_one_number(site: None) -> None:
    _settings(max_guest_bookings_per_phone=2)
    client = PortalClient()
    doctors = _doctors(client)
    assert len(doctors) >= 2
    a = _slots(client, doctors[0])
    assert _book(client, doctors[0], a[0], phone="0912 345 678").status_code == 201
    same_day = _book(client, doctors[0], a[1], phone="+249912345678")
    assert (same_day.status_code, same_day.json()["code"]) == (409, "PORTAL_ALREADY_BOOKED")
    b_ = _slots(client, doctors[1])
    assert _book(client, doctors[1], b_[0], phone="00249912345678").status_code == 201
    third = _book(client, doctors[0], _slots(client, doctors[0], day_index=2)[0], phone="912345678")
    assert third.status_code == 409
    assert third.json()["code"] == "GUEST_PHONE_LIMIT"
    assert third.json()["details"]["limit"] == 2
    # Another number is not affected.
    assert _book(client, doctors[0], a[2], phone="0911111111").status_code == 201


def test_requests_per_doctor_day_are_capped_while_approval_is_on(site: None) -> None:
    _settings(max_pending_per_doctor_day=1)
    client = PortalClient()
    doctor = _doctors(client)[0]
    starts = _slots(client, doctor)
    assert _book(client, doctor, starts[0], phone="0911000001").status_code == 201
    full = _book(client, doctor, starts[1], phone="0911000002")
    assert (full.status_code, full.json()["code"]) == (409, "ONLINE_DOCTOR_DAY_FULL")
    # Confirmed bookings are not requests: without approval the cap does not apply.
    _settings(require_approval=False)
    assert _book(client, doctor, starts[1], phone="0911000003").status_code == 201


def test_requests_per_address_per_day_answer_429_and_raise_the_difficulty(site: None) -> None:
    _settings(max_requests_per_address_day=2)
    client = PortalClient()
    doctor = _doctors(client)[0]
    starts = _slots(client, doctor)
    first_bits = client.get("/api/portal/challenge").json()["bits"]
    assert _book(client, doctor, starts[0], phone="0911000001").status_code == 201
    assert client.get("/api/portal/challenge").json()["bits"] == first_bits + 2
    assert _book(client, doctor, starts[1], phone="0911000002").status_code == 201
    limited = _book(client, doctor, starts[2], phone="0911000003")
    assert (limited.status_code, limited.json()["code"]) == (429, "RATE_LIMITED")
    assert PortalEvent.objects.filter(kind="booking_throttled").exists()


def test_guest_booking_switches(site: None) -> None:
    client = PortalClient()
    doctor = _doctors(client)[0]
    body = _body(client, doctor, _slots(client, doctor)[0])
    _settings(guest_booking_enabled=False)
    for response in (client.get("/api/portal/challenge"), _post(client, body, str(uuid.uuid4()))):
        assert (response.status_code, response.json()["code"]) == (409, "GUEST_BOOKING_DISABLED")
    _settings(guest_booking_enabled=True, online_booking_enabled=False)
    response = _post(client, body, str(uuid.uuid4()))
    assert (response.status_code, response.json()["code"]) == (409, "ONLINE_BOOKING_DISABLED")


def test_a_guest_cannot_name_an_empty_person_or_a_non_phone(site: None) -> None:
    client = PortalClient()
    doctor = _doctors(client)[0]
    start = _slots(client, doctor)[0]
    assert _book(client, doctor, start, name="   ").json()["code"] == "GUEST_NAME_REQUIRED"
    assert _book(client, doctor, start, phone="call me").json()["code"] == "GUEST_PHONE_INVALID"


# --- the guest's sign-in and booking ----------------------------------------------------


def _booked(client: PortalClient, **kw: Any) -> dict[str, Any]:
    doctor = _doctors(client)[0]
    response = _book(client, doctor, _slots(client, doctor)[0], **kw)
    assert response.status_code == 201, response.content
    body: dict[str, Any] = response.json()
    return body


def test_sign_in_refuses_uniformly_and_locks_after_five_wrong_pins(
    site: None, staff: ApiClient
) -> None:
    booker = PortalClient()
    made = _booked(booker)
    wrong_pin = "000000" if made["pin"] != "000000" else "111111"
    visitor = PortalClient()
    refusals = [
        _sign_in(visitor, "ZZZZZ-ZZZZZ", made["pin"]),  # unknown reference
        _sign_in(visitor, "not a ref", made["pin"]),  # malformed
        _sign_in(visitor, made["reference"], "12"),  # malformed PIN
    ]
    refusals += [_sign_in(visitor, made["reference"].lower(), wrong_pin) for _ in range(5)]
    for response in refusals:
        assert response.status_code == 401
        assert response.json() == {
            "code": "GUEST_INVALID_CREDENTIALS",
            "message": "The booking reference or PIN is not right",
            "details": {},
        }
    access = GuestBookingAccess.objects.get()
    assert access.locked_at is not None
    assert access.failed_attempts == 5
    assert PortalEvent.objects.filter(kind="guest_locked").count() == 1
    # Locked: even the right PIN answers the same 401.
    assert _sign_in(visitor, made["reference"], made["pin"]).status_code == 401
    # Reception issues a new PIN: it opens the booking, the old one does not.
    appointment = access.appointment_id
    no_reason = staff.post(
        f"/api/visits/online-bookings/{appointment}/reissue-pin", {"reason": " "}
    )
    assert no_reason.json()["code"] == "REASON_REQUIRED"
    reissued = staff.post(
        f"/api/visits/online-bookings/{appointment}/reissue-pin", {"reason": "locked out"}
    ).json()
    assert len(reissued["pin"]) == 6
    assert reissued["booking"]["guest_locked"] is False
    assert _sign_in(visitor, made["reference"], made["pin"]).status_code == 401
    opened = _sign_in(visitor, made["reference"], reissued["pin"])
    assert opened.status_code == 200, opened.content
    assert visitor.django.cookies[conf.GUEST_COOKIE_NAME]["path"] == "/api/portal/guest"
    assert visitor.get("/api/portal/guest/booking").json()["reference"] == made["reference"]
    # A further new PIN ends the open session.
    staff.post(f"/api/visits/online-bookings/{appointment}/reissue-pin", {"reason": "again"})
    assert visitor.get("/api/portal/guest/booking").status_code == 401
    assert PortalEvent.objects.filter(kind="guest_pin_reissued").count() == 2


def test_failed_guest_sign_ins_are_limited_per_address(site: None, settings: Any) -> None:
    settings.GUEST_LOGIN_IP_MAX_FAILURES = 3
    made = _booked(PortalClient())
    visitor = PortalClient()
    for _ in range(3):
        assert _sign_in(visitor, "ZZZZZZZZZZ", "123456").status_code == 401
    limited = _sign_in(visitor, made["reference"], made["pin"])
    assert (limited.status_code, limited.json()["code"]) == (429, "RATE_LIMITED")
    assert PortalEvent.objects.filter(kind="guest_throttled").exists()


def test_the_guest_sees_and_cancels_their_booking_and_signs_out(site: None) -> None:
    client = PortalClient()
    made = _booked(client)
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    view = client.get("/api/portal/guest/booking").json()
    assert view["status"] == "requested"
    assert view["can_cancel"] is True
    assert view["can_reschedule"] is False  # only a confirmed booking moves
    assert view["phone_masked"].endswith("678")
    assert PHONE_KEY not in view["phone_masked"]
    moved = client.post("/api/portal/guest/booking/reschedule", {"starts_at": made["starts_at"]})
    assert (moved.status_code, moved.json()["code"]) == (409, "APPOINTMENT_NOT_BOOKED")
    cancelled = client.post("/api/portal/guest/booking/cancel")
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["display_status"] == "cancelled_by_you"
    assert Notification.objects.filter(kind="online_booking_cancelled_by_patient").exists()
    again = client.post("/api/portal/guest/booking/cancel")
    assert (again.status_code, again.json()["code"]) == (409, "APPOINTMENT_NOT_BOOKED")
    assert client.post("/api/portal/guest/sign-out").status_code == 204
    assert client.get("/api/portal/guest/booking").status_code == 401
    assert client.post("/api/portal/guest/sign-out").status_code == 204  # idempotent


def test_a_reschedule_moves_the_guest_access_along_the_chain(site: None) -> None:
    _settings(require_approval=False)
    client = PortalClient()
    made = _booked(client)
    assert made["status"] == "booked"
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    doctor = made["doctor"]["id"]
    target = _slots(client, doctor, day_index=3)[0]
    moved = client.post("/api/portal/guest/booking/reschedule", {"starts_at": target})
    assert moved.status_code == 200, moved.content
    assert datetime.fromisoformat(moved.json()["starts_at"]) == datetime.fromisoformat(target)
    old = Appointment.objects.get(starts_at=datetime.fromisoformat(made["starts_at"]))
    new = Appointment.objects.get(rescheduled_from=old)
    assert old.status == AppointmentStatus.RESCHEDULED
    access = GuestBookingAccess.objects.get()
    assert access.appointment_id == new.pk
    assert PortalEvent.objects.filter(kind="booking_rescheduled").count() == 1
    # The same reference and PIN open the moved booking; the earlier row has no access.
    other = PortalClient()
    assert (
        _sign_in(other, made["reference"], made["pin"]).json()["starts_at"]
        == moved.json()["starts_at"]
    )
    assert not GuestBookingAccess.objects.filter(appointment=old).exists()


def test_guest_patient_and_staff_cookies_never_cross(
    site: None, staff: ApiClient, world: dict[str, Any], signed_in: dict[str, PortalClient]
) -> None:
    guest_client = PortalClient()
    made = _booked(guest_client)
    assert _sign_in(guest_client, made["reference"], made["pin"]).status_code == 200
    guest_token = guest_client.django.cookies[conf.GUEST_COOKIE_NAME].value
    patient = signed_in["a"]
    patient_token = patient.portal_cookie
    assert patient_token is not None
    # The guest cookie opens no patient and no staff operation.
    for path in ("/api/portal/me", "/api/portal/appointments", "/api/visits/online-bookings"):
        assert guest_client.get(path).status_code == 401, path
    # A patient's cookie and a staff session open no guest operation.
    for client in (patient, staff, PortalClient()):
        assert client.get("/api/portal/guest/booking").status_code == 401
        assert client.post("/api/portal/guest/booking/cancel").status_code == 401
    # A token of one kind under the other cookie's name is not a session either.
    swapped = PortalClient()
    swapped.django.cookies[conf.COOKIE_NAME] = guest_token
    assert swapped.get("/api/portal/me").status_code == 401
    swapped.django.cookies[conf.GUEST_COOKIE_NAME] = patient_token
    assert swapped.get("/api/portal/guest/booking").status_code == 401
    # Staff with the inbox permission still read the inbox; the guest's booking is there.
    assert staff.get("/api/visits/online-bookings").status_code == 200


# --- the reception inbox ----------------------------------------------------------------


def test_the_inbox_lists_requests_with_a_whatsapp_link_and_approves_them(
    site: None, staff: ApiClient, make_user: Any
) -> None:
    client = PortalClient()
    made = _booked(client)
    rows = staff.get("/api/visits/online-bookings").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["reference"] == made["reference"]
    assert row["source"] == "guest"
    assert row["display_status"] == "awaiting_approval"
    assert row["phone_open_requests"] == 1
    assert row["whatsapp_url"].startswith(f"https://wa.me/{PHONE_KEY}?text=")
    text = unquote(row["whatsapp_url"].split("?text=", 1)[1])
    assert made["reference"] in text
    assert made["pin"] not in text
    approved = staff.post(f"/api/visits/online-bookings/{row['id']}/approve")
    assert approved.status_code == 200, approved.content
    assert approved.json()["status"] == "booked"
    assert "confirmed" in unquote(approved.json()["whatsapp_url"])
    # Edges: approving or declining a confirmed booking is refused.
    for action in ("approve", "reject"):
        refused = staff.post(f"/api/visits/online-bookings/{row['id']}/{action}", {})
        assert refused.json()["code"] == "APPOINTMENT_NOT_REQUESTED", action
    assert staff.get("/api/visits/online-bookings").json() == []
    booked = staff.get("/api/visits/online-bookings?status=booked").json()
    assert [r["id"] for r in booked] == [row["id"]]
    # Without the permission: 403.
    make_user("doc2", roles=["doctor"])
    doctor = ApiClient()
    assert doctor.login("doc2").status_code == 200
    assert doctor.get("/api/visits/online-bookings").status_code == 403


def test_reception_declines_every_open_request_of_one_phone(site: None, staff: ApiClient) -> None:
    client = PortalClient()
    doctors = _doctors(client)
    ids = []
    for doctor, phone in ((doctors[0], "0912345678"), (doctors[1], "+249 912 345 678")):
        response = _book(client, doctor, _slots(client, doctor)[0], phone=phone)
        ids.append(Appointment.objects.get(contact_phone=" ".join(phone.split())).pk)
        assert response.status_code == 201
    other = _book(
        client, doctors[0], _slots(client, doctors[0], day_index=2)[0], phone="0911111111"
    )
    assert other.status_code == 201
    done = staff.post(
        f"/api/visits/online-bookings/{ids[0]}/reject-phone",
        {"reason_code": "ONLINE_REJECTED", "note": "flood from one number"},
    )
    assert done.status_code == 200, done.content
    assert done.json()["rejected"] == 2
    assert {r["id"] for r in done.json()["bookings"]} == set(ids)
    assert all(r["cancel_note"] == "flood from one number" for r in done.json()["bookings"])
    assert all(r["display_status"] == "declined" for r in done.json()["bookings"])
    for pk in ids:
        row = Appointment.objects.get(pk=pk)
        assert row.status == AppointmentStatus.CANCELLED
        assert row.cancelled_by is not None
        assert row.cancel_reason is not None
    assert Appointment.objects.get(contact_phone="0911111111").status == "requested"


def test_reception_cancels_on_behalf_and_links_a_file(site: None, staff: ApiClient) -> None:
    _settings(require_approval=False)
    client = PortalClient()
    made = _booked(client)
    pk = Appointment.objects.get(source="guest").pk
    first, second = b.patient(phone="0912345678"), b.patient()
    link = f"/api/visits/online-bookings/{pk}/link-patient"
    linked = staff.post(link, {"patient_id": first.pk})
    assert linked.status_code == 200, linked.content
    assert linked.json()["patient"]["id"] == first.pk
    assert staff.post(link, {"patient_id": first.pk}).status_code == 200  # the same file again
    refused = staff.post(link, {"patient_id": second.pk})
    assert (refused.status_code, refused.json()["code"]) == (409, "APPOINTMENT_PATIENT_MISMATCH")
    # The guest still sees their booking; a cancellation for them needs a reason.
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    cancel = f"/api/visits/online-bookings/{pk}/cancel"
    assert staff.post(cancel, {"reason_code": ""}).status_code in (409, 422)
    done = staff.post(cancel, {"reason_code": "PATIENT_REQUEST", "note": "called the desk"})
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "cancelled"
    assert client.get("/api/portal/guest/booking").json()["display_status"] == "cancelled_by_you"
    # A cancelled booking without a file cannot be linked.
    unlinked = _booked(client, phone="0911111111")
    other_pk = GuestBookingAccess.objects.get(
        reference=unlinked["reference"].replace("-", "")
    ).appointment_id
    staff.post(f"/api/visits/online-bookings/{other_pk}/cancel", {"reason_code": "PATIENT_REQUEST"})
    late = staff.post(
        f"/api/visits/online-bookings/{other_pk}/link-patient", {"patient_id": first.pk}
    )
    assert late.json()["code"] == "APPOINTMENT_NOT_BOOKED"


def test_reissue_needs_a_current_guest_booking(site: None, staff: ApiClient) -> None:
    _settings(require_approval=False)
    client = PortalClient()
    made = _booked(client)
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    target = _slots(client, made["doctor"]["id"], day_index=3)[0]
    assert (
        client.post("/api/portal/guest/booking/reschedule", {"starts_at": target}).status_code
        == 200
    )
    old = Appointment.objects.get(status=AppointmentStatus.RESCHEDULED)
    response = staff.post(f"/api/visits/online-bookings/{old.pk}/reissue-pin", {"reason": "x"})
    assert (response.status_code, response.json()["code"]) == (409, "NOT_A_GUEST_BOOKING")


# --- retention and housekeeping ---------------------------------------------------------


def test_retention_anonymizes_old_unlinked_guest_bookings_and_their_chain(site: None) -> None:
    _settings(require_approval=False, guest_retention_days=90)
    client = PortalClient()
    made = _booked(client)
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    target = _slots(client, made["doctor"]["id"], day_index=3)[0]
    assert (
        client.post("/api/portal/guest/booking/reschedule", {"starts_at": target}).status_code
        == 200
    )
    assert client.post("/api/portal/guest/booking/cancel").status_code == 200
    recent = _booked(PortalClient(), phone="0911111111")
    recent_pk = GuestBookingAccess.objects.get(
        reference=recent["reference"].replace("-", "")
    ).appointment_id
    Appointment.objects.filter(pk=recent_pk).update(
        status=AppointmentStatus.CANCELLED,
        cancelled_at=timezone.now(),
        cancelled_by=User.objects.get(username="admin"),
    )
    long_ago = timezone.now() - timedelta(days=91)
    Appointment.objects.filter(status=AppointmentStatus.CANCELLED).exclude(pk=recent_pk).update(
        cancelled_at=long_ago
    )
    out = StringIO()
    call_command("maintenance", stdout=out)
    assert "anonymized 2 old guest booking(s)" in out.getvalue()
    chain = Appointment.objects.filter(source="guest").exclude(pk=recent_pk)
    assert chain.count() == 2
    for row in chain:
        assert (row.contact_name, row.contact_phone, row.notes) == ("(removed)", "", "")
    assert not GuestBookingAccess.objects.exclude(appointment_id=recent_pk).exists()
    assert not GuestSession.objects.exclude(access__appointment_id=recent_pk).exists()
    assert Appointment.objects.get(pk=recent_pk).contact_name == "Amna Ali"
    event = PortalEvent.objects.get(kind="guest_purged")
    assert event.details == {"bookings": 2, "accesses": 1}
    # Idempotent: a second run touches nothing.
    assert guest_services.anonymize_old_guest_bookings() == 0


def test_housekeeping_drops_old_answers_challenges_and_idle_guest_sessions(site: None) -> None:
    client = PortalClient()
    made = _booked(client)
    assert _sign_in(client, made["reference"], made["pin"]).status_code == 200
    later = timezone.now() + timedelta(days=2)
    ended, answers, spent = guest_services.purge_stale(later)
    assert (ended, answers, spent) == (1, 1, 1)
    assert IdempotentRequest.objects.count() == 0
    assert UsedChallenge.objects.count() == 0
    assert GuestSession.objects.get().end_reason == "expired"
    assert datetime.now(UTC) < later


def test_a_signed_in_patients_request_reaches_the_inbox_with_their_phone(
    site: None, staff: ApiClient, world: dict[str, Any], signed_in: dict[str, PortalClient]
) -> None:
    client = signed_in["a"]
    doctor = _doctors(client)[0]
    start = _slots(client, doctor, day_index=2)[0]
    booked = client.post("/api/portal/appointments", {"doctor_id": doctor, "starts_at": start})
    assert booked.status_code == 201, booked.content
    assert Notification.objects.filter(kind="online_booking_requested").exists()
    rows = staff.get("/api/visits/online-bookings").json()
    row = next(r for r in rows if r["id"] == booked.json()["id"])
    assert row["source"] == "portal"
    assert row["reference"] is None
    assert row["patient"]["id"] == world["a"]["patient"]["id"]
    phone = Patient.objects.get(pk=world["a"]["patient"]["id"]).phone
    expected = guest_services.dguest.phone_key(phone)
    assert row["whatsapp_url"].startswith(f"https://wa.me/{expected}?text=")
    # No guest reference or PIN for a patient's booking.
    reissue = staff.post(f"/api/visits/online-bookings/{row['id']}/reissue-pin", {"reason": "x"})
    assert reissue.json()["code"] == "NOT_A_GUEST_BOOKING"
    # A patient's cancellation tells reception too.
    assert client.post(f"/api/portal/appointments/{row['id']}/cancel").status_code == 200
    assert Notification.objects.filter(kind="online_booking_cancelled_by_patient").exists()
