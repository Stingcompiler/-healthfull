"""Public receipt verification (FEATURES 15.1) and issuing access codes from the receipt."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.utils import timezone

from apps.core.models import User
from apps.core.tests import builders as b
from apps.patients.models import Patient
from apps.payments.models import Payment
from apps.portal import services
from apps.portal.models import PortalAccessCode, PortalEvent, PortalEventKind
from apps.portal.tests.conftest import PortalClient
from conftest import ApiClient

pytestmark = pytest.mark.django_db

NOT_FOUND = {"code": "NOT_FOUND", "message": "Not found", "details": {}}


def _verify(client: Any, number: str, token: str) -> Any:
    return client.get(f"/api/portal/verify?receipt={number}&token={token}")


# --- verification --------------------------------------------------------------------------


def test_verify_answers_only_minimal_data(world: dict[str, Any]) -> None:
    a = world["a"]
    response = _verify(ApiClient(), a["payment"]["number"], a["verify_token"])
    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {
        "center_name_ar",
        "center_name_en",
        "receipt_number",
        "date",
        "amount",
        "status",
        "patient_initials",
    }
    assert body["receipt_number"] == a["payment"]["number"]
    assert body["status"] == "valid"
    patient = Patient.objects.get(pk=a["patient"]["id"])
    text = json.dumps(body, ensure_ascii=False)
    for secret in (patient.full_name_ar, patient.full_name_en, patient.file_no, patient.phone):
        if secret:
            assert secret not in text
    assert len(body["patient_initials"].replace(".", "").replace(" ", "")) <= 2


@pytest.mark.parametrize("case", ["wrong-token", "other-receipt-token", "unknown-number"])
def test_verify_does_not_tell_unknown_from_wrong(world: dict[str, Any], case: str) -> None:
    a, other = world["a"], world["b"]
    number, token = {
        "wrong-token": (a["payment"]["number"], "a" * 20),
        "other-receipt-token": (a["payment"]["number"], other["verify_token"]),
        "unknown-number": ("RCP-2099-999999", a["verify_token"]),
    }[case]
    response = _verify(ApiClient(), number, token)
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_verify_reports_pending_and_void(seeded: None) -> None:
    pending = b.payment(method="bank_transfer")
    rejected = b.payment(
        method="bank_transfer",
        verification="rejected",
        rejection_reason=b.reason("transfer_reject"),
        verified_by=b.user(),
        verified_at=timezone.now(),
    )
    for payment, status in ((pending, "pending"), (rejected, "void")):
        token = services.receipt_verify_token(payment.number)
        assert _verify(ApiClient(), payment.number, token).json()["status"] == status


def test_verify_is_rate_limited(world: dict[str, Any], settings: Any) -> None:
    settings.PORTAL_VERIFY_IP_MAX = 2
    a = world["a"]
    client = ApiClient()
    assert _verify(client, a["payment"]["number"], a["verify_token"]).status_code == 200
    assert _verify(client, "RCP-2099-000001", "x" * 20).status_code == 404
    response = _verify(client, a["payment"]["number"], a["verify_token"])
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert PortalEvent.objects.filter(kind=PortalEventKind.VERIFY_THROTTLED).exists()


def test_receipt_payload_carries_the_verify_token(world: dict[str, Any]) -> None:
    a = world["a"]
    cashier = ApiClient()
    cashier.django.force_login(User.objects.get(username="cashier"))
    receipt = cashier.get(f"/api/payments/payments/{a['payment']['id']}/receipt").json()
    assert receipt["verify_token"] == a["verify_token"]


# --- issuing codes -------------------------------------------------------------------------


def _staff(username: str) -> ApiClient:
    client = ApiClient()
    client.django.force_login(User.objects.get(username=username))
    return client


def test_cashier_issues_a_code_once(world: dict[str, Any]) -> None:
    a = world["a"]
    response = _staff("cashier").post(
        "/api/portal/access-codes", {"payment_id": a["payment"]["id"]}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert len(body["code"]) == 9
    assert body["code"][4] == " "
    assert body["file_no"] == a["patient"]["file_no"]
    live = PortalAccessCode.objects.filter(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    assert live.count() == 1
    assert live.get().created_by.username == "cashier"
    revoked = PortalAccessCode.objects.filter(patient_id=a["patient"]["id"]).exclude(
        revoked_at=None
    )
    earlier = revoked.get().revoked_by  # the code printed earlier
    assert earlier is not None
    assert earlier.username == "cashier"
    assert PortalClient().sign_in(a, code=body["code"]).status_code == 200
    assert PortalEvent.objects.filter(kind=PortalEventKind.CODE_ISSUED).count() == 3


@pytest.mark.parametrize("username", ["doctor", "nurse", "pharmacist"])
def test_roles_without_the_permission_cannot_issue(world: dict[str, Any], username: str) -> None:
    response = _staff(username).post(
        "/api/portal/access-codes", {"payment_id": world["a"]["payment"]["id"]}
    )
    assert response.status_code == 403
    assert response.json()["details"] == {"permission": "portal.issue_access_code"}


def test_issuing_needs_a_staff_session(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    for client in (ApiClient(), signed_in["a"]):
        response = client.post(
            "/api/portal/access-codes", {"payment_id": world["a"]["payment"]["id"]}
        )
        assert response.status_code == 401


def test_issuing_needs_csrf(world: dict[str, Any]) -> None:
    response = _staff("cashier").post(
        "/api/portal/access-codes", {"payment_id": world["a"]["payment"]["id"]}, csrf=False
    )
    assert response.status_code == 403


def test_a_file_without_phone_gets_no_code(seeded: None) -> None:
    payment = b.payment(pat=b.patient(phone=""))
    response = _staff("cashier").post("/api/portal/access-codes", {"payment_id": payment.pk})
    assert response.status_code == 409
    assert response.json()["code"] == "PORTAL_PHONE_REQUIRED"


def test_unknown_payment_is_not_found(seeded: None) -> None:
    response = _staff("cashier").post("/api/portal/access-codes", {"payment_id": 999_999})
    assert response.status_code == 404
    assert not Payment.objects.filter(pk=999_999).exists()
