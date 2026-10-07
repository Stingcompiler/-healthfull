"""``/api/clinical``: notes, diagnoses, allergies, conditions, vitals, referrals, order sets.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.clinical.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

clinical_router = Router(tags=["clinical"])
add_ping(clinical_router, "clinical")
