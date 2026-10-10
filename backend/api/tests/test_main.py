"""The assembled API: routes, operation ids, auth defaults, OpenAPI shape, JSON 404s."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from django.http import HttpRequest
from django.test import Client, RequestFactory

from api.main import API_VERSION
from api.middleware import _resolved_user_id
from apps.core.management.commands.export_openapi import render_schema

#: Module routers that carry only ``GET /ping`` in Phase 1 (ARCHITECTURE 4.11 order).
PING_MODULES = (
    "core",
    "patients",
    "visits",
    "catalog",
    "clinical",
    "orders",
    "billing",
    "payments",
    "pharmacy",
    "lab",
    "claims",
    "reports",
    "imports",
    "portal",
)

OPERATION_ID = re.compile(
    r"^(auth|core|ops|patients|visits|catalog|clinical|orders|billing|"
    r"payments|pharmacy|lab|claims|reports|imports|portal)_[a-z]+(_[a-z0-9]+)*$"
)


MODULE_PATH = re.compile(
    r"^/api/(auth|core|ops|patients|visits|catalog|clinical|orders|billing|"
    r"payments|pharmacy|lab|claims|reports|imports|portal)(/|$)"
)

#: The cashier module's operations (billing, payments, perform-first), used by the frontend.
CASHIER_OPERATIONS = (
    "billing_lookup_patients",
    "billing_get_visit_billing",
    "billing_list_unbilled_lines",
    "billing_set_line_payer",
    "billing_list_reasons",
    "billing_create_invoice",
    "billing_get_invoice",
    "billing_get_invoice_print",
    "billing_remove_draft_line",
    "billing_cancel_draft_line",
    "billing_set_preapproval_ref",
    "billing_discount_line",
    "billing_discount_invoice",
    "billing_approve_invoice",
    "billing_void_invoice",
    "billing_create_credit_note",
    "billing_list_credit_notes",
    "billing_get_credit_note",
    "billing_approve_credit_note",
    "payments_list_banks",
    "payments_list_tills",
    "payments_get_current_shift",
    "payments_open_shift",
    "payments_list_shifts",
    "payments_list_handover_targets",
    "payments_list_handover_receivers",
    "payments_get_shift",
    "payments_close_shift",
    "payments_review_shift",
    "payments_create_handover",
    "payments_receive_handover",
    "payments_cancel_handover",
    "payments_record_payment",
    "payments_get_payment",
    "payments_get_receipt",
    "payments_check_receipt",
    "payments_allocate_payment",
    "payments_list_transfers",
    "payments_confirm_transfer",
    "payments_reject_transfer",
    "payments_list_refunds",
    "payments_request_refund",
    "payments_approve_refund",
    "payments_reject_refund",
    "payments_pay_refund",
    "orders_get_perform_first_visit",
    "orders_authorize_perform_first",
    "orders_list_perform_first",
    "orders_revoke_perform_first",
)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    # Exactly what export_openapi writes (JSON round-trip turns status codes into strings).
    return dict(json.loads(render_schema()))


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op) for path, item in schema["paths"].items() for method, op in item.items()
    ]


def test_expected_routes_exist(schema: dict[str, Any]) -> None:
    # The platform routes and every module's ping exist; module features add more paths, each
    # under its own module router (ARCHITECTURE 4.11).
    assert set(schema["paths"]) >= {
        "/api/auth/csrf",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/me/preferences",
        "/api/auth/change-password",
        "/api/ops/health",
        *(f"/api/{module}/ping" for module in PING_MODULES),
    }
    for path in schema["paths"]:
        assert MODULE_PATH.match(path), path
    assert schema["info"]["title"] == "Hospital System API"
    assert schema["info"]["version"] == API_VERSION


def test_operation_ids_are_stable_and_unique(schema: dict[str, Any]) -> None:
    ids = [op["operationId"] for _, _, op in _operations(schema)]
    assert len(ids) == len(set(ids))
    for op_id in ids:
        assert OPERATION_ID.match(op_id), op_id
    # Operation ids become frontend function names: the pinned ones never change.
    pinned = {
        "auth_get_csrf",
        "auth_login",
        "auth_logout",
        "auth_get_me",
        "auth_update_preferences",
        "auth_change_password",
        "ops_get_health",
        *(f"{module}_get_ping" for module in PING_MODULES),
        *CASHIER_OPERATIONS,
    }
    assert pinned <= set(ids), sorted(pinned - set(ids))


def test_schema_class_names_are_unique() -> None:
    """Two ninja ``Schema`` classes with one name become one OpenAPI component: the second
    silently replaces the first in ``schema.d.ts`` and the frontend types the wrong shape
    (the ``DepartmentOut`` of visits once replaced the admin one). Prefix the module."""
    from collections import defaultdict

    from ninja import Schema

    import api.main  # noqa: F401  (imports every router and its schemas)

    def walk(cls: type) -> list[type]:
        out = []
        for sub in cls.__subclasses__():
            out.append(sub)
            out.extend(walk(sub))
        return out

    by_name: dict[str, set[str]] = defaultdict(set)
    for cls in walk(Schema):
        module = cls.__module__
        if module.startswith(("apps.", "api.")) and ".tests" not in module:
            by_name[cls.__name__].add(f"{module}.{cls.__qualname__}")
    clashes = {name: sorted(where) for name, where in by_name.items() if len(where) > 1}
    assert not clashes, clashes


#: Operations a signed-in user may call without a permission code. Anything else must carry
#: ``@require_perm`` (a new endpoint that forgets it fails here instead of going unnoticed).
OPEN_OPERATIONS = frozenset(
    {
        # Session plumbing: every user, before and after sign-in.
        "auth_get_csrf",
        "auth_login",
        "auth_logout",
        "auth_get_me",
        "auth_update_preferences",
        "auth_change_password",
        "ops_get_health",
        # Reference data every screen reads: the reason dialog lists and the center logo on
        # printouts and the app shell.
        "core_list_reason_codes",
        "core_get_center_logo",
        *(f"{module}_get_ping" for module in PING_MODULES),
        # Patient portal: public (sign-in, sign-out, receipt check).
        "portal_get_session",
        "portal_login",
        "portal_logout",
        "portal_verify_receipt",
    }
)


def _ninja_operations() -> list[tuple[str, Any]]:
    from api.main import api

    return [
        (str(op.operation_id), op)
        for _, router in api._routers
        for path_view in router.path_operations.values()
        for op in path_view.operations
    ]


def test_every_operation_requires_a_permission_unless_allowlisted() -> None:
    from apps.portal.api import PATIENT_OPERATIONS

    ops = _ninja_operations()
    open_ops = {
        op_id for op_id, op in ops if not getattr(op.view_func, "required_permission", None)
    }
    # Patient portal operations carry no staff permission: they authenticate a patient with
    # the portal cookie and read only that patient's rows (ADR 0016, apps/portal/tests).
    assert open_ops - PATIENT_OPERATIONS == OPEN_OPERATIONS
    # The allowlist names only operations that exist (a renamed one is not silently kept).
    assert {op_id for op_id, _ in ops} >= OPEN_OPERATIONS


def test_every_operation_is_tagged_with_its_module(schema: dict[str, Any]) -> None:
    for path, _, op in _operations(schema):
        module = path.split("/")[2]
        assert op["tags"] == [module], (path, op["tags"])
        assert op["operationId"].startswith(f"{module}_"), op["operationId"]


def test_only_whitelisted_operations_are_public(schema: dict[str, Any]) -> None:
    public = {op["operationId"] for _, _, op in _operations(schema) if not op.get("security")}
    assert public == {
        "auth_get_csrf",
        "auth_login",
        "auth_logout",
        "ops_get_health",
        # Patient portal sign-in and sign-out, and the public receipt check (ADR 0016).
        "portal_get_session",
        "portal_login",
        "portal_logout",
        "portal_verify_receipt",
    }


def test_error_responses_reference_error_schema(schema: dict[str, Any]) -> None:
    login = schema["paths"]["/api/auth/login"]["post"]["responses"]
    for status in ("401", "403", "422", "423"):
        ref = login[status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorOut")
    error_schema = schema["components"]["schemas"]["ErrorOut"]
    assert set(error_schema["required"]) == {"code", "message", "details"}


def test_me_out_shape(schema: dict[str, Any]) -> None:
    me = schema["components"]["schemas"]["MeOut"]
    assert set(me["required"]) == {
        "id",
        "username",
        "full_name_ar",
        "full_name_en",
        "roles",
        "permissions",
        "language",
        "theme",
        "must_change_password",
    }
    # Nullable: null means "never chosen" (the client follows the device).
    language = me["properties"]["language"]["anyOf"]
    theme = me["properties"]["theme"]["anyOf"]
    assert {"enum": ["ar", "en"], "type": "string"} in language
    assert {"type": "null"} in language
    assert {"enum": ["light", "dark", "warm"], "type": "string"} in theme
    assert {"type": "null"} in theme


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/", "/api/nope", "/api/auth/unknown", "/api/ops/health/x"])
def test_unknown_api_paths_return_json_404(path: str) -> None:
    response = Client().get(path)
    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Not found", "details": {}}


@pytest.mark.django_db
def test_admin_is_mounted() -> None:
    response = Client().get("/admin/")
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


def test_resolved_user_id_never_evaluates_lazy_user() -> None:
    from django.utils.functional import SimpleLazyObject

    request: HttpRequest = RequestFactory().get("/")
    request.user = SimpleLazyObject(lambda: pytest.fail("must not evaluate"))  # type: ignore[assignment]
    assert _resolved_user_id(request) is None


def test_resolved_user_id_reads_concrete_user() -> None:
    class FakeUser:
        is_authenticated = True
        pk = 42

    request = RequestFactory().get("/")
    request.user = FakeUser()  # type: ignore[assignment]
    assert _resolved_user_id(request) == 42
    request.user = type("Anon", (), {"is_authenticated": False, "pk": None})()
    assert _resolved_user_id(request) is None


@pytest.mark.django_db
def test_api_docs_use_bundled_assets_only(settings: Any) -> None:
    if not settings.API_DOCS_ENABLED:  # pragma: no cover - production-like environment
        pytest.skip("API docs disabled")
    response = Client().get("/api/docs")
    assert response.status_code == 200
    html = response.content.decode()
    assets = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert assets
    assert all(a.startswith("/static/") for a in assets), assets
    assert "cdn" not in html.lower()
    schema = Client().get("/api/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "Hospital System API"


def test_schema_class_names_are_unique_across_apps() -> None:
    # The OpenAPI generator keys components by class name, so two apps declaring the same name
    # (patients.PayerOut and catalog.PayerOut once did) silently document one endpoint with the
    # other's shape and the generated frontend types follow the wrong one.
    import importlib
    import inspect
    import pkgutil
    from collections import defaultdict

    from ninja import Schema

    import apps

    owners: dict[str, set[str]] = defaultdict(set)
    for info in pkgutil.iter_modules(apps.__path__):
        for part in ("schemas", "api"):
            try:
                module = importlib.import_module(f"apps.{info.name}.{part}")
            except ModuleNotFoundError:
                continue
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, Schema) and cls.__module__ == module.__name__:
                    owners[name].add(module.__name__)
    clashes = {name: sorted(mods) for name, mods in owners.items() if len(mods) > 1}
    assert clashes == {}
