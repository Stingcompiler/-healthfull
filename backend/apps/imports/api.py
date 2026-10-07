"""``/api/imports``: bulk data import jobs (upload, validate, confirm).

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.imports.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

imports_router = Router(tags=["imports"])
add_ping(imports_router, "imports")
