"""The single NinjaAPI instance mounted at ``/api/`` (ARCHITECTURE 4.11).

Secure by default: every operation requires a session (``session_auth``) unless it opts
out with ``auth=None``, and every unsafe request must pass the CSRF check.
One router per module, mounted in the ARCHITECTURE 4.11 order; each carries an
authenticated ``GET /ping`` until its feature endpoints land.
"""

from __future__ import annotations

from django.conf import settings
from ninja import NinjaAPI

from api.errors import install_exception_handlers
from api.security import csrf_guard, session_auth
from apps.billing.api import billing_router
from apps.catalog.api import catalog_router
from apps.claims.api import claims_router
from apps.clinical.api import clinical_router
from apps.core.api import auth_router, core_router
from apps.imports.api import imports_router
from apps.lab.api import lab_router
from apps.ops.api import ops_router
from apps.orders.api import orders_router
from apps.patients.api import patients_router
from apps.payments.api import payments_router
from apps.pharmacy.api import pharmacy_router
from apps.portal.api import portal_router
from apps.reports.api import reports_router
from apps.visits.api import visits_router

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
api.add_router("/core", core_router)
api.add_router("/patients", patients_router)
api.add_router("/visits", visits_router)
api.add_router("/catalog", catalog_router)
api.add_router("/clinical", clinical_router)
api.add_router("/orders", orders_router)
api.add_router("/billing", billing_router)
api.add_router("/payments", payments_router)
api.add_router("/pharmacy", pharmacy_router)
api.add_router("/lab", lab_router)
api.add_router("/claims", claims_router)
api.add_router("/reports", reports_router)
api.add_router("/imports", imports_router)
api.add_router("/ops", ops_router)
api.add_router("/portal", portal_router)
