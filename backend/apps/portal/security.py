"""Portal authentication (ADR 0016): its own cookie, its own session table, never the staff
session. ``request.auth`` is a :class:`~apps.portal.services.PortalPrincipal`; staff users,
their roles and permissions play no part, and a portal cookie opens no staff endpoint."""

from __future__ import annotations

from typing import Any, cast

from django.http import HttpRequest
from ninja.security import APIKeyCookie

from apps.portal import conf, services
from apps.portal.services import PortalPrincipal


class PortalAuth(APIKeyCookie):
    param_name: str = conf.COOKIE_NAME

    def __init__(self) -> None:
        # Unsafe methods also pass the API-wide CSRF guard; this repeats it for the cookie.
        super().__init__(csrf=True)

    def authenticate(self, request: HttpRequest, key: str | None) -> Any:
        return services.authenticate(key)


portal_auth = PortalAuth()


def principal(request: HttpRequest) -> PortalPrincipal:
    """The signed-in patient of a request authenticated by :data:`portal_auth`."""
    return cast(PortalPrincipal, request.auth)  # type: ignore[attr-defined]
