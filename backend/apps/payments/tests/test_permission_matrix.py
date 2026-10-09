"""Every cashier operation refuses a role without its permission (403 ``PERMISSION_DENIED``).

Generated from the OpenAPI schema: each operation under ``/api/billing``, ``/api/payments`` and
``/api/orders/perform-first`` is called with a well-formed request (path ids, required query
parameters and a body built from the schema), by every probe role that lacks the permission
its router requires. A new endpoint is covered without editing this file, and an endpoint
without a ``require_perm`` fails here.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import pytest

from api.main import api
from apps.core.management.commands.export_openapi import render_schema
from apps.core.models import User
from apps.core.permissions import effective_permissions
from apps.payments.tests import api_kit as kit

pytestmark = pytest.mark.django_db

PREFIXES = ("/api/billing/", "/api/payments/", "/api/orders/perform-first")
#: Roles that hold none or only some of the cashier codes. Cashiers probe the supervisor-only
#: endpoints; doctors, nurses and pharmacists probe the whole desk.
PROBE_ROLES = ("doctor", "nurse", "pharmacist", "lab_supervisor", "receptionist", "cashier")


def _schema() -> dict[str, Any]:
    return dict(json.loads(render_schema()))


def _required_permissions() -> dict[str, str]:
    """operation id -> the code its ``@require_perm`` checks (read from the bound API)."""
    found: dict[str, str] = {}
    for pattern in api.urls[0]:
        closure = getattr(pattern.callback, "__closure__", None) or ()
        for cell in closure:
            path_view = cell.cell_contents
            for op in getattr(path_view, "operations", ()):
                view = op.view_func
                while view is not None and not hasattr(view, "required_permission"):
                    view = getattr(view, "__wrapped__", None)
                if view is not None:
                    found[op.operation_id] = view.required_permission
    return found


def _cashier_operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if path.startswith(PREFIXES) and not path.endswith("/ping")
    ]


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = schema["components"]["schemas"][name]
    return node


def _example(schema: dict[str, Any], node: dict[str, Any]) -> Any:
    """A value the schema accepts: every property filled, the first enum value, ids of 1."""
    node = _resolve(schema, node)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        return _example(schema, options[0])
    if "enum" in node:
        return node["enum"][0]
    if "const" in node:
        return node["const"]
    kind = node.get("type")
    if kind == "object":
        props = node.get("properties", {})
        return {name: _example(schema, sub) for name, sub in props.items()}
    if kind == "array":
        return [_example(schema, node["items"])] if node.get("minItems") else []
    if kind == "integer":
        return 1
    if kind == "number":
        return 1
    if kind == "boolean":
        return False
    if node.get("format") == "date":
        return "2026-01-01"
    return "1"


def _request(schema: dict[str, Any], path: str, op: dict[str, Any]) -> tuple[str, Any]:
    url = path
    query: dict[str, Any] = {}
    for param in op.get("parameters", []):
        value = _example(schema, param.get("schema", {}))
        if param["in"] == "path":
            url = url.replace("{" + param["name"] + "}", str(value))
        elif param["in"] == "query" and param.get("required"):
            query[param["name"]] = value
    if query:
        url = f"{url}?{urlencode(query)}"
    body = None
    content = op.get("requestBody", {}).get("content", {}).get("application/json")
    if content is not None:
        body = _example(schema, content["schema"])
    return url, body


def test_every_cashier_operation_declares_a_permission() -> None:
    schema = _schema()
    required = _required_permissions()
    missing = [op["operationId"] for _, _, op in _cashier_operations(schema)]
    missing = [op_id for op_id in missing if op_id not in required]
    assert missing == []


def test_every_cashier_operation_refuses_roles_without_its_permission(make_user: Any) -> None:
    kit.desk(make_user)  # reference data the bodies point at (reasons, banks)
    schema = _schema()
    required = _required_permissions()
    probes = {role: kit.actor(make_user, f"probe_{role}", role) for role in PROBE_ROLES}
    held = {
        role: effective_permissions(User.objects.get(pk=probe.user.pk))
        for role, probe in probes.items()
    }
    checked: list[tuple[str, str]] = []
    for path, method, op in _cashier_operations(schema):
        op_id = op["operationId"]
        code = required[op_id]
        url, body = _request(schema, path, op)
        for role, probe in probes.items():
            if code in held[role]:
                continue
            response = probe.api.request(method.upper(), url, body)
            assert response.status_code == 403, (op_id, role, response.content)
            assert response.json()["code"] == "PERMISSION_DENIED", (op_id, role)
            assert response.json()["details"]["permission"] == code, (op_id, role)
            checked.append((op_id, role))
    tested = {op_id for op_id, _ in checked}
    every = {op["operationId"] for _, _, op in _cashier_operations(schema)}
    # Every operation was refused to at least one probe role, and the doctor never reaches any.
    assert tested == every
    assert {op_id for op_id, role in checked if role == "doctor"} == every
