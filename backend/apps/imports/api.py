"""``/api/imports``: Excel import of patients with preview and confirm (FEATURES 1.8).

Routers stay thin: each operation checks its permission, reads its schema and calls one
function of ``apps.imports.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, Status
from ninja.files import UploadedFile

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.core.models import User
from apps.imports import services
from apps.imports.models import ImportJob
from apps.imports.schemas import (
    ConfirmIn,
    ImportJobOut,
    ImportRowOut,
    RowParams,
    TemplateParams,
)

imports_router = Router(tags=["imports"])
add_ping(imports_router, "imports")

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("imports.run")
    return user


@imports_router.get(
    "/patients/template",
    response={200: None, **_READ},
    operation_id="imports_get_patient_template",
    summary="An empty patient import sheet (.xlsx) with the header row",
    description="The response is the .xlsx file itself (attachment).",
)
@require_perm("imports.run")
def get_patient_template(request: HttpRequest, params: Query[TemplateParams]) -> HttpResponse:
    response = HttpResponse(services.patient_template(params.language), content_type=_XLSX)
    response["Content-Disposition"] = f'attachment; filename="patients-{params.language}.xlsx"'
    return response


@imports_router.post(
    "/patients",
    response={201: ImportJobOut, **_WRITE},
    operation_id="imports_preview_patients",
    summary="Upload a patient sheet: validate every row and flag duplicates (nothing saved)",
    description=(
        "Excel (.xlsx) or CSV, first sheet, header row in Arabic or English. 409 "
        "IMPORT_FILE_INVALID, IMPORT_FILE_TOO_LARGE, IMPORT_HEADERS_MISSING, IMPORT_NO_ROWS, "
        "IMPORT_TOO_MANY_ROWS."
    ),
)
@require_perm("imports.run")
def preview_patients(request: HttpRequest, file: File[UploadedFile]) -> Status[ImportJob]:
    content = file.read(services.MAX_FILE_BYTES + 1)
    job = services.preview_patients(
        filename=file.name or "import", content=content, actor=_actor(request)
    )
    return Status(201, job)


@imports_router.get(
    "/{int:job_id}",
    response={200: ImportJobOut, **_READ},
    operation_id="imports_get_job",
    summary="An import job with its row counts",
)
@require_perm("imports.run")
def get_job(request: HttpRequest, job_id: int) -> ImportJob:
    return get_object_or_404(ImportJob.objects.select_related("uploaded_by"), pk=job_id)


@imports_router.get(
    "/{int:job_id}/rows",
    response={200: Page[ImportRowOut], **_READ},
    operation_id="imports_list_rows",
    summary="The rows of an import in sheet order (paged, filtered by status)",
)
@require_perm("imports.run")
def list_rows(request: HttpRequest, job_id: int, params: Query[RowParams]) -> dict[str, Any]:
    job = get_object_or_404(ImportJob, pk=job_id)
    return paginate(services.job_rows(job, status=params.status), params.page, params.page_size)


@imports_router.post(
    "/{int:job_id}/confirm",
    response={200: ImportJobOut, **_WRITE},
    operation_id="imports_confirm_job",
    summary="Register the valid rows (and, if asked, the possible duplicates)",
    description="409 IMPORT_JOB_CLOSED.",
)
@require_perm("imports.run")
def confirm_job(request: HttpRequest, job_id: int, payload: ConfirmIn) -> ImportJob:
    return services.confirm_job(
        get_object_or_404(ImportJob, pk=job_id),
        actor=_actor(request),
        include_duplicates=payload.include_duplicates,
    )


@imports_router.post(
    "/{int:job_id}/cancel",
    response={200: ImportJobOut, **_WRITE},
    operation_id="imports_cancel_job",
    summary="Drop a preview without importing",
    description="409 IMPORT_JOB_CLOSED.",
)
@require_perm("imports.run")
def cancel_job(request: HttpRequest, job_id: int) -> ImportJob:
    return services.cancel_job(get_object_or_404(ImportJob, pk=job_id), actor=_actor(request))
