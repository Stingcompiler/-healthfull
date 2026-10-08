"""``/api/portal``: the patient portal (P2 in FEATURES, built in Phase 7).

Phase 1 holds only the ``ping`` operation, which uses the API-wide staff session auth.
ARCHITECTURE 4.11: the portal gets its own session key and router auth; when that lands,
this router's ``auth`` is replaced and the staff-auth ping goes with it.
"""

from __future__ import annotations

from ninja import Router

from api.ping import add_ping

portal_router = Router(tags=["portal"])
add_ping(portal_router, "portal")
