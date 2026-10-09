"""``/api/ops``: health, the system status page, manual backup requests, update history and the
full data export (FEATURES 0.8, 13.8, 13.9, 13.10, 14.1).

Routers stay thin: each operation checks one permission and calls one function of
``apps.ops.services`` or ``apps.ops.export``. Nothing here runs a shell command: a backup is
a recorded request the backup service picks up (ADR 0014).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest, StreamingHttpResponse
from ninja import Query, Router, Status

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.core.models import User
from apps.ops import export, services
from apps.ops.models import BackupRequest
from apps.ops.schemas import (
    BackupRequestIn,
    BackupRequestOut,
    HealthOut,
    SystemStatusOut,
    UpdateHistoryOut,
    UpdateParams,
)

ops_router = Router(tags=["ops"])

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("ops.view_status")
    return user


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


@ops_router.get(
    "/status",
    response={200: SystemStatusOut, **_READ},
    operation_id="ops_get_status",
    summary="System status: database, disk, version, migrations, backups, restore tests",
)
@require_perm("ops.view_status")
def get_status(request: HttpRequest) -> dict[str, Any]:
    return services.system_status()


@ops_router.post(
    "/backups/request",
    response={201: BackupRequestOut, **_WRITE},
    operation_id="ops_request_backup",
    summary="Ask the backup service for a backup now (it picks the request up within minutes)",
    description="409 BACKUP_REQUEST_OPEN (one is already waiting or running).",
)
@require_perm("ops.trigger_backup")
def request_backup(request: HttpRequest, payload: BackupRequestIn) -> Status[BackupRequest]:
    return Status(201, services.request_backup(actor=_actor(request), note=payload.note))


@ops_router.get(
    "/updates",
    response={200: UpdateHistoryOut, **_READ},
    operation_id="ops_list_updates",
    summary="The running version and the recorded updates with their release notes",
)
@require_perm("ops.view_status")
def list_updates(request: HttpRequest, params: Query[UpdateParams]) -> dict[str, Any]:
    page = paginate(services.update_runs(), params.page, params.page_size)
    return {"current_version": settings.APP_VERSION, "log": services.update_log(), **page}


@ops_router.post(
    "/export",
    response={200: None, **_WRITE},
    operation_id="ops_export_data",
    summary="Full data export: a zip of CSV files (patients, visits, invoices, payments, ...)",
    description=(
        "The response is the zip itself (attachment), streamed. Every export is recorded in "
        "the audit trail (who, when, which tables, row counts)."
    ),
)
@require_perm("ops.export_data")
def export_data(request: HttpRequest) -> StreamingHttpResponse:
    record = export.begin_export(actor=_actor(request))
    response = StreamingHttpResponse(export.stream_export(record), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{export.export_filename()}"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
