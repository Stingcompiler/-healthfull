"""``/api/patients``: patient registration, search, coverage, merge and balance.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.patients.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

patients_router = Router(tags=["patients"])
add_ping(patients_router, "patients")
