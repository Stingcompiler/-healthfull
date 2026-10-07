"""Error mapping, CSRF guard, session auth and require_perm through a full request cycle."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory

from api.errors import PermissionRequired
from api.permissions import (
    REQUIRED_CODES,
    check_perm,
    has_perm,
    request_permissions,
    require_perm,
)
from apps.core.models import Department, Role, RolePermission
from conftest import ApiClient

pytestmark = [pytest.mark.django_db, pytest.mark.urls("api.tests.urls")]


def _body(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.content
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    return body


@pytest.mark.parametrize(
    ("path", "status", "code", "details"),
    [
        ("/test-api/domain", 409, "SHIFT_NOT_OPEN", {"shift_id": None, "cashier": 7}),
        ("/test-api/domain-credentials", 401, "INVALID_CREDENTIALS", {}),
        ("/test-api/api-error", 400, "BAD_THING", {"field": "x"}),
        ("/test-api/not-found", 404, "NOT_FOUND", {}),
        ("/test-api/denied", 403, "PERMISSION_DENIED", {}),
        ("/test-api/forbidden", 403, "PERMISSION_DENIED", {}),
        ("/test-api/csrf-http-error", 403, "CSRF_FAILED", {}),
        ("/test-api/teapot", 418, "HTTP_ERROR", {}),
        ("/test-api/conflict", 409, "CONFLICT", {}),
        ("/test-api/throttled", 429, "RATE_LIMITED", {"wait": 5}),
        ("/test-api/does-not-exist", 404, "NOT_FOUND", {}),
        (
            "/test-api/model-invalid",
            422,
            "VALIDATION_ERROR",
            {"fields": {"code": ["Unknown role code 'x'."]}},
        ),
        (
            "/test-api/plain-invalid",
            422,
            "VALIDATION_ERROR",
            {"fields": {"__all__": ["Something is off."]}},
        ),
        ("/test-api/boom", 500, "INTERNAL_ERROR", {}),
        ("/test-api/whoami", 401, "NOT_AUTHENTICATED", {}),
    ],
)
def test_exceptions_map_to_uniform_errors(
    api_client: ApiClient, path: str, status: int, code: str, details: dict[str, Any]
) -> None:
    body = _body(api_client.get(path), status)
    assert body["code"] == code
    assert body["details"] == details


def test_integrity_error_is_a_conflict_without_db_details(api_client: ApiClient) -> None:
    body = _body(api_client.post("/test-api/duplicate"), 409)
    assert body["code"] == "CONFLICT"
    assert "DUP" not in body["message"]
    assert "core_department" not in body["message"]


def test_unknown_api_path_post_without_csrf_is_json_404(api_client: ApiClient) -> None:
    body = _body(api_client.post("/api/nope", {"x": 1}, csrf=False), 404)
    assert body["code"] == "NOT_FOUND"


def test_csrf_failure_outside_ninja_is_json_under_api(rf: Any) -> None:
    from api.views import csrf_failure

    response = csrf_failure(rf.post("/api/anything"), reason="no token")
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert json.loads(response.content)["code"] == "CSRF_FAILED"
    html = csrf_failure(rf.post("/admin/login/"), reason="no token")
    assert html.status_code == 403
    assert html["Content-Type"].startswith("text/html")


def test_internal_errors_do_not_leak_details(api_client: ApiClient) -> None:
    body = _body(api_client.get("/test-api/boom"), 500)
    assert "secret" not in body["message"]
    body = _body(api_client.get("/test-api/not-found"), 404)
    assert "secret" not in body["message"]
    body = _body(api_client.get("/test-api/does-not-exist"), 404)
    assert "secret" not in body["message"]


def test_domain_error_message_is_passed_through(api_client: ApiClient) -> None:
    assert api_client.get("/test-api/domain").json()["message"] == "No open shift"


def test_validation_errors_are_sanitised(api_client: ApiClient) -> None:
    body = _body(api_client.post("/test-api/echo", {"name": "a", "count": "many"}), 422)
    assert body["code"] == "VALIDATION_ERROR"
    (error,) = body["details"]["errors"]
    assert error["loc"] == ["body", "payload", "count"]
    assert error["type"] == "int_parsing"
    assert set(error) == {"loc", "msg", "type"}


def test_valid_payload_passes(api_client: ApiClient) -> None:
    response = api_client.post("/test-api/echo", {"name": "a", "count": 2})
    assert response.status_code == 200
    assert response.json() == {"name": "a", "count": 2}


# --- CSRF ---------------------------------------------------------------------------------


def test_csrf_enforced_before_auth_and_validation(api_client: ApiClient) -> None:
    # Unauthenticated + invalid body + no token -> CSRF wins.
    assert _body(api_client.post("/test-api/echo", {}, csrf=False), 403)["code"] == "CSRF_FAILED"
    assert _body(api_client.post("/test-api/write", csrf=False), 403)["code"] == "CSRF_FAILED"


def test_safe_methods_skip_csrf(api_client: ApiClient) -> None:
    assert api_client.get("/test-api/domain").status_code == 409


def test_csrf_token_must_match_cookie(api_client: ApiClient) -> None:
    api_client.fetch_csrf()
    other = ApiClient().fetch_csrf()
    response = api_client.post(
        "/test-api/echo",
        {"name": "a", "count": 1},
        headers={
            "X-CSRFToken": other,
        },
    )
    # Tokens are masked per request; a token from another browser has a different secret.
    assert _body(response, 403)["code"] == "CSRF_FAILED"


def test_untrusted_origin_is_rejected(api_client: ApiClient) -> None:
    response = api_client.post(
        "/test-api/echo", {"name": "a", "count": 1}, headers={"Origin": "http://evil.example"}
    )
    assert _body(response, 403)["code"] == "CSRF_FAILED"


def test_trusted_frontend_origin_is_accepted(api_client: ApiClient, settings: Any) -> None:
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:5173"]
    response = api_client.post(
        "/test-api/echo",
        {"name": "a", "count": 1},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200


# --- Session auth -------------------------------------------------------------------------


def test_session_auth_accepts_logged_in_user(
    api_client: ApiClient, make_user: Any, settings: Any
) -> None:
    user = make_user("alice")
    assert api_client.login("alice").status_code == 200
    assert api_client.get("/test-api/whoami").json() == {"id": user.pk}
    assert api_client.post("/test-api/write").status_code == 201


def test_password_change_pending_blocks_regular_endpoints(
    api_client: ApiClient, make_user: Any
) -> None:
    make_user("pending", must_change_password=True)
    assert api_client.login("pending").status_code == 200
    body = _body(api_client.get("/test-api/whoami"), 403)
    assert body["code"] == "PASSWORD_CHANGE_REQUIRED"


# --- require_perm -------------------------------------------------------------------------


def test_require_perm_denies_without_permission(api_client: ApiClient, make_user: Any) -> None:
    make_user("cashier1", roles=["cashier"])
    api_client.login("cashier1")
    body = _body(api_client.get("/test-api/users-only"), 403)
    assert body == {
        "code": "PERMISSION_DENIED",
        "message": "Permission denied",
        "details": {"permission": "core.manage_users"},
    }


def test_require_perm_allows_role_default(api_client: ApiClient, make_user: Any) -> None:
    make_user("admin1", roles=["admin"])
    api_client.login("admin1")
    assert api_client.get("/test-api/users-only").json() == {"ok": True}


def test_require_perm_keeps_the_view_signature(api_client: ApiClient, make_user: Any) -> None:
    from api.tests.urls import test_api

    make_user("admin2", roles=["admin"])
    make_user("nurse2", roles=["nurse"])
    api_client.login("admin2")
    ok = api_client.post("/test-api/perm-echo", {"name": "n", "count": 3})
    assert ok.status_code == 200
    assert ok.json() == {"name": "n", "count": 3}
    assert api_client.post("/test-api/perm-echo", {"name": "n"}).status_code == 422
    other = ApiClient()
    other.login("nurse2")
    assert other.post("/test-api/perm-echo", {"name": "n", "count": 3}).status_code == 403
    schema = test_api.get_openapi_schema(path_prefix="/test-api/")
    assert "requestBody" in schema["paths"]["/test-api/perm-echo"]["post"]


def test_require_perm_honours_overrides(api_client: ApiClient, make_user: Any) -> None:
    make_user("cashier2", roles=["cashier"])
    RolePermission.objects.create(
        role=Role.objects.get(code="cashier"), code="core.manage_users", allowed=True
    )
    api_client.login("cashier2")
    assert api_client.get("/test-api/users-only").status_code == 200


def test_require_perm_unauthenticated_is_401(api_client: ApiClient) -> None:
    assert _body(api_client.get("/test-api/users-only"), 401)["code"] == "NOT_AUTHENTICATED"


def test_require_perm_with_unregistered_code_fails_loudly(
    api_client: ApiClient, make_user: Any
) -> None:
    make_user("someone")
    api_client.login("someone")
    assert _body(api_client.get("/test-api/unregistered"), 500)["code"] == "INTERNAL_ERROR"
    assert "nowhere.at_all" in REQUIRED_CODES


def test_require_perm_must_sit_below_the_router_decorator() -> None:
    from ninja import Router

    router = Router()

    with pytest.raises(ImproperlyConfigured, match="must be placed below"):

        @require_perm("core.manage_users")
        @router.get("/x")
        def misplaced(request: Any) -> None:
            return None  # pragma: no cover

    @router.get("/y")
    @require_perm("core.view_audit")
    def placed(request: Any) -> None:
        return None  # pragma: no cover

    assert placed.required_permission == "core.view_audit"  # type: ignore[attr-defined]


def test_request_permissions_are_cached_per_request(make_user: Any) -> None:
    user = make_user("cache", roles=["admin"])
    request = RequestFactory().get("/")
    request.user = user
    first = request_permissions(request)
    RolePermission.objects.create(
        role=Role.objects.get(code="admin"), code="core.manage_users", allowed=False
    )
    assert request_permissions(request) is first
    assert has_perm(request, "core.manage_users")
    fresh = RequestFactory().get("/")
    fresh.user = user
    assert not has_perm(fresh, "core.manage_users")


def _request_for(user: Any) -> Any:
    request = RequestFactory().get("/")
    request.user = user
    return request


def test_check_perm(make_user: Any) -> None:
    admin_request = _request_for(make_user("x1", roles=["admin"]))
    check_perm(admin_request, "core.manage_users")
    with pytest.raises(PermissionRequired) as exc:
        check_perm(_request_for(make_user("x2", roles=["nurse"])), "core.manage_users")
    assert exc.value.permission == "core.manage_users"
    with pytest.raises(ImproperlyConfigured):
        check_perm(admin_request, "ghost.code")


# --- Pagination through the API -----------------------------------------------------------


def test_paginated_endpoint(api_client: ApiClient) -> None:
    for i in range(30):
        Department.objects.create(code=f"D{i:02d}", name_ar=f"قسم {i}", name_en=f"Dept {i}")
    body = api_client.get("/test-api/departments?page=2&page_size=10").json()
    assert body["count"] == 30
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert [d["code"] for d in body["items"]] == [f"D{i:02d}" for i in range(10, 20)]

    filtered = api_client.get("/test-api/departments?q=Dept 2").json()
    assert filtered["count"] == 11  # Dept 2, Dept 20..29

    assert api_client.get("/test-api/departments?page_size=101").status_code == 422
    assert api_client.get("/test-api/departments?page=0").status_code == 422
