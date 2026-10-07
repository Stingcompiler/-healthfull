"""``/api/reports``: dashboard and operational, financial, stock and lab reports.

Phase 1 holds only the ``ping`` operation; feature endpoints arrive with their phase.
Routers stay thin: business rules live in ``domain`` and ``apps.reports.services``.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

reports_router = Router(tags=["reports"])
add_ping(reports_router, "reports")
