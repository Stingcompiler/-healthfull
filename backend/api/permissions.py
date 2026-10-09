"""Permission enforcement for routers: ``@require_perm("billing.approve_invoice")``."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from ninja.operation import Operation
from ninja.utils import contribute_operation_callback

from api.errors import PermissionRequired
from apps.core.permissions import effective_permissions, is_registered

#: Every code used with ``require_perm``; verified by the ``core.E001`` system check.
REQUIRED_CODES: set[str] = set()

_CACHE_ATTR = "_hospital_effective_permissions"


def request_permissions(request: HttpRequest) -> frozenset[str]:
    """Effective permission codes of ``request.user``, computed once per request."""
    cached: frozenset[str] | None = getattr(request, _CACHE_ATTR, None)
    if cached is None:
        cached = effective_permissions(request.user)
        setattr(request, _CACHE_ATTR, cached)
    return cached


def check_perm(request: HttpRequest, code: str) -> None:
    """Raise ``PermissionRequired`` (HTTP 403) unless ``request.user`` holds ``code``."""
    if not is_registered(code):
        raise ImproperlyConfigured(f"Permission {code!r} is not registered")
    if code not in request_permissions(request):
        raise PermissionRequired(code)


def require_perm[F: Callable[..., Any]](code: str) -> Callable[[F], F]:
    """Restrict a ninja operation to users holding the permission ``code``.

    Place it *below* the ``@router.<method>(...)`` decorator::

        @router.post("/invoices/{invoice_id}/approve", ...)
        @require_perm("billing.approve_invoice")
        def approve_invoice(request, invoice_id: int): ...

    Authentication is still the router's job (401 first); a logged-in user without the code
    gets 403 ``PERMISSION_DENIED`` with ``details.permission``, before the request's query
    and body are validated (no 422 for a caller who may not use the operation).

    The view function itself is returned unchanged (ninja must read its signature with the
    module's own globals to resolve postponed annotations); the check is attached to the
    ninja operation built from it.
    """
    REQUIRED_CODES.add(code)

    def attach(operation: Operation) -> None:
        view = operation.view_func

        @functools.wraps(view)
        def checked(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            check_perm(request, code)
            return view(request, *args, **kwargs)

        operation.view_func = checked

        # Check right after authentication as well, before ninja parses the query and body,
        # so a caller without the code gets 403 and never a 422 describing the operation's
        # fields. Ninja clones operations when a router is mounted and re-applies the
        # operation's ``_run_decorators`` to each clone, so the hook rides along.
        run_decorators = list(getattr(operation, "_run_decorators", []))
        run_decorators.append(precheck)
        operation._run_decorators = run_decorators  # type: ignore[attr-defined]
        precheck(operation.run)

    def precheck(run: Callable[..., Any]) -> Callable[..., Any]:
        op = getattr(run, "__self__", None)
        if not isinstance(op, Operation) or op.is_async:
            return run  # pragma: no cover - every operation of this API is synchronous
        checks = op._run_checks

        def checked_checks(request: HttpRequest) -> HttpResponse | None:
            error = checks(request)
            if error is not None:
                return error
            try:
                check_perm(request, code)
            except Exception as exc:
                return op.api.on_exception(request, exc)
            return None

        op._run_checks = checked_checks  # type: ignore[method-assign]
        return run

    def decorator(func: F) -> F:
        if hasattr(func, "_ninja_operation"):
            raise ImproperlyConfigured(
                f"@require_perm({code!r}) must be placed below the @router.<method> decorator "
                f"of {func.__qualname__}"
            )
        contribute_operation_callback(func, attach)
        func.required_permission = code  # type: ignore[attr-defined]
        return func

    return decorator


def has_perm(request: HttpRequest, code: str) -> bool:
    """Non-raising check, for services or views that branch on a permission."""
    return code in request_permissions(request)
