"""``/api/payments``: payments, transfer verification, refunds, shifts, handovers and banks.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.payments.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

payments_router = Router(tags=["payments"])
add_ping(payments_router, "payments")
