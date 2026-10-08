"""``/api/catalog``: services, price lists and versions, payers, coverage rules and exclusions.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.catalog.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

catalog_router = Router(tags=["catalog"])
add_ping(catalog_router, "catalog")
