"""``/api/lab``: work list, samples, results, approval and amendments, test setup.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.lab.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

lab_router = Router(tags=["lab"])
add_ping(lab_router, "lab")
