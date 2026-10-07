"""The single NinjaAPI instance mounted at ``/api/`` (ARCHITECTURE 4.11).

Secure by default: every operation requires a session (``session_auth``) unless it opts
out with ``auth=None``, and every unsafe request must pass the CSRF check.
One router per app; routers of later phases are added here as their apps land.
"""

from __future__ import annotations

from django.conf import settings
from ninja import NinjaAPI

from api.errors import install_exception_handlers
from api.security import csrf_guard, session_auth
from apps.core.api import auth_router
from apps.ops.api import ops_router

#: Version of the HTTP contract (not the build). Bump on breaking API changes.
API_VERSION = "0.1.0"

api = NinjaAPI(
    title="Hospital System API",
    version=API_VERSION,
    description=(
        "Medical center management system. Session cookie auth; send the csrftoken cookie "
        "value in the X-CSRFToken header on unsafe methods. Errors are "
        "{code, message, details}."
    ),
    urls_namespace="api",
    auth=session_auth,
    docs_url="/docs" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_DOCS_ENABLED else None,
)
install_exception_handlers(api)
api.add_decorator(csrf_guard, mode="view")

api.add_router("/auth", auth_router)
api.add_router("/ops", ops_router)
