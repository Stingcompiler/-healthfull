"""Portal access codes from the patient's file at reception (portal follow-up): issuing a code
for the printed slip revokes older ones; an explicit revoke ends the code and its sessions;
the codes are listed by state, never shown again; the roles without the codes get 403."""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.models import User
from apps.core.tests import builders as b
from apps.portal.models import PortalAccessCode, PortalEvent, PortalEventKind
from apps.portal.tests.conftest import PortalClient
from conftest import ApiClient

pytestmark = pytest.mark.django_db


def _staff(username: str) -> ApiClient:
    client = ApiClient()
    client.django.force_login(User.objects.get(username=username))
    return client


def _issue(who: dict[str, Any], username: str = "reception") -> Any:
    return _staff(username).post(f"/api/portal/patients/{who['patient']['id']}/access-codes", {})


def test_reception_issues_a_code_for_the_slip_and_older_codes_stop(
    world: dict[str, Any],
) -> None:
    a = world["a"]
    response = _issue(a)
    assert response.status_code == 201, response.content
    slip = response.json()
    assert slip["file_no"] == a["patient"]["file_no"]
    assert len(slip["code"]) == 9
    assert slip["full_name_en"] or slip["full_name_ar"]
    # The receipt's code no longer opens the portal; the slip's does.
    assert PortalClient().sign_in(a).status_code == 401
    assert PortalClient().sign_in(a, code=slip["code"]).status_code == 200
    live = PortalAccessCode.objects.filter(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    assert live.get().created_by.username == "reception"
    event = PortalEvent.objects.filter(kind=PortalEventKind.CODE_ISSUED).latest("id")
    assert event.details["payment"] == ""


def test_the_list_shows_states_never_codes(world: dict[str, Any]) -> None:
    a = world["a"]
    _issue(a)
    response = _staff("reception").get(f"/api/portal/patients/{a['patient']['id']}/access-codes")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["file_no"] == a["patient"]["file_no"]
    assert body["has_phone"] is True
    assert [c["state"] for c in body["codes"]] == ["active", "revoked"]
    text = response.content.decode()
    assert "code_hash" not in text
    assert a["code"] not in text


def test_revoke_ends_the_code_and_its_sessions(
    world: dict[str, Any], signed_in: dict[str, PortalClient]
) -> None:
    a = world["a"]
    assert signed_in["a"].get("/api/portal/me").status_code == 200
    code = PortalAccessCode.objects.get(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    reception = _staff("reception")
    refused = reception.post(f"/api/portal/access-codes/{code.pk}/revoke", {"note": " "})
    assert refused.status_code == 409
    assert refused.json()["code"] == "REASON_REQUIRED"
    response = reception.post(
        f"/api/portal/access-codes/{code.pk}/revoke", {"note": "slip lost in the car park"}
    )
    assert response.status_code == 200, response.content
    row = response.json()["codes"][0]
    assert row["state"] == "revoked"
    assert row["revoke_note"] == "slip lost in the car park"
    assert row["revoked_by"]["id"] == User.objects.get(username="reception").pk
    # The open session ends and the code no longer signs in.
    assert signed_in["a"].get("/api/portal/me").status_code == 401
    assert PortalClient().sign_in(a).status_code == 401
    assert PortalEvent.objects.filter(kind=PortalEventKind.CODE_REVOKED).count() == 1
    again = reception.post(f"/api/portal/access-codes/{code.pk}/revoke", {"note": "again"})
    assert again.status_code == 409
    assert again.json()["code"] == "PORTAL_CODE_ALREADY_REVOKED"
    # The other patient's code is untouched.
    assert PortalClient().sign_in(world["b"]).status_code == 200


def test_a_merged_file_gets_its_code_on_the_surviving_file(seeded: None) -> None:
    survivor = b.patient(phone="0912345678")
    merged = b.patient(phone="0912345678")
    merged.merged_into = survivor
    merged.is_active = False
    merged.save(update_fields=["merged_into", "is_active"])
    response = _staff("reception").post(f"/api/portal/patients/{merged.pk}/access-codes", {})
    assert response.status_code == 201, response.content
    assert response.json()["file_no"] == survivor.file_no
    assert PortalAccessCode.objects.get(revoked_at__isnull=True).patient_id == survivor.pk


def test_a_file_without_a_phone_gets_no_code(seeded: None) -> None:
    patient = b.patient(phone="")
    response = _staff("reception").post(f"/api/portal/patients/{patient.pk}/access-codes", {})
    assert response.status_code == 409
    assert response.json()["code"] == "PORTAL_PHONE_REQUIRED"
    listing = _staff("reception").get(f"/api/portal/patients/{patient.pk}/access-codes")
    assert listing.json()["has_phone"] is False
    missing = _staff("reception").post("/api/portal/patients/999999/access-codes", {})
    assert missing.status_code == 404


@pytest.mark.parametrize("username", ["doctor", "nurse", "pharmacist", "labtech", "accountant"])
def test_roles_without_the_codes_get_403(world: dict[str, Any], username: str) -> None:
    a = world["a"]
    client = _staff(username)
    pid = a["patient"]["id"]
    code = PortalAccessCode.objects.get(patient_id=pid, revoked_at__isnull=True)
    for response, permission in (
        (client.get(f"/api/portal/patients/{pid}/access-codes"), "portal.issue_access_code"),
        (client.post(f"/api/portal/patients/{pid}/access-codes", {}), "portal.issue_access_code"),
        (
            client.post(f"/api/portal/access-codes/{code.pk}/revoke", {"note": "x"}),
            "portal.revoke_access_code",
        ),
    ):
        assert response.status_code == 403, (username, response.content)
        assert response.json()["details"] == {"permission": permission}
    code.refresh_from_db()
    assert code.revoked_at is None


def test_a_cashier_issues_but_does_not_revoke(world: dict[str, Any]) -> None:
    a = world["a"]
    assert _issue(a, "cashier").status_code == 201
    code = PortalAccessCode.objects.get(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    response = _staff("cashier").post(f"/api/portal/access-codes/{code.pk}/revoke", {"note": "x"})
    assert response.status_code == 403


def test_staff_endpoints_refuse_a_portal_session(
    world: dict[str, Any], signed_in: dict[str, PortalClient]
) -> None:
    pid = world["a"]["patient"]["id"]
    for client in (ApiClient(), signed_in["a"]):
        assert client.get(f"/api/portal/patients/{pid}/access-codes").status_code == 401
        assert client.post(f"/api/portal/patients/{pid}/access-codes", {}).status_code == 401
