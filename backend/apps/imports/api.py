"""``/api/imports``: Excel imports with preview and confirm (FEATURES 1.8, 8.13, 5.2).

Patients keep their reception endpoints (``/patients``, ``/patients/template``); every kind
(patients, items with opening stock, prices) goes through ``/jobs`` and ``/templates/{kind}``,
which the administration wizard uses. Confirm, cancel and rows work for every kind.

Routers stay thin: each operation checks its permission, reads its schema and calls one
function of ``apps.imports.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Form, Query, Router, Status
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
    ImportJobRowOut,
    ImportKindCode,
    ImportRowOut,
    JobListParams,
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
    response["X-Content-Type-Options"] = "nosniff"
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
    job = services.preview_patients(
        filename=file.name or "import", content=_upload(file), actor=_actor(request)
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
    summary="Import the valid rows (and, if asked, the possible duplicates)",
    description=(
        "Every kind goes through its module's services (patients registered, items created "
        "and opening stock posted as a goods receipt, prices put into the version that has "
        "not started). 409 IMPORT_JOB_CLOSED, IMPORT_NOTHING_TO_IMPORT, and for prices the "
        "catalog's refusals (PRICE_VERSION_LOCKED, ...)."
    ),
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


# --- every kind (the administration wizard) -------------------------------------------------


def _upload(file: UploadedFile) -> bytes:
    """The upload's bytes, at most one byte past the limit (the service refuses it)."""
    return file.read(services.MAX_FILE_BYTES + 1)


@imports_router.get(
    "/templates/{kind}",
    response={200: None, **_READ, 409: ErrorOut},
    operation_id="imports_get_template",
    summary="An empty import sheet (.xlsx) of a kind with its header row",
    description="The response is the .xlsx file itself (attachment).",
)
@require_perm("imports.run")
def get_template(
    request: HttpRequest, kind: ImportKindCode, params: Query[TemplateParams]
) -> HttpResponse:
    response = HttpResponse(services.template(kind, params.language), content_type=_XLSX)
    response["Content-Disposition"] = f'attachment; filename="{kind}-{params.language}.xlsx"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@imports_router.post(
    "/jobs",
    response={201: ImportJobOut, **_WRITE},
    operation_id="imports_preview_job",
    summary="Upload a sheet of a kind: validate every row and flag duplicates (nothing saved)",
    description=(
        "Excel (.xlsx) or CSV, first sheet, header row in Arabic or English, at most 2,000 "
        "rows and 5 MB. Formulas are refused (FORMULA_NOT_ALLOWED on the row), never run. "
        "items: optional store (default store code of batch rows). prices: price_list (code) "
        "and effective_from (a date after today). 409 IMPORT_KIND_UNKNOWN, "
        "IMPORT_FILE_INVALID, IMPORT_FILE_TOO_LARGE, IMPORT_HEADERS_MISSING, IMPORT_NO_ROWS, "
        "IMPORT_TOO_MANY_ROWS, IMPORT_OPTION_REQUIRED, IMPORT_OPTION_INVALID, STORE_UNKNOWN, "
        "PRICE_LIST_UNKNOWN, PRICE_LIST_INACTIVE, PRICE_VERSION_BACKDATED."
    ),
)
@require_perm("imports.run")
def preview_job(
    request: HttpRequest,
    file: File[UploadedFile],
    kind: Form[ImportKindCode],
    store: Form[str] = "",
    price_list: Form[str] = "",
    effective_from: Form[str] = "",
) -> Status[ImportJob]:
    options = {"store": store, "price_list": price_list, "effective_from": effective_from}
    job = services.preview(
        kind,
        filename=file.name or "import",
        content=_upload(file),
        actor=_actor(request),
        options={k: v[:40] for k, v in options.items() if v},
    )
    return Status(201, job)


@imports_router.get(
    "/jobs",
    response={200: Page[ImportJobOut], **_READ},
    operation_id="imports_list_jobs",
    summary="Import jobs, newest first (optionally one kind)",
)
@require_perm("imports.run")
def list_jobs(request: HttpRequest, params: Query[JobListParams]) -> dict[str, Any]:
    return paginate(services.list_jobs(kind=params.kind), params.page, params.page_size)


@imports_router.get(
    "/jobs/{int:job_id}/rows",
    response={200: Page[ImportJobRowOut], **_READ},
    operation_id="imports_list_job_rows",
    summary="The rows of an import of any kind in sheet order (paged, filtered by status)",
)
@require_perm("imports.run")
def list_job_rows(request: HttpRequest, job_id: int, params: Query[RowParams]) -> dict[str, Any]:
    job = get_object_or_404(ImportJob, pk=job_id)
    return paginate(services.job_rows(job, status=params.status), params.page, params.page_size)
