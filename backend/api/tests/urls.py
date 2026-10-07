"""A throwaway API wired exactly like ``api.main`` to exercise the shared plumbing."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpRequest
from django.urls import path
from ninja import NinjaAPI, Query, Schema, Status
from ninja.errors import AuthorizationError, HttpError, Throttled

from api.errors import ApiError, install_exception_handlers
from api.pagination import PageParams, paginate
from api.permissions import require_perm
from api.schemas import Page
from api.security import csrf_guard, session_auth
from apps.core.models import Department
from config import urls as main_urls
from domain.errors import DomainError

test_api = NinjaAPI(title="test", version="test", urls_namespace="test-api", auth=session_auth)
install_exception_handlers(test_api)
test_api.add_decorator(csrf_guard, mode="view")


class EchoIn(Schema):
    name: str
    count: int


class DepartmentOut(Schema):
    code: str
    name_en: str


@test_api.get("/domain", auth=None)
def raise_domain(request: HttpRequest) -> None:
    raise DomainError("SHIFT_NOT_OPEN", "No open shift", shift_id=None, cashier=7)


@test_api.get("/domain-credentials", auth=None)
def raise_domain_mapped(request: HttpRequest) -> None:
    raise DomainError("INVALID_CREDENTIALS", "nope")


@test_api.get("/api-error", auth=None)
def raise_api_error(request: HttpRequest) -> None:
    raise ApiError(400, "BAD_THING", "bad thing", field="x")


@test_api.get("/not-found", auth=None)
def raise_404(request: HttpRequest) -> None:
    raise Http404("secret detail")


@test_api.get("/denied", auth=None)
def raise_denied(request: HttpRequest) -> None:
    raise PermissionDenied


@test_api.get("/forbidden", auth=None)
def raise_forbidden(request: HttpRequest) -> None:
    raise AuthorizationError()


@test_api.get("/csrf-http-error", auth=None)
def raise_csrf_http_error(request: HttpRequest) -> None:
    # What ninja's cookie auth raises when its own CSRF check fails.
    raise HttpError(403, "CSRF check Failed")


@test_api.get("/teapot", auth=None)
def raise_teapot(request: HttpRequest) -> None:
    raise HttpError(418, "I'm a teapot")


@test_api.get("/conflict", auth=None)
def raise_conflict(request: HttpRequest) -> None:
    raise HttpError(409, "conflict")


@test_api.get("/throttled", auth=None)
def raise_throttled(request: HttpRequest) -> None:
    raise Throttled(wait=5)


@test_api.get("/does-not-exist", auth=None)
def raise_does_not_exist(request: HttpRequest) -> None:
    Department.objects.get(code="NOPE-secret")


@test_api.get("/model-invalid", auth=None)
def raise_model_validation(request: HttpRequest) -> None:
    raise DjangoValidationError({"code": ["Unknown role code 'x'."]})


@test_api.get("/plain-invalid", auth=None)
def raise_plain_validation(request: HttpRequest) -> None:
    raise DjangoValidationError("Something is off.")


@test_api.post("/duplicate", auth=None)
def raise_integrity(request: HttpRequest) -> None:
    Department.objects.create(code="DUP", name_ar="أ", name_en="A")
    Department.objects.create(code="DUP", name_ar="ب", name_en="B")


@test_api.get("/boom", auth=None)
def raise_boom(request: HttpRequest) -> None:
    raise RuntimeError("internal secret")


@test_api.post("/echo", auth=None)
def echo(request: HttpRequest, payload: EchoIn) -> dict[str, Any]:
    return payload.model_dump()


@test_api.get("/whoami")
def whoami(request: HttpRequest) -> dict[str, Any]:
    return {"id": request.user.pk}


@test_api.post("/write", response={201: dict[str, bool]})
def write(request: HttpRequest) -> Status[dict[str, bool]]:
    return Status(201, {"ok": True})


@test_api.get("/users-only")
@require_perm("core.manage_users")
def users_only(request: HttpRequest) -> dict[str, bool]:
    return {"ok": True}


@test_api.post("/perm-echo")
@require_perm("core.manage_users")
def perm_echo(request: HttpRequest, payload: EchoIn) -> dict[str, Any]:
    return payload.model_dump()


@test_api.get("/unregistered")
@require_perm("nowhere.at_all")
def unregistered(request: HttpRequest) -> dict[str, bool]:
    return {"ok": True}  # pragma: no cover - never reached


@test_api.get("/departments", auth=None, response=Page[DepartmentOut])
def departments(request: HttpRequest, params: Query[PageParams]) -> dict[str, Any]:
    qs = Department.objects.order_by("code")
    if params.q:
        qs = qs.filter(name_en__icontains=params.q)
    return paginate(qs, params.page, params.page_size)


urlpatterns = [path("test-api/", test_api.urls), *main_urls.urlpatterns]
