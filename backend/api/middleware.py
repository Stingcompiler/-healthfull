"""Request correlation and audit context.

``RequestIdMiddleware`` (first in the stack) assigns every request a server-generated id,
binds it to the structlog context, returns it in the ``X-Request-ID`` response header and
writes one access log line per request. The id ends up in immutable audit rows
(``AuthEvent.request_id``, pghistory context), so a client can never choose it: a
well-formed incoming ``X-Request-ID`` is kept only as ``client_request_id`` (logs and
pghistory metadata, clearly labelled as client-supplied).

``ApiMethodNotAllowedMiddleware`` turns ninja's plain-text 405 into the JSON error shape.

``AuditContextMiddleware`` (after ``AuthenticationMiddleware``) opens a
``pghistory.context`` for writes, so every audited row change made while serving the
request records the acting user id, request id, method and path.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable

import pghistory
import structlog
from django.http import HttpRequest, HttpResponseBase, JsonResponse
from django.utils.functional import SimpleLazyObject

from api.errors import error_body

logger = structlog.get_logger("hospital.request")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_INCOMING_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

GetResponse = Callable[[HttpRequest], HttpResponseBase]


def _client_request_id_from(request: HttpRequest) -> str | None:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    return incoming if _VALID_INCOMING_ID.match(incoming) else None


def _resolved_user_id(request: HttpRequest) -> int | None:
    """User id if the user was already resolved during the request; never hits the DB."""
    # ``login()`` replaces request.user with a concrete user; otherwise use the value the
    # lazy auth middleware cached, if anything evaluated it during the request.
    user = request.__dict__.get("user")
    if user is None or isinstance(user, SimpleLazyObject):
        user = getattr(request, "_cached_user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    pk = getattr(user, "pk", None)
    return pk if isinstance(pk, int) else None


class RequestIdMiddleware:
    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        request_id = uuid.uuid4().hex
        client_request_id = _client_request_id_from(request)
        request.request_id = request_id  # type: ignore[attr-defined]
        request.client_request_id = client_request_id  # type: ignore[attr-defined]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        if client_request_id:
            structlog.contextvars.bind_contextvars(client_request_id=client_request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request",
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                user_id=_resolved_user_id(request),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()


class ApiMethodNotAllowedMiddleware:
    """Ninja answers unsupported methods with a plain-text 405; make it a JSON error too."""

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        if (
            response.status_code == 405
            and request.path.startswith("/api/")
            and not response.get("Content-Type", "").startswith("application/json")
        ):
            allow = response.get("Allow", "")
            json_response = JsonResponse(
                error_body(
                    "METHOD_NOT_ALLOWED",
                    "Method not allowed",
                    {"allowed": sorted(m.strip() for m in allow.split(",") if m.strip())},
                ),
                status=405,
            )
            if allow:
                json_response["Allow"] = allow
            return json_response
        return response


class AuditContextMiddleware:
    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if request.method not in _WRITE_METHODS:
            return self.get_response(request)
        user = getattr(request, "user", None)
        user_id = user.pk if user is not None and user.is_authenticated else None
        structlog.contextvars.bind_contextvars(user_id=user_id)
        context: dict[str, object] = {
            "user": user_id,
            "request_id": getattr(request, "request_id", None),
            "method": request.method,
            "url": request.path,
        }
        client_request_id = getattr(request, "client_request_id", None)
        if client_request_id:
            context["client_request_id"] = client_request_id
        with pghistory.context(**context):
            return self.get_response(request)
