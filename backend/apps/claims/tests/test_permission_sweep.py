"""Every ``/api/claims`` operation refuses a role without its permission (403).

The accountant owns claims (FLOW step 10); managers read them. Generated from the OpenAPI
schema like the cashier sweep: each operation is called with a well-formed request by every
probe role, so a new endpoint is covered without editing this file and an endpoint without a
``require_perm`` fails here. Cashiers and doctors must never reach any of them: payer share
is not the till's money (invariant 7), and doctors hold no billing codes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import apps.payments.tests.test_permission_matrix as matrix
from apps.claims import permissions as _registered  # noqa: F401 - registers the codes
from apps.core.management.commands.export_openapi import render_schema
from apps.core.models import User
from apps.core.permissions import effective_permissions
from apps.payments.tests import api_kit as kit

pytestmark = pytest.mark.django_db

PREFIX = "/api/claims/"
PROBE_ROLES = (
    "cashier",
    "cashier_supervisor",
    "doctor",
    "nurse",
    "pharmacist",
    "lab_tech",
    "lab_supervisor",
    "receptionist",
    "manager",
)


def _schema() -> dict[str, Any]:
    return dict(json.loads(render_schema()))


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if path.startswith(PREFIX) and not path.endswith("/ping")
    ]


def test_every_claims_operation_declares_a_claims_permission() -> None:
    required = matrix._required_permissions()
    ops = _operations(_schema())
    assert len(ops) >= 19
    for _, _, op in ops:
        assert required.get(op["operationId"], "").startswith("claims."), op["operationId"]


def test_every_claims_operation_refuses_roles_without_its_permission(make_user: Any) -> None:
    kit.desk(make_user)  # reference data the bodies point at (reasons, banks)
    schema = _schema()
    required = matrix._required_permissions()
    probes = {role: kit.actor(make_user, f"probe_{role}", role) for role in PROBE_ROLES}
    held = {
        role: effective_permissions(User.objects.get(pk=probe.user.pk))
        for role, probe in probes.items()
    }
    checked: list[tuple[str, str]] = []
    for path, method, op in _operations(schema):
        op_id = op["operationId"]
        code = required[op_id]
        url, body = matrix._request(schema, path, op)
        for role, probe in probes.items():
            if code in held[role]:
                continue
            response = probe.api.request(method.upper(), url, body)
            assert response.status_code == 403, (op_id, role, response.content)
            assert response.json()["code"] == "PERMISSION_DENIED", (op_id, role)
            assert response.json()["details"]["permission"] == code, (op_id, role)
            checked.append((op_id, role))
    every = {op["operationId"] for _, _, op in _operations(schema)}
    refused = {role: {op for op, r in checked if r == role} for role in PROBE_ROLES}
    # No role but the accountant's, the manager's (reads and rejections) and the admin's
    # holds a claims code: cashiers, supervisors and doctors are refused everything.
    for role in PROBE_ROLES:
        if role != "manager":
            assert refused[role] == every, role
    manager_may = {
        op["operationId"]
        for _, _, op in _operations(schema)
        if required[op["operationId"]] in ("claims.view", "claims.resolve_rejection")
    }
    assert every - refused["manager"] == manager_may
