"""``/api/ops``: health and (later) backup/restore status."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router, Status

from apps.ops import services
from apps.ops.schemas import HealthOut

ops_router = Router(tags=["ops"])


@ops_router.get(
    "/health",
    auth=None,
    response={200: HealthOut, 503: HealthOut},
    operation_id="ops_get_health",
    summary="Liveness and database health (no authentication)",
    description="200 when everything is ok; 503 with status=degraded when the database fails.",
)
def health(request: HttpRequest) -> Status[dict[str, Any]]:
    result = services.health()
    return Status(200 if result["status"] == "ok" else 503, result)
