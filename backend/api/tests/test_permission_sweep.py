"""One permission sweep over the whole API contract (inspection F02).

Every OpenAPI operation is classified, from the explicit tables below or from its
``@require_perm``:

* ``PUBLIC``: no session of any kind (sign-in, CSRF, health, the public receipt check and the
  portal's public pages);
* ``STAFF_ANY``: any signed-in staff user, whatever the role (their own account, their own
  notifications, reference reads every dialog needs);
* ``PING``: the module pings (any signed-in staff user; a known, harmless exception);
* ``PORTAL_PATIENT``: the patient portal, its own session only (``apps.portal.api``);
* ``STAFF_PERM``: everything else, each with the one code its ``@require_perm`` checks. The
  portal's staff operations (access codes) are listed in ``PORTAL_STAFF`` on top, so a portal
  path that drops its permission fails here.

An operation in no class fails the sweep, as does a stale table entry. Then:

* nobody signed in: every non-public operation answers 401;
* each of the 12 roles: every ``STAFF_PERM`` operation whose code the role lacks answers 403
  ``PERMISSION_DENIED`` naming that code;
* a staff session on a portal patient operation, and a patient session on a staff operation,
  answer 401;
* a signed-in patient asking for another patient's invoice, receipt, result or appointment
  gets 404, never 403 and never the row.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.models import User
from apps.core.permissions import effective_permissions
from apps.core.roles import ROLE_CODES
from apps.payments.tests import api_kit as kit
from apps.payments.tests.test_permission_matrix import _request, _required_permissions, _schema
from apps.portal.api import PATIENT_OPERATIONS
from apps.portal.tests.conftest import PortalClient, seeded, signed_in, world  # noqa: F401
from conftest import ApiClient

pytestmark = pytest.mark.django_db

PUBLIC = {
    "auth_get_csrf",
    "auth_login",
    "auth_logout",
    "ops_get_health",
    "ops_get_site",
    "portal_get_session",
    "portal_login",
    "portal_logout",
    "portal_verify_receipt",
    "portal_get_center_page",
    "portal_get_center_logo",
    "portal_get_center_identity",
    "portal_get_center_media",
}

STAFF_ANY = {
    "auth_get_me",
    "auth_update_preferences",
    "auth_change_password",
    "core_get_center_logo",
    "core_list_notifications",
    "core_mark_notification_read",
    "core_mark_all_notifications_read",
    "core_get_unread_notification_count",
    "core_list_reason_codes",
}

#: Staff operations under /api/portal: access codes are issued and revoked by staff (ADR 0016),
#: each behind its own permission.
PORTAL_STAFF = {
    "portal_issue_access_code": "portal.issue_access_code",
    "portal_revoke_access_code": "portal.revoke_access_code",
    "portal_list_patient_access_codes": "portal.issue_access_code",
    "portal_issue_patient_access_code": "portal.issue_access_code",
}

#: Path parameters of portal patient operations that name the patient's own rows: a request for
#: another patient's id answers 404. ``doctor_id`` names a public doctor, not a patient's row.
OWNED_PARAMS = {
    "invoice_id": lambda w: w["invoice"]["id"],
    "payment_id": lambda w: w["payment"]["id"],
    "line_id": lambda w: w["approved_line"],
    "appointment_id": lambda w: w["appointment"]["id"],
}
NOT_OWNED_PARAMS = {"doctor_id"}

ALL_ROLES = sorted(ROLE_CODES)


@pytest.fixture(autouse=True)
def _patient_sign_in_on(db: None) -> None:
    """Patient sign-in on (a new install has it off, and patient operations would answer 409
    ``PORTAL_DISABLED`` before authentication): this sweep proves the session isolation. The
    switches are proved in ``apps/portal/tests/test_switches.py``."""
    from apps.core.models import PublicSiteSettings

    PublicSiteSettings.load()
    PublicSiteSettings.objects.filter(pk=1).update(patient_tracking_enabled=True)


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op) for path, item in schema["paths"].items() for method, op in item.items()
    ]


def _classify(op_id: str, required: dict[str, str]) -> str:
    if op_id in PUBLIC:
        return "public"
    if op_id in STAFF_ANY:
        return "staff_any"
    if op_id.endswith("_get_ping"):
        return "ping"
    if op_id in PATIENT_OPERATIONS:
        return "portal_patient"
    if op_id in required:
        return "staff_perm"
    return "unclassified"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return _schema()


@pytest.fixture(scope="module")
def required() -> dict[str, str]:
    return _required_permissions()


def test_every_operation_is_classified_and_the_tables_are_current(
    schema: dict[str, Any], required: dict[str, str]
) -> None:
    ops = {op["operationId"]: path for path, _, op in _operations(schema)}
    assert len(ops) > 350  # the scan itself works
    kinds = {op_id: _classify(op_id, required) for op_id in ops}
    assert [o for o, k in kinds.items() if k == "unclassified"] == [], (
        "classify these in api/tests/test_permission_sweep.py (or give them a @require_perm)"
    )
    # No operation is in two classes, and no table names an operation that no longer exists.
    explicit = [PUBLIC, STAFF_ANY, PATIENT_OPERATIONS]
    for a in range(len(explicit)):
        for b_ in range(a + 1, len(explicit)):
            assert explicit[a] & explicit[b_] == set()
    for table in (*explicit, set(PORTAL_STAFF)):
        assert table - set(ops) == set(), table - set(ops)
    # Unguarded classes really are unguarded, guarded ones carry a permission.
    for op_id in PUBLIC | STAFF_ANY | PATIENT_OPERATIONS:
        assert op_id not in required, f"{op_id} has a @require_perm: drop it from the table"
    # Every staff operation under /api/portal is a known one with its own permission.
    portal_staff = {o for o, path in ops.items() if path.startswith("/api/portal/")}
    portal_staff -= PUBLIC | PATIENT_OPERATIONS | {o for o in ops if o.endswith("_get_ping")}
    assert portal_staff == set(PORTAL_STAFF)
    for op_id, code in PORTAL_STAFF.items():
        assert required[op_id] == code, op_id


def test_nobody_signed_in_reaches_only_the_public_operations(
    schema: dict[str, Any], required: dict[str, str]
) -> None:
    anonymous = ApiClient()
    checked = 0
    for path, method, op in _operations(schema):
        op_id = op["operationId"]
        if _classify(op_id, required) == "public":
            continue
        url, body = _request(schema, path, op)
        response = anonymous.request(method.upper(), url, body)
        assert response.status_code == 401, (op_id, response.status_code, response.content)
        checked += 1
    assert checked > 300


def test_every_role_is_refused_every_permission_it_lacks(
    make_user: Any, schema: dict[str, Any], required: dict[str, str]
) -> None:
    kit.desk(make_user)  # reference data the generated bodies point at (reasons, banks)
    refused: dict[str, int] = {}
    for role in ALL_ROLES:
        probe = kit.actor(make_user, f"sweep_{role}", role)
        held = effective_permissions(User.objects.get(pk=probe.user.pk))
        refused[role] = 0
        for path, method, op in _operations(schema):
            op_id = op["operationId"]
            kind = _classify(op_id, required)
            url, body = _request(schema, path, op)
            if kind == "portal_patient":
                response = probe.api.request(method.upper(), url, body)
                assert response.status_code == 401, (role, op_id, response.status_code)
                continue
            if kind != "staff_perm" or required[op_id] in held:
                continue
            response = probe.api.request(method.upper(), url, body)
            assert response.status_code == 403, (
                role,
                op_id,
                response.status_code,
                response.content,
            )
            answer = response.json()
            assert answer["code"] == "PERMISSION_DENIED", (role, op_id)
            assert answer["details"] == {"permission": required[op_id]}, (role, op_id)
            refused[role] += 1
    # Every role but the administrator lacks something; the kiosk lacks all but its feed.
    assert refused["admin"] == 0
    assert all(n > 0 for role, n in refused.items() if role != "admin"), refused
    assert refused["display"] == sum(1 for c in required.values() if c != "visits.view_display")


def test_a_patient_session_opens_no_staff_operation(
    signed_in: dict[str, PortalClient],  # noqa: F811
    schema: dict[str, Any],
    required: dict[str, str],
) -> None:
    patient = signed_in["a"]
    checked = 0
    for path, method, op in _operations(schema):
        op_id = op["operationId"]
        if _classify(op_id, required) not in {"staff_perm", "staff_any", "ping"}:
            continue
        url, body = _request(schema, path, op)
        response = patient.request(method.upper(), url, body)
        assert response.status_code == 401, (op_id, response.status_code)
        checked += 1
    assert checked > 300


def test_a_patient_gets_404_for_another_patients_rows(
    signed_in: dict[str, PortalClient],  # noqa: F811
    world: dict[str, Any],  # noqa: F811
    schema: dict[str, Any],
) -> None:
    checked: list[str] = []
    for path, method, op in _operations(schema):
        op_id = op["operationId"]
        if op_id not in PATIENT_OPERATIONS:
            continue
        params = [p["name"] for p in op.get("parameters", []) if p["in"] == "path"]
        owned = [p for p in params if p not in NOT_OWNED_PARAMS]
        assert set(owned) <= set(OWNED_PARAMS), f"{op_id}: classify path parameters {owned}"
        if not owned:
            continue
        for me, other in (("a", "b"), ("b", "a")):
            url = path
            for name in params:
                value = OWNED_PARAMS[name](world[other]) if name in OWNED_PARAMS else 1
                url = url.replace("{" + name + "}", str(value))
            _, body = _request(schema, path, op)
            response = signed_in[me].request(method.upper(), url, body)
            assert response.status_code == 404, (op_id, me, response.status_code, response.content)
            assert response.json()["code"] == "NOT_FOUND"
        checked.append(op_id)
    assert set(checked) >= {
        "portal_get_invoice",
        "portal_get_receipt",
        "portal_get_result",
        "portal_cancel_appointment",
    }
