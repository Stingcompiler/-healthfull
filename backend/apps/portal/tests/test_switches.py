"""Public site switches on the portal (ADR 0028, 0029; plan Phase 1).

Every operation of ``/api/portal`` is called with each switch off. The operations a switch
governs answer its exact code; every other one is unaffected (never a switch code, never a
500). The table below must name every portal operation, so a new one is classified on purpose.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.core import services as core
from apps.core.models import PublicSiteSettings, User
from apps.patients.tests.test_contract import module_operations
from apps.portal.api import PATIENT_OPERATIONS
from apps.portal.models import PortalAccessCode, PortalSession
from apps.portal.tests.conftest import PortalClient
from conftest import ApiClient

pytestmark = pytest.mark.django_db(transaction=False)

SWITCH_CODES = {"SITE_DISABLED", "ONLINE_BOOKING_DISABLED", "PORTAL_DISABLED"}

BOOKING_OPERATIONS = {
    "portal_book_appointment",
    "portal_list_doctors",
    "portal_list_booking_days",
    "portal_list_slots",
}
ISSUE_OPERATIONS = {"portal_issue_access_code", "portal_issue_patient_access_code"}

#: switch field -> {operation id: (status, code)}; operations not named are unaffected.
EXPECTED: dict[str, dict[str, tuple[int, str]]] = {
    "site_enabled": {
        "portal_get_center_page": (404, "SITE_DISABLED"),
        # The website's images belong to the website (ADR 0028 decision 3, Phase 2).
        "portal_get_center_media": (404, "SITE_DISABLED"),
    },
    "online_booking_enabled": dict.fromkeys(BOOKING_OPERATIONS, (409, "ONLINE_BOOKING_DISABLED")),
    "patient_tracking_enabled": dict.fromkeys(
        PATIENT_OPERATIONS | {"portal_login"} | ISSUE_OPERATIONS, (409, "PORTAL_DISABLED")
    ),
}

#: Operations that never depend on a switch (named, so the table covers the whole router).
UNAFFECTED = {
    "portal_get_ping",
    "portal_get_session",
    "portal_logout",
    "portal_verify_receipt",
    "portal_get_center_logo",
    "portal_get_center_identity",
    "portal_list_patient_access_codes",
    "portal_revoke_access_code",
}

STAFF_OPERATIONS = {
    "portal_get_ping",
    "portal_issue_access_code",
    "portal_list_patient_access_codes",
    "portal_issue_patient_access_code",
    "portal_revoke_access_code",
}


def _admin() -> User:
    return User.objects.get(username="admin")


def _switch(field: str, value: bool) -> None:
    core.update_public_site_settings(_admin(), reason="test", **{field: value})


def test_the_table_classifies_every_portal_operation() -> None:
    governed = set().union(*(set(ops) for ops in EXPECTED.values()))
    every = set(module_operations("/api/portal").values())
    assert governed | UNAFFECTED == every
    assert not governed & UNAFFECTED


def _url(path: str, ids: dict[str, Any]) -> str:
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(ids[m.group(1)]), path)


def _call(
    op_id: str,
    method: str,
    path: str,
    *,
    patient: ApiClient,
    staff: ApiClient,
    w: dict[str, Any],
) -> Any:
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    code = PortalAccessCode.objects.filter(patient_id=w["patient"]["id"]).first()
    ids = {
        "appointment_id": w["appointment"]["id"],
        "doctor_id": 1,
        "line_id": w["approved_line"],
        "invoice_id": w["invoice"]["id"],
        "payment_id": w["payment"]["id"],
        "patient_id": w["patient"]["id"],
        "code_id": code.pk if code else 1,
        "media_id": 1,
    }
    url = _url(path, ids)
    client: ApiClient = staff if op_id in STAFF_OPERATIONS else patient
    bodies: dict[str, Any] = {
        "portal_login": {
            "file_no": w["patient"]["file_no"],
            "phone": w["patient"]["phone"],
            "code": "WRONG-CODE",
        },
        "portal_book_appointment": {
            "doctor_id": 1,
            "starts_at": (timezone.now() + timedelta(days=2)).isoformat(),
        },
        "portal_issue_access_code": {"payment_id": w["payment"]["id"]},
        "portal_revoke_access_code": {"note": "lost slip"},
    }
    if op_id == "portal_list_slots":
        url += f"?on={tomorrow}"
    if op_id == "portal_verify_receipt":
        url += f"?receipt={w['payment']['number']}&token={w['verify_token']}"
    if method == "get":
        return client.get(url)
    return client.post(url, bodies.get(op_id, {}))


def _order(item: tuple[tuple[str, str], str]) -> tuple[int, str, str]:
    """Patient and public operations first, then sign-out, then staff ones (issuing or
    revoking a code ends the patient's session, which would hide what the switch does)."""
    (method, path), op_id = item
    rank = 2 if op_id in STAFF_OPERATIONS else 1 if op_id == "portal_logout" else 0
    return rank, path, method


@pytest.mark.parametrize("field", sorted(EXPECTED))
def test_each_switch_off_answers_its_exact_code_and_nothing_else(
    field: str,
    world: dict[str, dict[str, Any]],
    signed_in: dict[str, PortalClient],
    make_user: Any,
) -> None:
    make_user("desk", roles=["cashier", "receptionist"])
    staff = ApiClient()
    assert staff.login("desk").status_code == 200
    _switch(field, False)
    expected = EXPECTED[field]
    for (method, path), op_id in sorted(module_operations("/api/portal").items(), key=_order):
        response = _call(op_id, method, path, patient=signed_in["a"], staff=staff, w=world["a"])
        is_json = response.get("Content-Type", "").startswith("application/json")
        body = response.json() if response.content and is_json else {}
        if op_id in expected:
            status, code = expected[op_id]
            assert (response.status_code, body.get("code")) == (status, code), (op_id, body)
        else:
            assert response.status_code < 500, (op_id, response.status_code)
            if isinstance(body, dict):
                assert body.get("code") not in SWITCH_CODES, op_id


def test_patient_operations_answer_portal_disabled_even_without_a_session(
    world: dict[str, dict[str, Any]],
) -> None:
    anonymous = PortalClient()
    w = world["a"]
    patient_ops = {
        key: op for key, op in module_operations("/api/portal").items() if op in PATIENT_OPERATIONS
    }
    for (method, path), op_id in patient_ops.items():
        response = _call(op_id, method, path, patient=anonymous, staff=anonymous, w=w)
        assert response.status_code == 401, (op_id, response.status_code)
    _switch("patient_tracking_enabled", False)
    for (method, path), op_id in patient_ops.items():
        response = _call(op_id, method, path, patient=anonymous, staff=anonymous, w=w)
        assert (response.status_code, response.json()["code"]) == (409, "PORTAL_DISABLED"), op_id


def test_turning_tracking_off_ends_every_live_session_and_session_reads_signed_out(
    signed_in: dict[str, PortalClient],
) -> None:
    assert PortalSession.objects.filter(ended_at__isnull=True).count() == 2
    _switch("patient_tracking_enabled", False)
    assert not PortalSession.objects.filter(ended_at__isnull=True).exists()
    assert set(PortalSession.objects.values_list("end_reason", flat=True)) == {"disabled"}
    response = signed_in["a"].get("/api/portal/session")
    assert response.status_code == 200
    assert response.json() == {"signed_in": False, "me": None}
    # Switching it back on does not revive the ended sessions: the patient signs in again.
    _switch("patient_tracking_enabled", True)
    assert signed_in["a"].get("/api/portal/me").status_code == 401


def test_other_saves_leave_sessions_alone(signed_in: dict[str, PortalClient]) -> None:
    _switch("online_booking_enabled", False)
    _switch("site_enabled", False)
    assert signed_in["a"].get("/api/portal/me").status_code == 200


def test_cancel_still_works_while_online_booking_is_off(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    _switch("online_booking_enabled", False)
    appointment = world["a"]["appointment"]["id"]
    response = signed_in["a"].post(f"/api/portal/appointments/{appointment}/cancel")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "cancelled"


def test_center_identity_answers_with_the_site_off(world: dict[str, dict[str, Any]]) -> None:
    _switch("site_enabled", False)
    response = PortalClient().get("/api/portal/center-identity")
    assert response.status_code == 200
    profile = core.center_profile()
    assert response.json() == {
        "name_ar": profile.name_ar,
        "name_en": profile.name_en,
        "logo_url": None,
    }


def test_staff_endpoints_are_unaffected_with_every_switch_off(
    world: dict[str, dict[str, Any]], make_user: Any
) -> None:
    for field in EXPECTED:
        _switch(field, False)
    make_user("front", roles=["receptionist"])
    staff = ApiClient()
    assert staff.login("front").status_code == 200
    upcoming = f"/api/visits/appointments/upcoming?patient_id={world['a']['patient']['id']}"
    assert staff.get(upcoming).status_code == 200
    assert staff.get(f"/api/patients/{world['a']['patient']['id']}").status_code == 200


def test_booking_reads_the_rules_from_the_settings_row(
    world: dict[str, dict[str, Any]], signed_in: dict[str, PortalClient]
) -> None:
    core.update_public_site_settings(_admin(), reason="test", max_open=7, cancel_cutoff_hours=5)
    rules = signed_in["a"].get("/api/portal/appointments").json()["rules"]
    assert (rules["max_open"], rules["cancel_cutoff_hours"]) == (7, 5)
    assert PublicSiteSettings.load().max_open == 7
