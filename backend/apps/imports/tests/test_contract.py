"""Route contract of ``/api/imports``: pinned operation ids, and every operation refuses a
signed-in user without the permission with 403 before reading the request (no 422)."""

from __future__ import annotations

from typing import Any

import pytest

from apps.patients.tests.test_contract import assert_role_less_user_is_refused, module_operations
from conftest import ApiClient

pytestmark = pytest.mark.django_db

OPERATIONS = {
    ("get", "/api/imports/patients/template"): "imports_get_patient_template",
    ("post", "/api/imports/patients"): "imports_preview_patients",
    ("get", "/api/imports/{job_id}"): "imports_get_job",
    ("get", "/api/imports/{job_id}/rows"): "imports_list_rows",
    ("post", "/api/imports/{job_id}/confirm"): "imports_confirm_job",
    ("post", "/api/imports/{job_id}/cancel"): "imports_cancel_job",
    ("get", "/api/imports/ping"): "imports_get_ping",
}


def test_operations_are_pinned() -> None:
    assert module_operations("/api/imports") == OPERATIONS


def test_every_operation_refuses_a_user_without_the_permission(
    make_user: Any, api_client: ApiClient
) -> None:
    make_user("nobody")
    assert api_client.login("nobody").status_code == 200
    assert_role_less_user_is_refused(api_client, OPERATIONS, open_ops={"imports_get_ping"})
