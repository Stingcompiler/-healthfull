"""Permission enforcement for routers: ``@require_perm("billing.approve_invoice")``."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
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
    gets 403 ``PERMISSION_DENIED`` with ``details.permission``.

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
