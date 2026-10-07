"""``/api/auth``: CSRF cookie, login, logout, current user, preferences, password change."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.middleware.csrf import get_token
from ninja import Router, Status
from ninja.errors import AuthenticationError

from api.schemas import ErrorOut
from api.security import session_auth_pending_ok
from apps.core import services
from apps.core.models import User
from apps.core.schemas import ChangePasswordIn, LoginIn, MeOut, PreferencesPatch

auth_router = Router(tags=["auth"])


def _current_user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


@auth_router.get(
    "/csrf",
    auth=None,
    response={204: None},
    operation_id="auth_get_csrf",
    summary="Set the csrftoken cookie",
)
def get_csrf(request: HttpRequest) -> Status[None]:
    get_token(request)
    return Status(204, None)


@auth_router.post(
    "/login",
    auth=None,
    response={
        200: MeOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ErrorOut,
        423: ErrorOut,
        429: ErrorOut,
    },
    operation_id="auth_login",
    summary="Log in with username and password",
    description=(
        "401 INVALID_CREDENTIALS on a wrong username/password. The 5th consecutive failure "
        "for a username (existing or not) locks it for 15 minutes; while locked every "
        "attempt returns 423 ACCOUNT_LOCKED with details.locked_until and "
        "details.retry_after_seconds. Too many failures from one client address return "
        "429 RATE_LIMITED with details.retry_after_seconds. A successful login rotates the "
        "session and the csrftoken cookie."
    ),
)
def login(request: HttpRequest, payload: LoginIn) -> dict[str, Any]:
    return services.login(request, payload.username, payload.password)


@auth_router.post(
    "/logout",
    auth=None,
    response={204: None, 403: ErrorOut},
    operation_id="auth_logout",
    summary="Log out (idempotent)",
)
def logout(request: HttpRequest) -> Status[None]:
    services.logout(request)
    return Status(204, None)


@auth_router.get(
    "/me",
    auth=session_auth_pending_ok,
    response={200: MeOut, 401: ErrorOut},
    operation_id="auth_get_me",
    summary="Current user, roles, effective permissions and preferences",
)
def me(request: HttpRequest) -> dict[str, Any]:
    return services.me_payload(_current_user(request))


@auth_router.patch(
    "/me/preferences",
    auth=session_auth_pending_ok,
    response={200: MeOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut},
    operation_id="auth_update_preferences",
    summary="Update language and/or theme",
)
def update_preferences(request: HttpRequest, payload: PreferencesPatch) -> dict[str, Any]:
    return services.update_preferences(
        _current_user(request), language=payload.language, theme=payload.theme
    )


@auth_router.post(
    "/change-password",
    auth=session_auth_pending_ok,
    response={204: None, 401: ErrorOut, 403: ErrorOut, 409: ErrorOut, 422: ErrorOut, 423: ErrorOut},
    operation_id="auth_change_password",
    summary="Change own password",
    description=(
        "409 PASSWORD_INVALID with details.reason = old_password_incorrect | "
        "password_unchanged | password_rejected (then details.messages lists why). "
        "Wrong current passwords count toward the login lockout: the one that locks the "
        "account ends the session and returns 423 ACCOUNT_LOCKED, as does any attempt "
        "while the account is locked."
    ),
)
def change_password(request: HttpRequest, payload: ChangePasswordIn) -> Status[None]:
    services.change_password(
        request, _current_user(request), payload.old_password, payload.new_password
    )
    return Status(204, None)
