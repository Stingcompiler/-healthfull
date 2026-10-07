"""``/api/pharmacy``: dispensing, stock, goods receipts, adjustments, counts and transfers.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.pharmacy.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

pharmacy_router = Router(tags=["pharmacy"])
add_ping(pharmacy_router, "pharmacy")
