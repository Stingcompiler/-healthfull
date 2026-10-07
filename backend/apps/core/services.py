"""Core services: authentication, preferences, password change, numbering, audit events.

Routers call exactly one function from here. Rule calculations live in ``domain``
(``domain.lockout``, ``domain.numbering``, ``domain.permissions``).
"""

from __future__ import annotations

import ipaddress
import math
from datetime import date, datetime, timedelta
from typing import Any

import pghistory
import structlog
from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest
from django.utils import timezone, translation

from apps.core.models import (
    AuthEvent,
    AuthEventKind,
    LoginThrottle,
    Policy,
    Sequence,
    ThrottleScope,
    User,
)
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
from domain.throttle import hit, is_limited, retry_after_seconds

logger = structlog.get_logger(__name__)

_INVALID_CREDENTIALS_MESSAGE = "Invalid username or password"


# --- Audit helpers -----------------------------------------------------------------------


def _valid_ip(value: str | None) -> str | None:
    """Normalised IP address text, or None when ``value`` is not an IP address."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: HttpRequest) -> str | None:
    """Client address; trusts ``X-Forwarded-For`` only when configured behind our proxy.

    Values that are not IP addresses are ignored (falling back to ``REMOTE_ADDR``), so a
    forged header can never break the ``inet`` column of the audit table.
    """
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.headers.get("X-Forwarded-For", "")
        candidate = _valid_ip(forwarded.split(",")[0]) if forwarded else None
        if candidate:
            return candidate
    return _valid_ip(request.META.get("REMOTE_ADDR"))


def record_auth_event(
    kind: AuthEventKind,
    request: HttpRequest,
    *,
    user: User | None = None,
    username: str = "",
    **details: Any,
) -> AuthEvent | None:
    """Append one ``AuthEvent``. Never raises for a database error.

    The insert runs in its own savepoint: if it fails, the error is logged and the
    surrounding transaction (for example the failed-login counter update) still commits.
    """
    try:
        with transaction.atomic():
            event = AuthEvent.objects.create(
                kind=kind,
                user=user,
                username=(username or (user.username if user else ""))[:150],
                ip_address=client_ip(request),
                user_agent=request.headers.get("User-Agent", "")[:300],
                request_id=str(getattr(request, "request_id", ""))[:64],
                details=details,
            )
    except DatabaseError:
        logger.exception(
            "auth_event_write_failed",
            kind=str(kind),
            username=username or (user.username if user else ""),
        )
        return None
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
        "language": user.language or None,
        "theme": user.theme or None,
        "must_change_password": user.must_change_password,
    }


# --- Login / logout ----------------------------------------------------------------------


#: The one authentication backend (settings.AUTHENTICATION_BACKENDS); stored in sessions.
LOCKOUT_BACKEND = "apps.core.auth_backends.LockoutBackend"


def _save_lock_state(user: User, state: LockState) -> None:
    user.failed_login_count = state.failed_count
    user.locked_until = state.locked_until
    user.save(update_fields=["failed_login_count", "locked_until"])


def _invalid_credentials() -> DomainError:
    return DomainError("INVALID_CREDENTIALS", _INVALID_CREDENTIALS_MESSAGE)


def _locked_error(locked_until: datetime, now: datetime) -> DomainError:
    return DomainError(
        "ACCOUNT_LOCKED",
        "Account is temporarily locked after repeated failed logins",
        locked_until=locked_until.isoformat(),
        retry_after_seconds=math.ceil((locked_until - now).total_seconds()),
    )


def _ip_rule() -> tuple[int, timedelta]:
    return (
        int(getattr(settings, "LOGIN_IP_MAX_FAILURES", 30)),
        timedelta(seconds=int(getattr(settings, "LOGIN_IP_WINDOW_SECONDS", 15 * 60))),
    )


def _locked_throttle(scope: ThrottleScope, key: str) -> LoginThrottle:
    """The throttle row for ``(scope, key)``, created if needed and locked FOR UPDATE."""
    LoginThrottle.objects.bulk_create([LoginThrottle(scope=scope, key=key)], ignore_conflicts=True)
    return LoginThrottle.objects.select_for_update().get(scope=scope, key=key)


def _ip_throttle_error(
    request: HttpRequest, ip: str | None, username: str, now: datetime
) -> DomainError | None:
    """``RATE_LIMITED`` when ``ip`` has used up its failed-login budget, else None."""
    if not ip:
        return None
    row = LoginThrottle.objects.filter(scope=ThrottleScope.IP, key=ip).first()
    limit, window = _ip_rule()
    if row is None or not is_limited(row.window_state, now, limit=limit, window=window):
        return None
    retry_after = retry_after_seconds(row.window_state, now, window=window)
    record_auth_event(
        AuthEventKind.LOGIN_THROTTLED, request, username=username, retry_after_seconds=retry_after
    )
    return DomainError(
        "RATE_LIMITED",
        "Too many failed logins from this address; try again later",
        retry_after_seconds=retry_after,
    )


def _count_ip_failure(ip: str | None, now: datetime) -> None:
    if not ip:
        return
    _, window = _ip_rule()
    row = _locked_throttle(ThrottleScope.IP, ip)
    state = hit(row.window_state, now, window=window)
    row.count = state.count
    row.window_started_at = state.window_started_at
    row.save(update_fields=["count", "window_started_at", "updated_at"])


def _check_unknown_username(request: HttpRequest, username: str, now: datetime) -> DomainError:
    """Failure path for a username with no account, indistinguishable from a real one.

    The username gets the same lockout state machine as an account (stored in
    ``LoginThrottle``), so after 5 failures it answers 423 exactly like an existing user.
    """
    # The key column holds 150 characters, the longest valid username.
    row = _locked_throttle(ThrottleScope.USERNAME, username[:150])
    state = normalize(row.lock_state, now)
    if is_locked(state, now) and state.locked_until is not None:
        record_auth_event(
            AuthEventKind.LOGIN_LOCKED, request, username=username, reason="unknown_user"
        )
        return _locked_error(state.locked_until, now)
    # Spend the same hashing time as a real check so usernames cannot be probed by timing.
    User().set_password("x")
    new_state = register_failure(state, now)
    row.count = new_state.failed_count
    row.locked_until = new_state.locked_until
    row.save(update_fields=["count", "locked_until", "updated_at"])
    record_auth_event(AuthEventKind.LOGIN_FAILED, request, username=username, reason="unknown_user")
    if new_state.locked_until is not None:
        record_auth_event(
            AuthEventKind.ACCOUNT_LOCKED,
            request,
            username=username,
            locked_until=new_state.locked_until.isoformat(),
        )
    return _invalid_credentials()


def _check_credentials(
    request: HttpRequest, username: str, password: str, now: datetime
) -> User | DomainError:
    """Verify credentials and update lockout state. Runs inside one transaction."""
    user = User.objects.select_for_update().filter(username=username).first()
    if user is None:
        return _check_unknown_username(request, username, now)

    state = normalize(user.lock_state, now)
    if is_locked(state, now) and state.locked_until is not None:
        record_auth_event(AuthEventKind.LOGIN_LOCKED, request, user=user)
        return _locked_error(state.locked_until, now)

    password_ok = user.check_password(password)
    if password_ok and not user.is_active:
        # Right password, deactivated account: refuse without counting.
        record_auth_event(AuthEventKind.LOGIN_FAILED, request, user=user, reason="inactive")
        return _invalid_credentials()
    if not password_ok:
        # Wrong passwords count for inactive accounts too, so every username locks alike.
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


def authenticate_credentials(
    request: HttpRequest, username: str, password: str
) -> User | DomainError:
    """The one credential check behind every way of logging in.

    Used by the API login, the Django admin login form and ``LockoutBackend`` (so any
    ``django.contrib.auth.authenticate()`` call), which all share the per-address
    throttle, the per-account lockout and the audit trail. Bookkeeping is committed
    before returning, so it survives the caller raising the returned error.

    Returns:
        The user, or the error to raise: ``RATE_LIMITED`` (HTTP 429),
        ``ACCOUNT_LOCKED`` (423) or ``INVALID_CREDENTIALS`` (401).
    """
    now = timezone.now()
    ip = client_ip(request)
    with transaction.atomic():
        throttled = _ip_throttle_error(request, ip, username, now)
        if throttled is not None:
            return throttled
        result = _check_credentials(request, username, password, now)
        if isinstance(result, DomainError):
            _count_ip_failure(ip, now)
    return result


def on_user_logged_in(request: HttpRequest, user: User) -> None:
    """Session policy and audit for every login (API or admin), via ``user_logged_in``."""
    request.session.set_expiry(Policy.load().session_idle_minutes * 60)
    pghistory.context(user=user.pk)
    record_auth_event(AuthEventKind.LOGIN_SUCCESS, request, user=user)


def on_user_logged_out(request: HttpRequest, user: User) -> None:
    """Audit for every logout (API or admin), via ``user_logged_out``."""
    record_auth_event(AuthEventKind.LOGOUT, request, user=user)


def login(request: HttpRequest, username: str, password: str) -> dict[str, Any]:
    """Authenticate, start a session and return the ``MeOut`` payload.

    Raises:
        DomainError: ``INVALID_CREDENTIALS`` (HTTP 401), ``ACCOUNT_LOCKED`` (423) or
            ``RATE_LIMITED`` (429). Failure bookkeeping is committed before the raise.
    """
    result = authenticate_credentials(request, username, password)
    if isinstance(result, DomainError):
        raise result
    with transaction.atomic():
        # Rotates the session key and CSRF token. The user_logged_in signal sets the idle
        # expiry, updates last_login and writes the LOGIN_SUCCESS audit row.
        django_login(request, result, backend=LOCKOUT_BACKEND)
    return me_payload(result)


def logout(request: HttpRequest) -> None:
    """End the session (the logout audit row comes from the signal). Idempotent."""
    django_logout(request)


def unlock_accounts(request: HttpRequest, users: list[User], *, reason: str) -> int:
    """Clear the lockout of ``users`` (an administrator override, invariant 4).

    Each unlock writes an ``ACCOUNT_UNLOCKED`` audit row with the acting user, the reason
    and the previous lock state; accounts that are not locked or counting are skipped.
    Returns how many accounts were unlocked.
    """
    reason = reason.strip()
    if not reason:
        raise DomainError("REASON_REQUIRED", "A reason is required to unlock an account")
    actor = request.user
    unlocked = 0
    with transaction.atomic():
        for user in User.objects.select_for_update().filter(pk__in=[u.pk for u in users]):
            previous = user.lock_state
            if previous == register_success():
                continue
            _save_lock_state(user, register_success())
            record_auth_event(
                AuthEventKind.ACCOUNT_UNLOCKED,
                request,
                user=user,
                reason=reason[:500],
                actor_id=actor.pk if actor.is_authenticated else None,
                actor_username=actor.get_username() if actor.is_authenticated else "",
                previous_failed_count=previous.failed_count,
                previous_locked_until=(
                    previous.locked_until.isoformat() if previous.locked_until else None
                ),
            )
            unlocked += 1
    return unlocked


# --- Profile ---------------------------------------------------------------------------


def update_preferences(user: User, *, language: str | None, theme: str | None) -> dict[str, Any]:
    """Save language and/or theme and return the ``MeOut`` payload."""
    fields: list[str] = []
    if language is not None and language != user.language:
        user.language = language
        fields.append("language")
    if theme is not None and theme != user.theme:
        user.theme = theme
        fields.append("theme")
    if fields:
        user.save(update_fields=fields)
    return me_payload(user)


def _check_old_password(
    request: HttpRequest, user: User, old_password: str, now: datetime
) -> DomainError | None:
    """Verify the current password with the login lockout rules. Runs in a transaction.

    A session is not proof of identity (an unattended workstation), so wrong current
    passwords count like failed logins: the failure that locks the account also ends the
    session. While the account is locked the password is not checked at all.
    """
    locked = User.objects.select_for_update().get(pk=user.pk)
    state = normalize(locked.lock_state, now)
    if is_locked(state, now) and state.locked_until is not None:
        record_auth_event(
            AuthEventKind.PASSWORD_CHANGE_FAILED, request, user=user, reason="account_locked"
        )
        return _locked_error(state.locked_until, now)
    if locked.check_password(old_password):
        if locked.lock_state != register_success():
            _save_lock_state(locked, register_success())
        return None
    new_state = register_failure(state, now)
    _save_lock_state(locked, new_state)
    record_auth_event(
        AuthEventKind.PASSWORD_CHANGE_FAILED,
        request,
        user=user,
        reason="old_password_incorrect",
        failed_count=new_state.failed_count,
    )
    if new_state.locked_until is None:
        return DomainError(
            "PASSWORD_INVALID", "Current password is incorrect", reason="old_password_incorrect"
        )
    record_auth_event(
        AuthEventKind.ACCOUNT_LOCKED,
        request,
        user=user,
        locked_until=new_state.locked_until.isoformat(),
        source="change_password",
    )
    django_logout(request)
    return _locked_error(new_state.locked_until, now)


def _new_password_error(user: User, old_password: str, new_password: str) -> DomainError | None:
    if old_password == new_password:
        return DomainError(
            "PASSWORD_INVALID",
            "New password must differ from the current one",
            reason="password_unchanged",
        )
    try:
        with translation.override(user.language or settings.LANGUAGE_CODE):
            validate_password(new_password, user)
    except ValidationError as exc:
        return DomainError(
            "PASSWORD_INVALID",
            "New password does not meet the password policy",
            reason="password_rejected",
            messages=[str(m) for m in exc.messages],
        )
    return None


def change_password(request: HttpRequest, user: User, old_password: str, new_password: str) -> None:
    """Change the user's password and keep the current session alive.

    Raises:
        DomainError: ``PASSWORD_INVALID`` with ``details.reason`` one of
            ``old_password_incorrect``, ``password_unchanged``, ``password_rejected``
            (the last with ``details.messages`` from Django's validators);
            ``ACCOUNT_LOCKED`` (HTTP 423) while the account is locked, including right
            after the wrong current password that reached the lockout limit (that request
            also ends the session).
    """
    with transaction.atomic():
        error = _check_old_password(request, user, old_password, timezone.now())
    if error is None:
        error = _new_password_error(user, old_password, new_password)
        if error is not None:
            record_auth_event(
                AuthEventKind.PASSWORD_CHANGE_FAILED,
                request,
                user=user,
                reason=error.details["reason"],
            )
    if error is not None:
        raise error

    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "password_changed_at", "must_change_password"])
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
    if not connection.in_atomic_block:
        # In autocommit the increment would commit on its own, and a document insert that
        # fails afterwards would leave a permanent gap.
        raise RuntimeError(
            "next_number() must run inside the transaction that creates the document "
            "(wrap the caller in transaction.atomic())"
        )
    Sequence.objects.bulk_create(
        [Sequence(code=code, year=year, last_value=0)], ignore_conflicts=True
    )
    seq = Sequence.objects.select_for_update().get(code=code, year=year)
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return format_document_number(code, year, seq.last_value)
