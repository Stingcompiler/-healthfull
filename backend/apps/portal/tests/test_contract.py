"""The portal router's whole surface: operations, auth kind and permission codes."""

from __future__ import annotations

import json

from api.security import SessionAuth
from apps.core.management.commands.export_openapi import render_schema
from apps.portal.api import PATIENT_OPERATIONS
from apps.portal.security import PortalAuth
from conftest import router_operations

PUBLIC = {"portal_login", "portal_logout", "portal_verify_receipt"}
STAFF = {"portal_get_ping": None, "portal_issue_access_code": "portal.issue_access_code"}


def _security_by_operation() -> dict[str, list[str]]:
    schema = json.loads(render_schema())
    return {
        op["operationId"]: sorted(name for req in op.get("security", []) for name in req)
        for path, item in schema["paths"].items()
        if path.startswith("/api/portal/")
        for op in item.values()
    }


def test_router_surface_is_pinned() -> None:
    ops = router_operations("/portal")
    by_id = {op_id: perm for _, _, op_id, perm in ops}
    assert set(by_id) == PATIENT_OPERATIONS | PUBLIC | set(STAFF)
    for op_id, perm in STAFF.items():
        assert by_id[op_id] == perm
    for op_id in PATIENT_OPERATIONS | PUBLIC:
        assert by_id[op_id] is None  # staff permission codes never apply on the portal


def test_each_operation_uses_the_right_kind_of_auth() -> None:
    security = _security_by_operation()
    portal_scheme = PortalAuth.__name__
    staff_scheme = SessionAuth.__name__
    assert portal_scheme != staff_scheme
    for op_id in PATIENT_OPERATIONS:
        assert security[op_id] == [portal_scheme], op_id
    for op_id in PUBLIC:
        assert security[op_id] == [], op_id
    for op_id in STAFF:
        assert security[op_id] == [staff_scheme], op_id
