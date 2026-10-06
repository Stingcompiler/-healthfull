"""Authentication and CSRF for the API.

* Every unsafe request (POST/PUT/PATCH/DELETE) to any operation must carry a valid
  ``X-CSRFToken`` header matching the ``csrftoken`` cookie, including unauthenticated
  ones such as login (login CSRF). Enforced by :func:`csrf_guard`, installed API-wide
  in "view" mode so it runs before authentication and body validation.
* Authenticated operations use :data:`session_auth` (Django session cookie). Users whose
  ``must_change_password`` flag is set are refused with ``PASSWORD_CHANGE_REQUIRED``
  everywhere except the few auth endpoints that use :data:`session_auth_pending_ok`.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase
from ninja.security import APIKeyCookie
from ninja.utils import check_csrf

from api.errors import ApiError, error_response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def csrf_guard(run: Callable[..., HttpResponseBase]) -> Callable[..., HttpResponseBase]:
    """Ninja "view"-mode decorator that rejects unsafe requests failing Django's CSRF check."""

    @functools.wraps(run)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if request.method not in SAFE_METHODS and check_csrf(request) is not None:
            return error_response(403, "CSRF_FAILED", "CSRF verification failed")
        return run(request, *args, **kwargs)

    return wrapper


class SessionAuth(APIKeyCookie):
    """Django session authentication for ninja operations."""

    param_name: str = settings.SESSION_COOKIE_NAME

    def __init__(self, *, allow_password_change_pending: bool = False) -> None:
        self.allow_password_change_pending = allow_password_change_pending
        super().__init__(csrf=True)

    def authenticate(self, request: HttpRequest, key: str | None) -> Any:
        user = request.user
        if not user.is_authenticated or not user.is_active:
            return None
        if getattr(user, "must_change_password", False) and not self.allow_password_change_pending:
            raise ApiError(
                403,
                "PASSWORD_CHANGE_REQUIRED",
                "Password must be changed before using the system",
            )
        return user


session_auth = SessionAuth()
session_auth_pending_ok = SessionAuth(allow_password_change_pending=True)
