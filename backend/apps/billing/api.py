"""``/api/billing``: invoices, discounts, credit notes and pharmacy sales.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.billing.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

billing_router = Router(tags=["billing"])
add_ping(billing_router, "billing")
