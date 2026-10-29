"""Uniform JSON errors: every failure is ``{code, message, details}`` (ARCHITECTURE 4.11).

| Exception                         | Status | code                         |
|-----------------------------------|--------|------------------------------|
| ``domain.errors.DomainError``     | 409*   | the error's own code         |
| ``ninja.errors.ValidationError``  | 422    | ``VALIDATION_ERROR``         |
| ``AuthenticationError``           | 401    | ``NOT_AUTHENTICATED``        |
| ``PermissionDenied`` / authz      | 403    | ``PERMISSION_DENIED``        |
| CSRF failure                      | 403    | ``CSRF_FAILED``              |
| ``Http404`` / ``Model.DoesNotExist`` | 404 | ``NOT_FOUND``                |
| Django ``ValidationError``        | 422    | ``VALIDATION_ERROR``         |
| database guard (``CODE: ...``)    | 409    | ``DB_GUARD_CODES[CODE]``     |
| ``IntegrityError``                | 409    | ``CONFLICT``                 |
| ``ApiError``                      | any    | the error's own code         |
| anything else                     | 500    | ``INTERNAL_ERROR``           |

(*) A few domain codes have a more specific status, listed in ``DOMAIN_ERROR_STATUS``.

Database guards (triggers, ARCHITECTURE 4.9) raise ``'<CODE>: <detail>'``. Services check the
same rules first, so a guard firing means a race or a path the service missed; the user still
gets the guard's own translated code, never the SQL text (tables, ids, values), which is only
logged. A code not in ``DB_GUARD_CODES`` stays a 500 ``INTERNAL_ERROR``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import structlog
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, Throttled
from ninja.errors import ValidationError as NinjaValidationError

from domain.errors import DomainError

logger = structlog.get_logger(__name__)

#: Domain codes whose HTTP status is not the default 409.
DOMAIN_ERROR_STATUS: dict[str, int] = {
    "INVALID_CREDENTIALS": 401,
    "ACCOUNT_LOCKED": 423,
    "RATE_LIMITED": 429,
    # Patient portal sign-in (ADR 0016).
    "PORTAL_INVALID_CREDENTIALS": 401,
    "PORTAL_LOCKED": 423,
    # Guest booking (ADR 0029 C, D).
    "GUEST_INVALID_CREDENTIALS": 401,
    "IDEMPOTENCY_KEY_REQUIRED": 400,
    # The center website switched off answers as if there were no page (ADR 0028, 0029).
    "SITE_DISABLED": 404,
}

#: Database guard code (the text before ``:`` in a trigger's RAISE EXCEPTION) -> API code, all
#: answered 409. Every code a trigger in the schema raises is listed; a test reads the trigger
#: functions from the database and fails on any code missing here. Two guard codes have texts
#: that show details the service sends (``remaining``, ``effective_from``) and the trigger
#: cannot, so they answer a sibling code with a text of its own. ``pgtrigger`` is the prefix of
#: django-pgtrigger's own Protect/ReadOnly triggers ("pgtrigger: Cannot update rows from ...").
DB_GUARD_CODES: dict[str, str] = {
    "ACCOUNT_FIXED": "ACCOUNT_FIXED",
    "APPEND_ONLY": "APPEND_ONLY",
    "AUTHORIZATION_PERMANENT": "AUTHORIZATION_PERMANENT",
    "AUTHORIZATION_READONLY": "AUTHORIZATION_READONLY",
    "AUTHORIZATION_REVOKED": "AUTHORIZATION_REVOKED",
    "BATCH_EXPIRED": "BATCH_EXPIRED",
    "CLAIM_FINAL": "CLAIM_FINAL",
    "CLAIM_LINE_LOCKED": "CLAIM_LINE_LOCKED",
    "CLAIM_LINE_NOT_ACCRUED": "CLAIM_LINE_NOT_ACCRUED",
    "CLAIM_LINE_PERMANENT": "CLAIM_LINE_PERMANENT",
    "CLAIM_LINE_READONLY": "CLAIM_LINE_READONLY",
    "CLAIM_LINE_TRANSITION": "CLAIM_LINE_TRANSITION",
    "CLAIM_STATUS_INVALID": "CLAIM_STATUS_INVALID",
    "CREDIT_EXCEEDS_INVOICE": "CREDIT_EXCEEDS_INVOICE",
    "CREDIT_NOTE_EMPTY": "CREDIT_NOTE_EMPTY",
    "CREDIT_NOTE_FROZEN": "CREDIT_NOTE_FROZEN",
    "CREDIT_NOTE_LINES_NOT_FROZEN": "CREDIT_NOTE_LINES_NOT_FROZEN",
    "CREDIT_NOTE_REQUIRED": "CREDIT_NOTE_REQUIRED",
    "CREDIT_NOTE_TOTALS_MISMATCH": "CREDIT_NOTE_TOTALS_MISMATCH",
    "CREDIT_WRONG_INVOICE": "CREDIT_WRONG_INVOICE",
    "DISPENSE_EXCEEDS_LINE": "DISPENSE_EXCEEDS_LINE_GUARD",
    "DOCUMENT_FINAL": "DOCUMENT_FINAL",
    "HANDOVER_FINAL": "HANDOVER_FINAL",
    "HANDOVER_PERMANENT": "HANDOVER_PERMANENT",
    "HANDOVER_READONLY": "HANDOVER_READONLY",
    "INVOICE_EMPTY": "INVOICE_EMPTY",
    "INVOICE_FROZEN": "INVOICE_FROZEN",
    "INVOICE_LINES_NOT_FROZEN": "INVOICE_LINES_NOT_FROZEN",
    "INVOICE_TOTALS_MISMATCH": "INVOICE_TOTALS_MISMATCH",
    "JOURNAL_DIMENSION": "JOURNAL_DIMENSION",
    "JOURNAL_UNBALANCED": "JOURNAL_UNBALANCED",
    "LINE_AUTHORIZATION_FIXED": "LINE_AUTHORIZATION_FIXED",
    "LINE_BILLED_READONLY": "LINE_BILLED_READONLY",
    "LINE_BILLING_TRANSITION": "LINE_BILLING_TRANSITION",
    "LINE_NOT_DELETABLE": "LINE_NOT_DELETABLE",
    "LINE_NOT_ELIGIBLE": "LINE_NOT_ELIGIBLE",
    "LINE_NOT_INVOICED": "LINE_NOT_INVOICED",
    "LINE_NOT_ON_VISIT": "LINE_NOT_ON_VISIT",
    "LINE_PARTLY_DISPENSED": "LINE_PARTLY_DISPENSED",
    "LINE_TERMINAL": "LINE_TERMINAL",
    "PAYMENT_PERMANENT": "PAYMENT_PERMANENT",
    "PAYMENT_REJECTED": "PAYMENT_REJECTED",
    "PAYMENT_VERIFICATION_TRANSITION": "PAYMENT_VERIFICATION_TRANSITION",
    "PRICE_VERSION_BACKDATED": "PRICE_VERSION_BACKDATED",
    "PRICE_VERSION_LOCKED": "PRICE_VERSION_LOCKED_GUARD",
    "REFUND_DECISION_FINAL": "REFUND_DECISION_FINAL",
    "REFUND_FINAL": "REFUND_FINAL",
    "REFUND_TRANSITION": "REFUND_TRANSITION",
    "RESULT_FROZEN": "RESULT_FROZEN",
    "SHIFT_CLOSED": "SHIFT_CLOSED",
    "SHIFT_NOT_OPEN": "SHIFT_NOT_OPEN",
    "STOCK_BALANCE_DERIVED": "STOCK_BALANCE_DERIVED",
    "STOCK_ITEM_MISMATCH": "STOCK_ITEM_MISMATCH",
    "pgtrigger": "RECORD_PROTECTED",
}

_GUARD_MESSAGE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*):")


def db_guard_code(exc: BaseException) -> str | None:
    """The API code of a database guard error, or None when ``exc`` is not one we know."""
    match = _GUARD_MESSAGE.match(str(exc))
    return DB_GUARD_CODES.get(match.group(1)) if match else None


_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    423: "LOCKED",
    429: "RATE_LIMITED",
}


class ApiError(Exception):
    """A transport-level error with an explicit status and stable code.

    Business-rule violations should raise :class:`DomainError` from services instead.
    """

    def __init__(self, status: int, code: str, message: str = "", **details: Any) -> None:
        self.status = status
        self.code = code
        self.message = message or code
        self.details = details
        super().__init__(self.message)


class PermissionRequired(PermissionDenied):
    """Raised by ``require_perm`` when the user lacks a permission code."""

    def __init__(self, permission: str) -> None:
        self.permission = permission
        super().__init__(f"Permission required: {permission}")


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JsonResponse:
    """Plain Django JSON error response, for code paths outside ninja's handler chain."""
    return JsonResponse(error_body(code, message, details), status=status)


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for err in errors:
        clean.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return clean


def install_exception_handlers(api: NinjaAPI) -> None:
    """Register the uniform error handlers on a NinjaAPI instance."""

    def respond(
        request: HttpRequest,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> HttpResponse:
        return api.create_response(request, error_body(code, message, details), status=status)

    def on_domain_error(request: HttpRequest, exc: DomainError) -> HttpResponse:
        status = DOMAIN_ERROR_STATUS.get(exc.code, 409)
        return respond(request, status, exc.code, exc.message, exc.details)

    def on_api_error(request: HttpRequest, exc: ApiError) -> HttpResponse:
        return respond(request, exc.status, exc.code, exc.message, exc.details)

    def on_validation_error(request: HttpRequest, exc: NinjaValidationError) -> HttpResponse:
        return respond(
            request,
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            {"errors": _sanitize_validation_errors(exc.errors)},
        )

    def on_authentication_error(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        return respond(request, 401, "NOT_AUTHENTICATED", "Authentication required")

    def on_authorization_error(request: HttpRequest, exc: AuthorizationError) -> HttpResponse:
        return respond(request, 403, "PERMISSION_DENIED", "Permission denied")

    def on_permission_denied(request: HttpRequest, exc: PermissionDenied) -> HttpResponse:
        details: dict[str, Any] = {}
        if isinstance(exc, PermissionRequired):
            details["permission"] = exc.permission
        return respond(request, 403, "PERMISSION_DENIED", "Permission denied", details)

    def on_not_found(request: HttpRequest, exc: Http404 | ObjectDoesNotExist) -> HttpResponse:
        return respond(request, 404, "NOT_FOUND", "Not found")

    def on_django_validation_error(
        request: HttpRequest, exc: DjangoValidationError
    ) -> HttpResponse:
        # full_clean() / Model.clean(): field -> messages, or __all__ for non-field errors.
        if hasattr(exc, "error_dict"):
            fields = {field: [str(m) for m in msgs] for field, msgs in exc.message_dict.items()}
        else:
            fields = {"__all__": [str(m) for m in exc.messages]}
        return respond(
            request, 422, "VALIDATION_ERROR", "Request validation failed", {"fields": fields}
        )

    def on_db_guard(request: HttpRequest, code: str, exc: DatabaseError) -> HttpResponse:
        # The trigger text names tables, ids and values; log it, never return it.
        logger.warning("api.db_guard", path=request.path, code=code, error=str(exc))
        return respond(request, 409, code, "Refused by a data protection rule")

    def on_integrity_error(request: HttpRequest, exc: IntegrityError) -> HttpResponse:
        code = db_guard_code(exc)
        if code is not None:
            return on_db_guard(request, code, exc)
        # The constraint text can name tables and values; log it, never return it.
        logger.warning("api.integrity_error", path=request.path, error=str(exc))
        return respond(request, 409, "CONFLICT", "The change conflicts with existing data")

    def on_database_error(request: HttpRequest, exc: DatabaseError) -> HttpResponse:
        code = db_guard_code(exc)
        if code is not None:
            return on_db_guard(request, code, exc)
        return on_unhandled(request, exc)

    def on_throttled(request: HttpRequest, exc: Throttled) -> HttpResponse:
        return respond(request, 429, "RATE_LIMITED", "Too many requests", {"wait": exc.wait})

    def on_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
        if exc.status_code == 403 and "csrf" in exc.message.lower():
            return respond(request, 403, "CSRF_FAILED", "CSRF verification failed")
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return respond(request, exc.status_code, code, exc.message)

    def on_unhandled(request: HttpRequest, exc: Exception) -> HttpResponse:
        logger.exception("api.unhandled_exception", path=request.path, method=request.method)
        return respond(request, 500, "INTERNAL_ERROR", "Internal server error")

    handlers: list[tuple[type[Exception], Callable[[HttpRequest, Any], HttpResponse]]] = [
        (Exception, on_unhandled),
        (DomainError, on_domain_error),
        (ApiError, on_api_error),
        (NinjaValidationError, on_validation_error),
        (HttpError, on_http_error),
        (AuthenticationError, on_authentication_error),
        (AuthorizationError, on_authorization_error),
        (Throttled, on_throttled),
        (PermissionDenied, on_permission_denied),
        (Http404, on_not_found),
        (ObjectDoesNotExist, on_not_found),
        (DjangoValidationError, on_django_validation_error),
        (DatabaseError, on_database_error),
        (IntegrityError, on_integrity_error),
    ]
    for exc_class, handler in handlers:
        api.add_exception_handler(exc_class, handler)
