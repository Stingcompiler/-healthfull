"""``/api/orders``: service lines, perform-first authorizations and procedures.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.orders.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

orders_router = Router(tags=["orders"])
add_ping(orders_router, "orders")
