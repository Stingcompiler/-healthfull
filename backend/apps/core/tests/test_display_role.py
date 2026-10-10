"""The waiting-room kiosk role ``display`` (ADR 0019): its only permission is the queue display
feed, and a sweep over the whole OpenAPI contract proves it reaches nothing else.

Generated from the schema like ``apps/payments/tests/test_permission_matrix.py``: every
operation that declares a ``require_perm`` is called with a well-formed request by a user
holding only the ``display`` role and must answer 403 with that permission, except the feed
itself. Operations without a ``require_perm`` are pinned here, so a new unguarded endpoint
fails until someone decides what a kiosk may see of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.models import Role, User
from apps.core.permissions import effective_permissions
from apps.core.roles import DISPLAY
from apps.payments.tests import api_kit as kit
from apps.payments.tests.test_permission_matrix import _request, _required_permissions, _schema

pytestmark = pytest.mark.django_db

#: Operations without a ``require_perm``: the caller's own account and notifications, module
#: pings, reference reads every dialog needs, the public health and receipt checks, and the
#: patient portal (its own session; a staff session answers 401 there).
UNGUARDED_STAFF = {
    "auth_change_password",
    "auth_get_csrf",
    "auth_login",
    "auth_logout",
    "auth_get_me",
    "auth_update_preferences",
    "core_get_center_logo",
    "core_list_notifications",
    "core_mark_all_notifications_read",
    "core_get_unread_notification_count",
    "core_mark_notification_read",
    "core_list_reason_codes",
    "ops_get_health",
    "portal_get_session",
    "portal_login",
    "portal_logout",
    "portal_verify_receipt",
}

PORTAL_PATIENT_PREFIX = "/api/portal/"


def test_the_role_is_seeded_with_labels_and_holds_only_the_feed(make_user: Any) -> None:
    role = Role.objects.get(code=DISPLAY)
    assert role.name_ar == "شاشة الانتظار"
    assert role.name_en == "Waiting-room display"
    user = make_user("kiosk", roles=[DISPLAY])
    assert effective_permissions(User.objects.get(pk=user.pk)) == {"visits.view_display"}


def test_staff_who_had_the_queue_keep_the_screen(make_user: Any) -> None:
    for role in ("receptionist", "doctor", "nurse", "manager", "admin"):
        user = make_user(f"screen_{role}", roles=[role])
        assert "visits.view_display" in effective_permissions(User.objects.get(pk=user.pk))
    cashier = make_user("screen_cashier", roles=["cashier"])
    assert "visits.view_display" not in effective_permissions(User.objects.get(pk=cashier.pk))


def test_the_display_role_reaches_the_feed_and_nothing_else(make_user: Any) -> None:
    kit.desk(make_user)  # reference data the generated bodies point at
    kiosk = kit.actor(make_user, "kiosk", DISPLAY)
    feed = kiosk.api.get("/api/visits/queue/display")
    assert feed.status_code == 200, feed.content
    assert {"serving", "waiting", "departments"} <= set(feed.json())

    schema = _schema()
    required = _required_permissions()
    refused: list[str] = []
    unguarded: set[str] = set()
    for path, item in schema["paths"].items():
        for method, op in item.items():
            op_id = op["operationId"]
            if op_id == "visits_get_display":
                continue
            if op_id not in required:
                unguarded.add(op_id)
                continue
            url, body = _request(schema, path, op)
            response = kiosk.api.request(method.upper(), url, body)
            assert response.status_code == 403, (op_id, response.status_code, response.content)
            assert response.json()["code"] == "PERMISSION_DENIED", op_id
            assert response.json()["details"]["permission"] == required[op_id], op_id
            refused.append(op_id)
    assert len(refused) == len(required) - 1  # every guarded operation but the feed

    pings = {op for op in unguarded if op.endswith("_ping")}
    portal_patient = (
        {
            op["operationId"]
            for path, item in schema["paths"].items()
            if path.startswith(PORTAL_PATIENT_PREFIX)
            for op in item.values()
            if op["operationId"] in unguarded
        }
        - UNGUARDED_STAFF
        - pings
    )
    assert unguarded - pings - portal_patient == UNGUARDED_STAFF
    # The patient portal never opens for a staff session, not even a kiosk's.
    for path, item in schema["paths"].items():
        for method, op in item.items():
            if op["operationId"] in portal_patient:
                url, body = _request(schema, path, op)
                response = kiosk.api.request(method.upper(), url, body)
                assert response.status_code == 401, (op["operationId"], response.status_code)
