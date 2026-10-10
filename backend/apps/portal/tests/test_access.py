"""Object-level access across two patients: every portal endpoint serves only the signed-in
person's rows, and another person's id answers 404 (never 403)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.portal.api import PATIENT_OPERATIONS
from apps.portal.tests.conftest import PortalClient
from apps.visits.models import Appointment, AppointmentStatus

pytestmark = pytest.mark.django_db

NOT_FOUND = {"code": "NOT_FOUND", "message": "Not found", "details": {}}


def _own_and_other(world: dict[str, Any], key: str, me: str) -> tuple[Any, Any]:
    other = "b" if me == "a" else "a"
    return world[me][key], world[other][key]


@pytest.mark.parametrize("me", ["a", "b"])
def test_results_are_own_and_approved_only(
    signed_in: dict[str, PortalClient], world: dict[str, Any], me: str
) -> None:
    client = signed_in[me]
    own, other = _own_and_other(world, "approved_line", me)
    listed = client.get("/api/portal/results").json()
    assert [r["line_id"] for r in listed] == [own]
    assert listed[0]["amended"] is False
    detail = client.get(f"/api/portal/results/{own}")
    assert detail.status_code == 200
    assert {v["parameter_code"] for v in detail.json()["values"]} == {"WBC", "HGB", "PLT"}
    # Someone else's approved result, and one's own unapproved draft: both simply not found.
    for line in (other, world[me]["draft_line"]):
        response = client.get(f"/api/portal/results/{line}")
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


def test_an_amended_result_shows_the_latest_approved_version(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    from apps.core.models import User
    from apps.lab import services as lab
    from apps.orders.models import ServiceLine

    sup = User.objects.get(username="labsup")
    line = ServiceLine.objects.get(pk=world["a"]["draft_line"])
    lab.approve_results(line, actor=sup)
    lab.start_amendment(line, actor=sup, reason_code="ENTRY_ERROR", note="wrong slide")
    lab.enter_results(line, values={"MP": "negative"}, actor=sup)
    # While the amendment is a draft, the portal still shows the approved first version.
    client = signed_in["a"]
    first = client.get(f"/api/portal/results/{line.pk}").json()
    assert first["amended"] is False
    assert [v["value"] for v in first["values"]] == ["positive"]
    lab.approve_results(line, actor=sup)
    detail = client.get(f"/api/portal/results/{world['a']['draft_line']}").json()
    assert detail["amended"] is True
    assert [v["value"] for v in detail["values"]] == ["negative"]
    assert detail["comment"] == ""


@pytest.mark.parametrize("me", ["a", "b"])
def test_invoices_are_own_and_show_no_payer_internals(
    signed_in: dict[str, PortalClient], world: dict[str, Any], me: str
) -> None:
    client = signed_in[me]
    own, other = _own_and_other(world, "invoice", me)
    listed = client.get("/api/portal/invoices").json()
    assert [i["id"] for i in listed] == [own["id"]]
    detail = client.get(f"/api/portal/invoices/{own['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["outstanding"] == "0.00"
    assert body["paid"] == body["patient_due"]
    text = json.dumps(body).lower()
    for internal in ("payer", "coverage", "claim", "gross", "price_list", "discount"):
        assert internal not in text
    assert client.get(f"/api/portal/invoices/{other['id']}").json() == NOT_FOUND


@pytest.mark.parametrize("me", ["a", "b"])
def test_receipts_are_own(
    signed_in: dict[str, PortalClient], world: dict[str, Any], me: str
) -> None:
    client = signed_in[me]
    own, other = _own_and_other(world, "payment", me)
    listed = client.get("/api/portal/receipts").json()
    assert [r["id"] for r in listed] == [own["id"]]
    assert listed[0]["status"] == "valid"
    detail = client.get(f"/api/portal/receipts/{own['id']}").json()
    assert detail["invoices"][0]["id"] == world[me]["invoice"]["id"]
    assert "cashier" not in json.dumps(detail)
    assert client.get(f"/api/portal/receipts/{other['id']}").json() == NOT_FOUND


@pytest.mark.parametrize("me", ["a", "b"])
def test_appointments_are_own_and_others_cannot_be_cancelled(
    signed_in: dict[str, PortalClient], world: dict[str, Any], me: str
) -> None:
    client = signed_in[me]
    own, other = _own_and_other(world, "appointment", me)
    listed = client.get("/api/portal/appointments").json()
    assert [a["id"] for a in listed["upcoming"]] == [own["id"]]
    response = client.post(f"/api/portal/appointments/{other['id']}/cancel")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert Appointment.objects.get(pk=other["id"]).status == AppointmentStatus.BOOKED


@pytest.mark.parametrize("me", ["a", "b"])
def test_prescriptions_profile_balance_and_home_are_own(
    signed_in: dict[str, PortalClient], world: dict[str, Any], me: str
) -> None:
    client = signed_in[me]
    other = "b" if me == "a" else "a"
    rx = client.get("/api/portal/prescriptions").json()
    assert [v["visit_number"] for v in rx["visits"]] == [world[me]["visit"]["number"]]
    item = rx["visits"][0]["items"][0]
    assert item["dose"] == "500 mg"
    assert item["instructions"] == "After meals"
    assert item["state"] == "not_dispensed"
    me_body = client.get("/api/portal/me").json()
    assert me_body["file_no"] == world[me]["patient"]["file_no"]
    assert me_body["file_no"] != world[other]["patient"]["file_no"]
    balance = client.get("/api/portal/balance").json()
    assert balance["outstanding"] == "0.00"
    home = client.get("/api/portal/summary").json()
    assert home["next_appointment"]["id"] == world[me]["appointment"]["id"]
    assert [r["line_id"] for r in home["latest_results"]] == [world[me]["approved_line"]]


def _patient_paths(world: dict[str, Any]) -> dict[str, tuple[str, str]]:
    a = world["a"]
    return {
        "portal_get_me": ("get", "/api/portal/me"),
        "portal_get_summary": ("get", "/api/portal/summary"),
        "portal_list_appointments": ("get", "/api/portal/appointments"),
        "portal_book_appointment": ("post", "/api/portal/appointments"),
        "portal_cancel_appointment": (
            "post",
            f"/api/portal/appointments/{a['appointment']['id']}/cancel",
        ),
        "portal_list_doctors": ("get", "/api/portal/doctors"),
        "portal_list_booking_days": ("get", "/api/portal/doctors/1/days"),
        "portal_list_slots": ("get", "/api/portal/doctors/1/slots?on=2026-10-10"),
        "portal_list_results": ("get", "/api/portal/results"),
        "portal_get_result": ("get", f"/api/portal/results/{a['approved_line']}"),
        "portal_get_prescriptions": ("get", "/api/portal/prescriptions"),
        "portal_list_invoices": ("get", "/api/portal/invoices"),
        "portal_get_invoice": ("get", f"/api/portal/invoices/{a['invoice']['id']}"),
        "portal_list_receipts": ("get", "/api/portal/receipts"),
        "portal_get_receipt": ("get", f"/api/portal/receipts/{a['payment']['id']}"),
        "portal_get_balance": ("get", "/api/portal/balance"),
    }


def test_every_patient_operation_needs_a_portal_session(world: dict[str, Any]) -> None:
    paths = _patient_paths(world)
    assert set(paths) == PATIENT_OPERATIONS  # a new patient endpoint must be added here
    anonymous = PortalClient()
    for op, (method, path) in paths.items():
        response = getattr(anonymous, method)(path)
        assert response.status_code == 401, (op, response.content)
        assert response.json()["code"] == "NOT_AUTHENTICATED"
