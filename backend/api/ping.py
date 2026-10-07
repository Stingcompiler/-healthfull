"""``GET /api/<module>/ping``: an authenticated no-op that proves a module router is mounted.

Every module router from ARCHITECTURE 4.11 carries one from Phase 1 on, before it has any
feature endpoints, so routing, session auth and the OpenAPI contract are exercised per module.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from api.schemas import ErrorOut, PingOut


def add_ping(router: Router, module: str) -> None:
    """Register ``GET /ping`` (operation id ``<module>_get_ping``) on ``router``.

    It uses the API-wide default auth (staff session): 401 ``NOT_AUTHENTICATED`` without a
    session, 403 ``PASSWORD_CHANGE_REQUIRED`` while a password change is pending.
    """

    @router.get(
        "/ping",
        response={200: PingOut, 401: ErrorOut, 403: ErrorOut},
        operation_id=f"{module}_get_ping",
        summary=f"Check that the /api/{module} router is reachable",
    )
    def ping(request: HttpRequest) -> dict[str, str]:
        return {"module": module}
