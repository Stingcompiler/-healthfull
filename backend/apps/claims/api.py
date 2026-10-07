"""``/api/claims``: claims, payer responses, rejection handling and payer payments.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.claims.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

claims_router = Router(tags=["claims"])
add_ping(claims_router, "claims")
