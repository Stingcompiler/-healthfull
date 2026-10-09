"""Route contract of ``/api/patients``: pinned operation ids, and every operation refuses a
signed-in user without the permission with 403 before reading the request (no 422)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from apps.core.management.commands.export_openapi import render_schema
from conftest import ApiClient

pytestmark = pytest.mark.django_db

PREFIX = "/api/patients"

#: The module's operations; a removed or renamed route fails here (the shared route test in
#: ``api/tests/test_main.py`` pins only the platform routes).
OPERATIONS = {
    ("get", "/api/patients"): "patients_list_patients",
    ("post", "/api/patients"): "patients_create_patient",
    ("get", "/api/patients/duplicates"): "patients_find_duplicates",
    ("get", "/api/patients/payers"): "patients_list_payers",
    ("get", "/api/patients/merge-reasons"): "patients_list_merge_reasons",
    ("post", "/api/patients/emergency"): "patients_register_emergency",
    ("get", "/api/patients/{patient_id}"): "patients_get_patient",
    ("patch", "/api/patients/{patient_id}"): "patients_update_patient",
    ("post", "/api/patients/{patient_id}/merge"): "patients_merge_patient",
    ("get", "/api/patients/{patient_id}/merges"): "patients_list_merges",
    ("get", "/api/patients/{patient_id}/coverages"): "patients_list_coverages",
    ("post", "/api/patients/{patient_id}/coverages"): "patients_create_coverage",
    ("patch", "/api/patients/coverages/{coverage_id}"): "patients_update_coverage",
    ("post", "/api/patients/coverages/{coverage_id}/end"): "patients_end_coverage",
    ("get", "/api/patients/{patient_id}/balance"): "patients_get_balance",
    ("get", "/api/patients/ping"): "patients_get_ping",
}


def module_operations(prefix: str) -> dict[tuple[str, str], str]:
    schema = json.loads(render_schema())
    return {
        (method, path): op["operationId"]
        for path, item in schema["paths"].items()
        if path == prefix or path.startswith(f"{prefix}/")
        for method, op in item.items()
    }


def assert_role_less_user_is_refused(
    api: ApiClient, operations: dict[tuple[str, str], str], *, open_ops: set[str]
) -> None:
    for (method, path), op_id in operations.items():
        if op_id in open_ops:
            continue
        url = re.sub(r"\{[a-z_]+\}", "1", path)
        response: Any = api.request(method.upper(), url, None if method == "get" else {})
        assert response.status_code == 403, (op_id, response.status_code, response.content)
        assert response.json()["code"] == "PERMISSION_DENIED", op_id


def test_operations_are_pinned() -> None:
    assert module_operations(PREFIX) == OPERATIONS


def test_every_operation_refuses_a_user_without_the_permission(
    make_user: Any, api_client: ApiClient
) -> None:
    make_user("nobody")
    assert api_client.login("nobody").status_code == 200
    assert_role_less_user_is_refused(api_client, OPERATIONS, open_ops={"patients_get_ping"})
