"""Route contract of ``/api/ops``: pinned operation ids, and every operation but the health
probe refuses a signed-in user without the permission with 403 before reading the request."""

from __future__ import annotations

from typing import Any

import pytest

from apps.patients.tests.test_contract import assert_role_less_user_is_refused, module_operations
from conftest import ApiClient

pytestmark = pytest.mark.django_db

OPERATIONS = {
    ("get", "/api/ops/health"): "ops_get_health",
    ("get", "/api/ops/status"): "ops_get_status",
    ("post", "/api/ops/backups/request"): "ops_request_backup",
    ("get", "/api/ops/updates"): "ops_list_updates",
    ("post", "/api/ops/export"): "ops_export_data",
}


def test_operations_are_pinned() -> None:
    assert module_operations("/api/ops") == OPERATIONS


def test_every_operation_refuses_a_user_without_the_permission(
    make_user: Any, api_client: ApiClient
) -> None:
    make_user("nobody")
    assert api_client.login("nobody").status_code == 200
    assert_role_less_user_is_refused(api_client, OPERATIONS, open_ops={"ops_get_health"})


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        ("admin", {"status", "request", "updates", "export"}),
        ("manager", {"status", "updates", "export"}),
        ("cashier", set()),
        ("doctor", set()),
    ],
)
def test_role_defaults(make_user: Any, api_client: ApiClient, role: str, allowed: set[str]) -> None:
    make_user(f"u-{role}", roles=[role])
    assert api_client.login(f"u-{role}").status_code == 200
    calls = {
        "status": lambda: api_client.get("/api/ops/status"),
        "request": lambda: api_client.post("/api/ops/backups/request", {"note": ""}),
        "updates": lambda: api_client.get("/api/ops/updates"),
        "export": lambda: api_client.post("/api/ops/export"),
    }
    for name, call in calls.items():
        response = call()
        if name in allowed:
            assert response.status_code in (200, 201), (role, name, response.status_code)
        else:
            assert response.status_code == 403, (role, name)
