"""Core services: authentication, preferences, password change, numbering, audit events.

Routers call exactly one function from here. Rule calculations live in ``domain``
(``domain.lockout``, ``domain.numbering``, ``domain.permissions``).
"""

from __future__ import annotations

import ipaddress
import math
import re
import uuid
from collections.abc import Iterable
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
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import DatabaseError, connection, transaction
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone, translation

from apps.core import roles
from apps.core.models import (
    AuthEvent,
    AuthEventKind,
    CenterProfile,
    Department,
    DoctorProfile,
    LoginThrottle,
    Notification,
    PaperSize,
    Policy,
    PrintDocument,
    PrintTemplate,
    ReasonCategory,
    ReasonCode,
    Role,
    RolePermission,
    Room,
    Sequence,
    ThrottleScope,
    User,
    UserRole,
)
from apps.core.permissions import PERMISSIONS, effective_permissions, role_permissions
from domain.errors import DomainError
from domain.lockout import (
    LockState,
    is_locked,
    normalize,
    register_failure,
    register_success,
)
from domain.numbering import format_document_number
from domain.permissions import MatrixChange, plan_matrix_update, role_grants
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


# --- Shared helpers for the money and order services -------------------------------------
#
# Used by ``apps.orders``, ``apps.billing``, ``apps.payments`` and ``apps.ledger`` services:
# permission checks that are business rules (approvals and overrides, invariant 4), reason
# codes from the configurable lists, and in-app notifications (FEATURES 0.13).


def holds_permission(user: User, code: str) -> bool:
    """Whether ``user`` holds permission ``code`` (roles, overrides, superuser)."""
    return code in effective_permissions(user)


def require_permission(user: User, code: str) -> None:
    """Raise ``PermissionRequired`` (HTTP 403 ``PERMISSION_DENIED``) unless ``user`` holds it.

    Routers check the permission of the action itself; services call this for permissions
    that are part of the business rule (who may approve, confirm, override).
    """
    from api.errors import PermissionRequired

    if not holds_permission(user, code):
        raise PermissionRequired(code)


def resolve_reason(reason: ReasonCode | str | None, category: str, note: str = "") -> ReasonCode:
    """Return the active ``ReasonCode`` of ``category`` given as an instance or its code.

    Uses the same error codes as the visits and pharmacy services so the frontend shows one
    message per case.

    Raises:
        DomainError: ``REASON_REQUIRED`` when no reason is given; ``REASON_UNKNOWN`` when the
            code is unknown, inactive or of another category; ``REASON_NOTE_REQUIRED`` when
            the code needs an explanation and ``note`` is blank.
    """
    if reason is None or reason == "":
        raise DomainError("REASON_REQUIRED", "A reason is required for this action")
    if isinstance(reason, ReasonCode):
        found: ReasonCode | None = reason
    else:
        found = ReasonCode.objects.filter(category=category, code=str(reason)).first()
    if found is None or found.category != category or not found.active:
        raise DomainError(
            "REASON_UNKNOWN",
            "Unknown or inactive reason code for this action",
            category=category,
            reason_code=str(getattr(found, "code", reason)),
        )
    if found.requires_note and not note.strip():
        raise DomainError(
            "REASON_NOTE_REQUIRED", "This reason needs an explanation", reason_code=found.code
        )
    return found


def notify_users(users: Iterable[User], kind: str, *, dedupe_key: str = "", **payload: Any) -> int:
    """Create one in-app notification of ``kind`` per distinct active user; returns the count.

    With ``dedupe_key`` (time-based alerts, FEATURES 0.13) a user who already has a
    notification with that key gets no second one (also under concurrent runs: a partial
    unique index backs it).
    """
    key = dedupe_key[:120]
    rows = []
    seen: set[int] = set()
    if key:
        seen.update(Notification.objects.filter(key=key).values_list("user_id", flat=True))
    for user in users:
        if user.pk in seen or not user.is_active:
            continue
        seen.add(user.pk)
        rows.append(Notification(user=user, kind=kind[:60], payload=payload, key=key))
    Notification.objects.bulk_create(rows, ignore_conflicts=bool(key))
    return len(rows)


def notify_roles(
    role_codes: Iterable[str], kind: str, *, dedupe_key: str = "", **payload: Any
) -> int:
    """Notify every active user holding one of ``role_codes`` (e.g. managers, FLOW step 9)."""
    users = User.objects.filter(is_active=True, roles__code__in=list(role_codes)).distinct()
    return notify_users(users, kind, dedupe_key=dedupe_key, **payload)


# =========================================================================================
# Administration (FEATURES 0.2, 0.3, 13.1-13.7). Every write runs in one transaction with a
# pghistory context naming the acting user and why, so the audit trail shows who changed
# what (FEATURES 0.4). Rules come from ``domain.permissions`` and ``domain.schedule``.
# =========================================================================================

_USERNAME_RE = re.compile(r"^[\w.@+-]{1,150}\Z")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,19}\Z")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,39}\Z")

#: Grants the matrix editor never revokes: without them nobody could manage users or the
#: matrix itself any more (only the break-glass superuser could repair it).
PROTECTED_GRANTS: frozenset[tuple[str, str]] = frozenset(
    {(roles.ADMIN, "core.manage_roles"), (roles.ADMIN, "core.manage_users")}
)

#: Document number prefixes issued by ``next_number`` (FEATURES 13.6), in workflow order.
DOCUMENT_SEQUENCES: tuple[str, ...] = (
    "PT",
    "VIS",
    "ADM",
    "INV",
    "CN",
    "RCP",
    "SH",
    "RFD",
    "HND",
    "LAB",
    "DSP",
    "GRN",
    "ADJ",
    "CNT",
    "TRF",
    "RTN",
    "CLM",
    "PP",
)

LOGO_MAX_BYTES = 1024 * 1024

#: Image types a logo may have, by their leading bytes. SVG is refused: it can carry script.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)


def _require_reason(reason: str, action: str) -> str:
    text = (reason or "").strip()
    if not text:
        raise DomainError("REASON_REQUIRED", f"A reason is required to {action}")
    return text[:500]


def _check_code(code: str, *, pattern: re.Pattern[str] = _CODE_RE) -> str:
    value = (code or "").strip()
    if not pattern.match(value):
        raise DomainError(
            "INVALID_CODE",
            "Codes use upper-case letters, digits, '-' and '_' and start with a letter",
            value=value,
        )
    return value


def _clean(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _check_fields(fields: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Not editable {what} fields: {sorted(unknown)}")


# --- Users -------------------------------------------------------------------------------


def list_users(
    *, q: str | None = None, role: str | None = None, active: bool | None = None
) -> QuerySet[User]:
    """Staff accounts for the users screen, filtered by text, role and active flag."""
    qs = User.objects.prefetch_related("roles").select_related("doctor_profile")
    text = (q or "").strip()
    if text:
        qs = qs.filter(
            Q(username__icontains=text)
            | Q(full_name_ar__icontains=text)
            | Q(full_name_en__icontains=text)
            | Q(phone__icontains=text)
        )
    if role:
        qs = qs.filter(roles__code=role)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs.distinct().order_by("username")


def get_user(user_id: int) -> User:
    return User.objects.prefetch_related("roles").select_related("doctor_profile").get(pk=user_id)


def _check_role_codes(codes: Iterable[str]) -> list[str]:
    wanted = sorted(set(codes))
    if not wanted:
        raise DomainError("ROLE_REQUIRED", "A user needs at least one role")
    unknown = [c for c in wanted if c not in roles.ROLE_CODES]
    if unknown:
        raise DomainError("ROLE_UNKNOWN", "Unknown role code", role=unknown[0])
    return wanted


def _password_error(password: str, user: User) -> DomainError | None:
    try:
        validate_password(password, user)
    except ValidationError as exc:
        return DomainError(
            "PASSWORD_INVALID",
            "The password does not meet the password policy",
            reason="password_rejected",
            messages=[str(m) for m in exc.messages],
        )
    return None


def _set_roles(user: User, codes: list[str]) -> None:
    current = set(user.roles.values_list("code", flat=True))
    wanted = set(codes)
    if current == wanted:
        return
    UserRole.objects.filter(user=user, role__code__in=current - wanted).delete()
    for role in Role.objects.filter(code__in=wanted - current).order_by("code"):
        UserRole.objects.create(user=user, role=role)


def _guard_role_change(actor: User, user: User | None, before: set[str], after: set[str]) -> None:
    """Role assignment never grants more than ``core.manage_users`` itself allows.

    Giving or taking the admin role, or adding any role to one's own account, needs
    ``core.manage_roles`` (which can rewrite the matrix anyway). Otherwise a holder of
    ``core.manage_users`` alone could make themselves (or an accomplice) administrator.

    Raises:
        PermissionRequired: HTTP 403 ``PERMISSION_DENIED`` (``details.permission``).
    """
    admin_changed = (roles.ADMIN in before) != (roles.ADMIN in after)
    self_added = user is not None and user.pk == actor.pk and bool(after - before)
    if admin_changed or self_added:
        require_permission(actor, "core.manage_roles")


#: Holding any of these makes an account an administrator for account-takeover purposes.
_ACCOUNT_ADMIN_PERMISSIONS = frozenset({"core.manage_roles", "core.manage_users"})


def _guard_privileged_target(actor: User, user: User, role_codes: Iterable[str]) -> None:
    """Taking over an administrator's account needs ``core.manage_roles``.

    Resetting the password of, unlocking, deactivating or reactivating another account that
    holds the admin role, or any role granting ``core.manage_users`` or ``core.manage_roles``,
    would let a holder of ``core.manage_users`` alone sign in as (or lock out) someone with
    more rights. One's own account is exempt: the actor already controls it.

    Raises:
        PermissionRequired: HTTP 403 ``PERMISSION_DENIED`` (``details.permission``).
    """
    if user.pk == actor.pk:
        return
    codes = set(role_codes)
    if roles.ADMIN in codes or role_permissions(codes) & _ACCOUNT_ADMIN_PERMISSIONS:
        require_permission(actor, "core.manage_roles")


def _protect_superuser(actor: User, user: User) -> None:
    if user.is_superuser and not actor.is_superuser:
        raise DomainError(
            "SUPERUSER_PROTECTED", "Only a superuser can change the break-glass account"
        )


def create_user(
    actor: User,
    *,
    username: str,
    password: str,
    role_codes: Iterable[str],
    full_name_ar: str = "",
    full_name_en: str = "",
    phone: str = "",
) -> User:
    """Create a staff account that must change its password at first login (FEATURES 0.1).

    Raises:
        DomainError: ``INVALID_USERNAME``, ``USERNAME_TAKEN``, ``ROLE_REQUIRED``,
            ``ROLE_UNKNOWN``, ``PASSWORD_INVALID`` (``details.messages`` lists why).
        PermissionRequired: the admin role without ``core.manage_roles``.
    """
    name = (username or "").strip()
    if not _USERNAME_RE.match(name):
        raise DomainError(
            "INVALID_USERNAME", "Usernames use letters, digits and @ . + - _ only", username=name
        )
    codes = _check_role_codes(role_codes)
    _guard_role_change(actor, None, set(), set(codes))
    user = User(
        username=name,
        full_name_ar=full_name_ar.strip(),
        full_name_en=full_name_en.strip(),
        phone=phone.strip(),
        must_change_password=True,
    )
    error = _password_error(password, user)
    if error is not None:
        raise error
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create user"):
        if User.objects.filter(username__iexact=name).exists():
            raise DomainError("USERNAME_TAKEN", "This username is already in use", username=name)
        user.set_password(password)
        user.save()
        _set_roles(user, codes)
    return get_user(user.pk)


def _lock_admins() -> list[int]:
    """Lock the active administrators (id order) and return their ids."""
    return list(
        User.objects.select_for_update()
        .filter(is_active=True, roles__code=roles.ADMIN)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def update_user(
    actor: User,
    user_id: int,
    *,
    full_name_ar: str | None = None,
    full_name_en: str | None = None,
    phone: str | None = None,
    is_active: bool | None = None,
    role_codes: Iterable[str] | None = None,
) -> User:
    """Edit a staff account: names, phone, active flag and roles (FEATURES 13.3).

    Raises:
        DomainError: ``SUPERUSER_PROTECTED``, ``CANNOT_DEACTIVATE_SELF``, ``ROLE_REQUIRED``,
            ``ROLE_UNKNOWN``, ``LAST_ADMIN`` (the last active administrator would go).
        PermissionRequired: the admin role or one's own roles change, or an
            administrator's account is (de)activated, without ``core.manage_roles``.
    """
    codes = _check_role_codes(role_codes) if role_codes is not None else None
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit user"):
        admins = _lock_admins()
        user = User.objects.select_for_update().get(pk=user_id)
        _protect_superuser(actor, user)
        if is_active is False and user.pk == actor.pk:
            raise DomainError("CANNOT_DEACTIVATE_SELF", "You cannot deactivate your own account")
        active_after = user.is_active if is_active is None else is_active
        roles_before = user.role_codes()
        roles_after = roles_before if codes is None else codes
        _guard_role_change(actor, user, set(roles_before), set(roles_after))
        if is_active is not None and is_active != user.is_active:
            _guard_privileged_target(actor, user, roles_before)
        if (
            user.pk in admins
            and len(admins) == 1
            and not (active_after and roles.ADMIN in roles_after)
        ):
            raise DomainError(
                "LAST_ADMIN", "The center must keep at least one active administrator"
            )
        fields: list[str] = []
        for attr, value in (
            ("full_name_ar", full_name_ar),
            ("full_name_en", full_name_en),
            ("phone", phone),
        ):
            if value is not None and value.strip() != getattr(user, attr):
                setattr(user, attr, value.strip())
                fields.append(attr)
        if is_active is not None and is_active != user.is_active:
            user.is_active = is_active
            fields.append("is_active")
        if fields:
            user.save(update_fields=fields)
        if codes is not None:
            _set_roles(user, codes)
    return get_user(user_id)


def reset_password(request: HttpRequest, actor: User, user_id: int, new_password: str) -> User:
    """Set a temporary password that the user must change at the next login (FEATURES 0.1).

    The user's other sessions end (Django checks the password hash on every request).

    Raises:
        DomainError: ``SUPERUSER_PROTECTED``, ``PASSWORD_INVALID``.
        PermissionRequired: an administrator's account without ``core.manage_roles``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="password reset"):
        user = User.objects.select_for_update().get(pk=user_id)
        _protect_superuser(actor, user)
        _guard_privileged_target(actor, user, user.role_codes())
        error = _password_error(new_password, user)
        if error is not None:
            raise error
        user.set_password(new_password)
        user.must_change_password = True
        user.save(update_fields=["password", "password_changed_at", "must_change_password"])
        if user.pk == actor.pk:
            update_session_auth_hash(request, user)
        record_auth_event(
            AuthEventKind.PASSWORD_RESET,
            request,
            user=user,
            actor_id=actor.pk,
            actor_username=actor.get_username(),
        )
    return get_user(user_id)


def unlock_user(request: HttpRequest, actor: User, user_id: int, reason: str) -> User:
    """Clear a lockout with a reason (invariant 4); audited as ``ACCOUNT_UNLOCKED``.

    Raises:
        DomainError: ``REASON_REQUIRED``, ``SUPERUSER_PROTECTED``, ``USER_NOT_LOCKED``.
        PermissionRequired: an administrator's account without ``core.manage_roles``.
    """
    text = _require_reason(reason, "unlock an account")
    user = User.objects.get(pk=user_id)
    _protect_superuser(actor, user)
    _guard_privileged_target(actor, user, user.role_codes())
    with pghistory.context(user=actor.pk, reason=f"unlock: {text}"):
        if unlock_accounts(request, [user], reason=text) == 0:
            raise DomainError("USER_NOT_LOCKED", "This account has no failed logins to clear")
    return get_user(user_id)


# --- Roles and the permission matrix (FEATURES 0.2, 0.3) ----------------------------------


def role_summaries() -> list[dict[str, Any]]:
    """Every role with how many active users hold it."""
    counts: dict[str, int] = {}
    for code in UserRole.objects.filter(user__is_active=True).values_list("role__code", flat=True):
        counts[code] = counts.get(code, 0) + 1
    return [
        {
            "code": role.code,
            "name_ar": role.name_ar,
            "name_en": role.name_en,
            "user_count": counts.get(role.code, 0),
        }
        for role in Role.objects.order_by("pk")
    ]


def _overrides() -> dict[tuple[str, str], bool]:
    return {
        (role_code, code): allowed
        for role_code, code, allowed in RolePermission.objects.values_list(
            "role__code", "code", "allowed"
        )
    }


def permission_matrix() -> dict[str, Any]:
    """Roles and, per registered permission code, which roles grant it now."""
    defaults = {code: perm.default_roles for code, perm in PERMISSIONS.items()}
    overrides = _overrides()
    role_rows = role_summaries()
    role_codes = [r["code"] for r in role_rows]
    rows = []
    for code in sorted(PERMISSIONS):
        perm = PERMISSIONS[code]
        rows.append(
            {
                "code": code,
                "app": code.split(".", 1)[0],
                "label_ar": perm.label_ar,
                "label_en": perm.label_en,
                "default_roles": sorted(perm.default_roles),
                "granted_roles": [
                    r for r in role_codes if role_grants(r, code, defaults, overrides)
                ],
                "overridden_roles": sorted(r for (r, c) in overrides if c == code),
                "protected_roles": sorted(r for (r, c) in PROTECTED_GRANTS if c == code),
            }
        )
    return {"roles": role_rows, "permissions": rows}


def update_permission_matrix(
    actor: User, changes: Iterable[tuple[str, str, bool]], *, reason: str
) -> dict[str, Any]:
    """Grant or revoke permission codes per role, with a reason (FEATURES 0.3, audited).

    Each change is ``(role, code, allowed)``. Cells that go back to their default lose their
    override row; the rest store one. Returns the matrix and the cells that changed.

    Raises:
        DomainError: ``REASON_REQUIRED``, ``PERMISSION_UNKNOWN``, ``ROLE_UNKNOWN``,
            ``MATRIX_CHANGE_CONFLICT``, ``PERMISSION_PROTECTED``.
    """
    text = _require_reason(reason, "change permissions")
    wanted = [MatrixChange(role, code, allowed) for role, code, allowed in changes]
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"permission matrix: {text}"),
    ):
        # One editor at a time: concurrent edits would plan against stale overrides.
        role_rows = {r.code: r for r in Role.objects.select_for_update().order_by("pk")}
        plan = plan_matrix_update(
            {code: perm.default_roles for code, perm in PERMISSIONS.items()},
            _overrides(),
            wanted,
            roles=role_rows.keys(),
            protected=PROTECTED_GRANTS,
        )
        for role_code, code in sorted(plan.deletes):
            RolePermission.objects.filter(role=role_rows[role_code], code=code).delete()
        for (role_code, code), allowed in sorted(plan.upserts.items()):
            RolePermission.objects.update_or_create(
                role=role_rows[role_code], code=code, defaults={"allowed": allowed}
            )
        logger.info(
            "permission_matrix_changed",
            actor=actor.pk,
            changed=[(c.role, c.code, c.allowed) for c in plan.changed],
        )
    result = permission_matrix()
    result["changed"] = [
        {"role": c.role, "code": c.code, "allowed": c.allowed} for c in plan.changed
    ]
    return result


# --- Center profile and logo (FEATURES 13.1) ----------------------------------------------


def center_profile() -> CenterProfile:
    return CenterProfile.load()


def _locked_center() -> CenterProfile:
    CenterProfile.load()
    return CenterProfile.objects.select_for_update().get(pk=CenterProfile.SINGLETON_PK)


def update_center_profile(actor: User, **fields: Any) -> CenterProfile:
    """Save the center's name, address, numbers and digit style (printed on documents)."""
    _check_fields(
        fields,
        {"name_ar", "name_en", "address", "phone", "registration_no", "tax_no", "digits"},
        "center profile",
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="center profile"):
        profile = _locked_center()
        for attr, value in fields.items():
            setattr(profile, attr, _clean(value))
        profile.full_clean(exclude=["logo"])
        profile.save()
    return profile


def sniff_image(head: bytes) -> tuple[str, str] | None:
    """``(extension, content type)`` of a PNG, JPEG, GIF or WebP image, else None."""
    for signature, ext, content_type in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return ext, content_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _delete_logo_later(profile: CenterProfile, name: str) -> None:
    if name:
        storage = profile.logo.storage
        transaction.on_commit(lambda: storage.delete(name))


def set_center_logo(actor: User, upload: UploadedFile) -> CenterProfile:
    """Store a new logo under MEDIA_ROOT (``center/``), replacing the old file.

    Raises:
        DomainError: ``LOGO_TOO_LARGE`` (over 1 MB), ``LOGO_INVALID_TYPE`` (not PNG, JPEG,
            GIF or WebP by content).
    """
    data = upload.read(LOGO_MAX_BYTES + 1)
    if (upload.size or 0) > LOGO_MAX_BYTES or len(data) > LOGO_MAX_BYTES:
        raise DomainError(
            "LOGO_TOO_LARGE", "The logo must be 1 MB or smaller", max_bytes=LOGO_MAX_BYTES
        )
    kind = sniff_image(data[:16])
    if kind is None:
        raise DomainError("LOGO_INVALID_TYPE", "The logo must be a PNG, JPEG, GIF or WebP image")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="center logo"):
        profile = _locked_center()
        old = profile.logo.name
        profile.logo.save(f"logo-{uuid.uuid4().hex[:12]}.{kind[0]}", ContentFile(data), save=False)
        profile.save()
        _delete_logo_later(profile, old)
    return profile


def clear_center_logo(actor: User) -> CenterProfile:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="center logo removed"):
        profile = _locked_center()
        old = profile.logo.name
        if old:
            profile.logo.name = ""
            profile.save()
            _delete_logo_later(profile, old)
    return profile


def center_logo() -> tuple[bytes, str]:
    """The stored logo's bytes and content type (``NOT_FOUND`` when there is none)."""
    profile = CenterProfile.load()
    if not profile.logo.name:
        raise CenterProfile.DoesNotExist("No logo")
    try:
        with profile.logo.open("rb") as handle:
            data = handle.read(LOGO_MAX_BYTES + 1)
    except FileNotFoundError:
        raise CenterProfile.DoesNotExist("Logo file missing") from None
    kind = sniff_image(data[:16])
    if kind is None:
        raise CenterProfile.DoesNotExist("Logo file is not an image")
    return data, kind[1]


# --- Policy (FEATURES 13.4) ---------------------------------------------------------------

_POLICY_FIELDS = {
    "allow_partial_payment",
    "pending_transfer_alert_days",
    "partial_dispense_remainder",
    "show_estimated_cost",
    "follow_up_window_days",
    "follow_up_discount_percent",
    "discount_limit_percent",
    "session_idle_minutes",
    "perform_first_roles",
    "claims_second_approver",
}


def policy() -> Policy:
    return Policy.load()


def update_policy(actor: User, **fields: Any) -> Policy:
    """Save the policy switches. ``default_pay_first`` is not editable (invariant 1).

    Raises:
        ValidationError: a value out of range or an unknown role code (HTTP 422 with fields).
    """
    _check_fields(fields, _POLICY_FIELDS, "policy")
    # A client that does not send the claims switch (older screens) keeps its value.
    if fields.get("claims_second_approver", False) is None:
        fields.pop("claims_second_approver")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="policy"):
        Policy.load()
        current = Policy.objects.select_for_update().get(pk=Policy.SINGLETON_PK)
        for attr, value in fields.items():
            setattr(current, attr, value)
        if isinstance(current.perform_first_roles, list):
            current.perform_first_roles = sorted(set(current.perform_first_roles))
        if isinstance(current.discount_limit_percent, dict):
            current.discount_limit_percent = dict(sorted(current.discount_limit_percent.items()))
        current.full_clean()
        current.save()
    return current


# --- Departments and rooms (FEATURES 13.2) ------------------------------------------------


def list_departments(*, active: bool | None = None) -> QuerySet[Department]:
    qs = Department.objects.annotate(
        room_count=Count("rooms", distinct=True),
        doctor_count=Count("doctors", filter=Q(doctors__active=True), distinct=True),
    )
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("sort_order", "code")


def create_department(
    actor: User,
    *,
    code: str,
    name_ar: str,
    name_en: str,
    active: bool = True,
    sort_order: int = 0,
) -> Department:
    """Raises ``INVALID_CODE``, ``DEPARTMENT_CODE_TAKEN``."""
    value = _check_code(code)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create department"):
        if Department.objects.filter(code__iexact=value).exists():
            raise DomainError("DEPARTMENT_CODE_TAKEN", "This department code exists", value=value)
        dept = Department.objects.create(
            code=value,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            active=active,
            sort_order=sort_order,
        )
    return list_departments().get(pk=dept.pk)


def update_department(actor: User, department_id: int, **fields: Any) -> Department:
    _check_fields(fields, {"name_ar", "name_en", "active", "sort_order"}, "department")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit department"):
        dept = Department.objects.select_for_update().get(pk=department_id)
        for attr, value in fields.items():
            setattr(dept, attr, _clean(value))
        dept.save()
    return list_departments().get(pk=department_id)


def list_rooms(*, department_id: int | None = None, active: bool | None = None) -> QuerySet[Room]:
    qs = Room.objects.select_related("department")
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("code")


def _active_department(department_id: int) -> Department:
    dept = Department.objects.get(pk=department_id)
    if not dept.active:
        raise DomainError("DEPARTMENT_INACTIVE", "The department is inactive", department=dept.code)
    return dept


def create_room(
    actor: User,
    *,
    code: str,
    name_ar: str,
    name_en: str,
    department_id: int | None = None,
    active: bool = True,
) -> Room:
    """Raises ``INVALID_CODE``, ``ROOM_CODE_TAKEN``, ``DEPARTMENT_INACTIVE``."""
    value = _check_code(code)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create room"):
        if Room.objects.filter(code__iexact=value).exists():
            raise DomainError("ROOM_CODE_TAKEN", "This room code exists", value=value)
        room = Room.objects.create(
            code=value,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            department=_active_department(department_id) if department_id is not None else None,
            active=active,
        )
    return list_rooms().get(pk=room.pk)


def update_room(actor: User, room_id: int, **fields: Any) -> Room:
    _check_fields(fields, {"name_ar", "name_en", "active", "department_id"}, "room")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit room"):
        room = Room.objects.select_for_update().get(pk=room_id)
        for attr, value in fields.items():
            if attr == "department_id":
                room.department = _active_department(value) if value is not None else None
            else:
                setattr(room, attr, _clean(value))
        room.save()
    return list_rooms().get(pk=room_id)


# --- Doctors and weekly schedules (FEATURES 13.2) -----------------------------------------


def list_doctors(
    *, department_id: int | None = None, active: bool | None = None
) -> QuerySet[DoctorProfile]:
    from apps.visits.services import schedule_prefetch

    qs = DoctorProfile.objects.select_related(
        "user", "department", "consultation_service"
    ).prefetch_related(schedule_prefetch())
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("department__sort_order", "user__username")


def get_doctor(doctor_id: int) -> DoctorProfile:
    return list_doctors().get(pk=doctor_id)


def _consultation_service(service_id: int | None) -> Any:
    if service_id is None:
        return None
    from apps.catalog.models import Service, ServiceKind

    service = Service.objects.get(pk=service_id)
    if service.kind != ServiceKind.CONSULTATION or not service.active:
        raise DomainError(
            "CONSULTATION_SERVICE_INVALID",
            "The consultation fee must be an active consultation service",
            service=service.code,
        )
    return service


def list_doctor_candidates() -> QuerySet[User]:
    """Active users with the doctor role and no clinical profile yet (the doctor picker of
    the departments screen, which must not need ``core.manage_users``)."""
    return (
        User.objects.filter(is_active=True, roles__code=roles.DOCTOR, doctor_profile__isnull=True)
        .distinct()
        .order_by("username")
    )


def create_doctor(
    actor: User,
    *,
    user_id: int,
    department_id: int,
    specialty_ar: str = "",
    specialty_en: str = "",
    consultation_service_id: int | None = None,
    active: bool = True,
) -> DoctorProfile:
    """Give a user with the doctor role a clinical profile (department, specialty, fee).

    Raises:
        DomainError: ``DOCTOR_ROLE_REQUIRED``, ``DOCTOR_PROFILE_EXISTS``,
            ``DEPARTMENT_INACTIVE``, ``CONSULTATION_SERVICE_INVALID``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create doctor"):
        user = User.objects.select_for_update().get(pk=user_id)
        if roles.DOCTOR not in user.role_codes():
            raise DomainError(
                "DOCTOR_ROLE_REQUIRED",
                "The user must hold the doctor role",
                username=user.username,
            )
        if DoctorProfile.objects.filter(user=user).exists():
            raise DomainError(
                "DOCTOR_PROFILE_EXISTS",
                "This user already has a doctor profile",
                username=user.username,
            )
        profile = DoctorProfile.objects.create(
            user=user,
            department=_active_department(department_id),
            specialty_ar=specialty_ar.strip(),
            specialty_en=specialty_en.strip(),
            consultation_service=_consultation_service(consultation_service_id),
            active=active,
        )
    return get_doctor(profile.pk)


def update_doctor(actor: User, doctor_id: int, **fields: Any) -> DoctorProfile:
    """Raises ``DEPARTMENT_INACTIVE``, ``CONSULTATION_SERVICE_INVALID``."""
    _check_fields(
        fields,
        {"department_id", "specialty_ar", "specialty_en", "consultation_service_id", "active"},
        "doctor",
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit doctor"):
        profile = DoctorProfile.objects.select_for_update().get(pk=doctor_id)
        for attr, value in fields.items():
            if attr == "department_id":
                profile.department = _active_department(value)
            elif attr == "consultation_service_id":
                profile.consultation_service = _consultation_service(value)
            else:
                setattr(profile, attr, _clean(value))
        profile.save()
    return get_doctor(doctor_id)


def set_doctor_schedule(
    actor: User, doctor_id: int, sessions: Iterable[dict[str, Any]]
) -> DoctorProfile:
    """Replace a doctor's weekly clinic hours (validated by ``domain.schedule``).

    Each session is ``{weekday, start_time, end_time, slot_minutes, room_id}``.

    Raises:
        DomainError: ``SCHEDULE_*`` (see ``domain.schedule``), ``ROOM_INACTIVE``.
    """
    from apps.visits import services as visit_services

    items = list(sessions)
    room_ids = {s["room_id"] for s in items if s.get("room_id") is not None}
    rooms = {r.pk: r for r in Room.objects.filter(pk__in=room_ids)}
    for room_id in sorted(room_ids):
        room = rooms.get(room_id)
        if room is None:
            raise Room.DoesNotExist(f"Room {room_id}")
        if not room.active:
            raise DomainError("ROOM_INACTIVE", "The room is inactive", room=room.code)
    visit_services.replace_weekly_schedule(
        DoctorProfile.objects.get(pk=doctor_id),
        [
            visit_services.SessionInput(
                weekday=s["weekday"],
                start=s["start_time"],
                end=s["end_time"],
                slot_minutes=s.get("slot_minutes", 15),
                room=rooms.get(s["room_id"]) if s.get("room_id") is not None else None,
            )
            for s in items
        ],
        actor=actor,
    )
    return get_doctor(doctor_id)


# --- Reason codes (FEATURES 13.5) ---------------------------------------------------------


def list_reason_codes(
    *, category: str | None = None, active: bool | None = None
) -> QuerySet[ReasonCode]:
    qs = ReasonCode.objects.all()
    if category:
        qs = qs.filter(category=category)
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("category", "sort_order", "code")


def create_reason_code(
    actor: User,
    *,
    category: str,
    code: str,
    label_ar: str,
    label_en: str,
    requires_note: bool = False,
    sort_order: int = 0,
) -> ReasonCode:
    """Raises ``INVALID_CODE``, ``REASON_CATEGORY_UNKNOWN``, ``REASON_CODE_TAKEN``."""
    value = _check_code(code, pattern=_REASON_CODE_RE)
    if category not in ReasonCategory.values:
        raise DomainError("REASON_CATEGORY_UNKNOWN", "Unknown reason category", category=category)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create reason code"):
        if ReasonCode.objects.filter(category=category, code=value).exists():
            raise DomainError("REASON_CODE_TAKEN", "This code exists in the category", value=value)
        return ReasonCode.objects.create(
            category=category,
            code=value,
            label_ar=label_ar.strip(),
            label_en=label_en.strip(),
            requires_note=requires_note,
            sort_order=sort_order,
        )


def update_reason_code(actor: User, reason_id: int, **fields: Any) -> ReasonCode:
    """Edit labels, the note flag, order or active flag (code and category never change).

    Raises:
        DomainError: ``REASON_CATEGORY_EMPTY`` when the last active code of a category would
            be switched off (that action could then never be documented, invariant 4).
    """
    _check_fields(
        fields, {"label_ar", "label_en", "requires_note", "active", "sort_order"}, "reason"
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit reason code"):
        reason = ReasonCode.objects.select_for_update().get(pk=reason_id)
        was_active = reason.active
        for attr, value in fields.items():
            setattr(reason, attr, _clean(value))
        if was_active and not reason.active:
            others = list(
                ReasonCode.objects.select_for_update()
                .filter(category=reason.category, active=True)
                .exclude(pk=reason.pk)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            if not others:
                raise DomainError(
                    "REASON_CATEGORY_EMPTY",
                    "Each reason list needs at least one active reason",
                    category=reason.category,
                )
        reason.save()
    return reason


# --- Numbering (FEATURES 13.6) ------------------------------------------------------------


def sequences(year: int | None = None) -> dict[str, Any]:
    """Document counters of ``year`` (default this year): last number and the next one."""
    this_year = timezone.localdate().year
    chosen = year or this_year
    rows = dict(Sequence.objects.filter(year=chosen).values_list("code", "last_value"))
    codes = list(DOCUMENT_SEQUENCES) + sorted(set(rows) - set(DOCUMENT_SEQUENCES))
    years = sorted({*Sequence.objects.values_list("year", flat=True), this_year}, reverse=True)
    items = []
    for code in codes:
        last = rows.get(code, 0)
        items.append(
            {
                "code": code,
                "last_value": last,
                "last_number": format_document_number(code, chosen, last) if last else None,
                "next_number": format_document_number(code, chosen, last + 1),
            }
        )
    return {"year": chosen, "years": years, "items": items}


# --- Print templates (FEATURES 0.10, 13.7) ------------------------------------------------


def print_templates() -> list[dict[str, Any]]:
    """Every document and paper size, saved or not (unsaved ones show the defaults)."""
    saved = {(t.document, t.paper): t for t in PrintTemplate.objects.all()}
    out = []
    for document in PrintDocument.values:
        for paper in PaperSize.values:
            row = saved.get((document, paper))
            out.append(
                {
                    "document": document,
                    "paper": paper,
                    "show_logo": row.show_logo if row else True,
                    "header_ar": row.header_ar if row else "",
                    "header_en": row.header_en if row else "",
                    "footer_ar": row.footer_ar if row else "",
                    "footer_en": row.footer_en if row else "",
                    "active": row.active if row else True,
                    "saved": row is not None,
                    "updated_at": row.updated_at if row else None,
                }
            )
    return out


def save_print_template(actor: User, document: str, paper: str, **fields: Any) -> dict[str, Any]:
    """Save the header, footer and logo switch of one document on one paper size."""
    if document not in PrintDocument.values or paper not in PaperSize.values:
        raise PrintTemplate.DoesNotExist(f"{document}/{paper}")
    _check_fields(
        fields,
        {"show_logo", "header_ar", "header_en", "footer_ar", "footer_en", "active"},
        "print template",
    )
    clean = {k: _clean(v) for k, v in fields.items()}
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="print template"):
        PrintTemplate.objects.update_or_create(document=document, paper=paper, defaults=clean)
    return next(t for t in print_templates() if (t["document"], t["paper"]) == (document, paper))
