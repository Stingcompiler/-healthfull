"""Core services: authentication, preferences, password change, numbering, audit events.

Routers call exactly one function from here. Rule calculations live in ``domain``
(``domain.lockout``, ``domain.numbering``, ``domain.permissions``).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pghistory
import structlog
from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone, translation

from apps.core.models import AuthEvent, AuthEventKind, Policy, Sequence, User
from apps.core.permissions import effective_permissions
from domain.errors import DomainError
from domain.lockout import (
    LockState,
    is_locked,
    normalize,
    register_failure,
    register_success,
)
from domain.numbering import format_document_number

logger = structlog.get_logger(__name__)

_INVALID_CREDENTIALS_MESSAGE = "Invalid username or password"


# --- Audit helpers -----------------------------------------------------------------------


def client_ip(request: HttpRequest) -> str | None:
    """Client address; trusts ``X-Forwarded-For`` only when configured behind our proxy."""
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    addr = request.META.get("REMOTE_ADDR")
    return addr or None


def record_auth_event(
    kind: AuthEventKind,
    request: HttpRequest,
    *,
    user: User | None = None,
    username: str = "",
    **details: Any,
) -> AuthEvent:
    event = AuthEvent.objects.create(
        kind=kind,
        user=user,
        username=(username or (user.username if user else ""))[:150],
        ip_address=client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        request_id=str(getattr(request, "request_id", ""))[:64],
        details=details,
    )
    logger.info("auth_event", kind=str(kind), username=event.username, user_id=event.user_id)
    return event


# --- Current user ------------------------------------------------------------------------


def me_payload(user: User) -> dict[str, Any]:
    """Data for ``MeOut``: identity, roles, effective permissions and preferences."""
    return {
        "id": user.pk,
        "username": user.username,
        "full_name_ar": user.full_name_ar,
        "full_name_en": user.full_name_en,
        "roles": user.role_codes(),
        "permissions": sorted(effective_permissions(user)),
        "language": user.language,
        "theme": user.theme,
        "must_change_password": user.must_change_password,
    }


# --- Login / logout ----------------------------------------------------------------------


def _save_lock_state(user: User, state: LockState) -> None:
    user.failed_login_count = state.failed_count
    user.locked_until = state.locked_until
    user.save(update_fields=["failed_login_count", "locked_until"])


def _invalid_credentials() -> DomainError:
    return DomainError("INVALID_CREDENTIALS", _INVALID_CREDENTIALS_MESSAGE)


def _check_credentials(request: HttpRequest, username: str, password: str) -> User | DomainError:
    """Verify credentials and update lockout state. Runs inside one transaction.

    Returns the user on success, or the error to raise once the transaction has committed
    (so failure counters and audit rows are kept).
    """
    now = timezone.now()
    user = User.objects.select_for_update().filter(username=username).first()
    if user is None:
        # Spend the same hashing time as a real check so usernames cannot be probed by timing.
        User().set_password(password)
        record_auth_event(
            AuthEventKind.LOGIN_FAILED, request, username=username, reason="unknown_user"
        )
        return _invalid_credentials()

    state = normalize(user.lock_state, now)
    if is_locked(state, now) and state.locked_until is not None:
        retry_after = math.ceil((state.locked_until - now).total_seconds())
        record_auth_event(AuthEventKind.LOGIN_LOCKED, request, user=user)
        return DomainError(
            "ACCOUNT_LOCKED",
            "Account is temporarily locked after repeated failed logins",
            locked_until=state.locked_until.isoformat(),
            retry_after_seconds=retry_after,
        )

    password_ok = user.check_password(password)
    if not user.is_active:
        record_auth_event(AuthEventKind.LOGIN_FAILED, request, user=user, reason="inactive")
        return _invalid_credentials()
    if not password_ok:
        new_state = register_failure(state, now)
        _save_lock_state(user, new_state)
        record_auth_event(
            AuthEventKind.LOGIN_FAILED,
            request,
            user=user,
            reason="bad_password",
            failed_count=new_state.failed_count,
        )
        if new_state.locked_until is not None:
            record_auth_event(
                AuthEventKind.ACCOUNT_LOCKED,
                request,
                user=user,
                locked_until=new_state.locked_until.isoformat(),
            )
        return _invalid_credentials()

    if user.lock_state != register_success():
        _save_lock_state(user, register_success())
    return user


def login(request: HttpRequest, username: str, password: str) -> User:
    """Authenticate and start a session.

    Raises:
        DomainError: ``INVALID_CREDENTIALS`` (HTTP 401) or ``ACCOUNT_LOCKED`` (HTTP 423).
            Failure bookkeeping is committed before the error is raised.
    """
    with transaction.atomic():
        result = _check_credentials(request, username, password)
        if isinstance(result, User):
            # Rotates the session key and CSRF token; updates last_login via signal.
            django_login(request, result, backend="django.contrib.auth.backends.ModelBackend")
            request.session.set_expiry(Policy.load().session_idle_minutes * 60)
            pghistory.context(user=result.pk)
            record_auth_event(AuthEventKind.LOGIN_SUCCESS, request, user=result)
    if isinstance(result, DomainError):
        raise result
    return result


def logout(request: HttpRequest) -> None:
    """End the session. Idempotent: logging out without a session is a no-op."""
    user = request.user
    if isinstance(user, User) and user.is_authenticated:
        record_auth_event(AuthEventKind.LOGOUT, request, user=user)
    django_logout(request)


# --- Profile ---------------------------------------------------------------------------


def update_preferences(user: User, *, language: str | None, theme: str | None) -> User:
    fields: list[str] = []
    if language is not None and language != user.language:
        user.language = language
        fields.append("language")
    if theme is not None and theme != user.theme:
        user.theme = theme
        fields.append("theme")
    if fields:
        user.save(update_fields=fields)
    return user


def change_password(request: HttpRequest, user: User, old_password: str, new_password: str) -> None:
    """Change the user's password and keep the current session alive.

    Raises:
        DomainError: ``PASSWORD_INVALID`` with ``details.reason`` one of
            ``old_password_incorrect``, ``password_unchanged``, ``password_rejected``
            (the last with ``details.messages`` from Django's validators).
    """
    error: DomainError | None = None
    if not user.check_password(old_password):
        error = DomainError(
            "PASSWORD_INVALID", "Current password is incorrect", reason="old_password_incorrect"
        )
    elif old_password == new_password:
        error = DomainError(
            "PASSWORD_INVALID",
            "New password must differ from the current one",
            reason="password_unchanged",
        )
    else:
        try:
            with translation.override(user.language):
                validate_password(new_password, user)
        except ValidationError as exc:
            error = DomainError(
                "PASSWORD_INVALID",
                "New password does not meet the password policy",
                reason="password_rejected",
                messages=[str(m) for m in exc.messages],
            )
    if error is not None:
        record_auth_event(
            AuthEventKind.PASSWORD_CHANGE_FAILED, request, user=user, reason=error.details["reason"]
        )
        raise error

    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        record_auth_event(AuthEventKind.PASSWORD_CHANGED, request, user=user)


# --- Document numbering ------------------------------------------------------------------


def next_number(code: str, *, on: date | None = None) -> str:
    """Allocate the next document number for ``code`` in the year of ``on`` (default today).

    Gap-free and race-safe: the counter row is locked with ``SELECT ... FOR UPDATE`` and the
    lock is held until the caller's transaction commits, so call this inside the same
    transaction that creates the document.
    """
    year = (on or timezone.localdate()).year
    # Validate before touching the DB (raises INVALID_SEQUENCE_PREFIX etc.).
    format_document_number(code, year, 1)
    with transaction.atomic():
        Sequence.objects.bulk_create(
            [Sequence(code=code, year=year, last_value=0)], ignore_conflicts=True
        )
        seq = Sequence.objects.select_for_update().get(code=code, year=year)
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
        return format_document_number(code, year, seq.last_value)
