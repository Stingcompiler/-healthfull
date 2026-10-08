"""``/api/patients``: registration, search, duplicate warning, merge, coverage and balance.

FEATURES 0.9 and 1.1-1.6. Routers stay thin: each operation checks its permission, reads
its schema and calls one function of ``apps.patients.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.catalog.models import Payer
from apps.core.models import User
from apps.patients import services
from apps.patients.models import Patient, PatientCoverage
from apps.patients.schemas import (
    BalanceOut,
    CoverageIn,
    CoverageListParams,
    CoverageOut,
    CoveragePatch,
    DuplicateOut,
    DuplicateParams,
    EmergencyIn,
    MergeIn,
    MergeOut,
    MergeReasonOut,
    PatientIn,
    PatientListOut,
    PatientOut,
    PatientPatch,
    PatientProfileOut,
    PatientSearchParams,
    PayerOut,
)

patients_router = Router(tags=["patients"])
add_ping(patients_router, "patients")

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("patients.view")
    return user


def _patient(patient_id: int) -> Patient:
    return get_object_or_404(Patient, pk=patient_id)


# --- files ----------------------------------------------------------------------------------


@patients_router.get(
    "",
    response={200: Page[PatientListOut], **_READ},
    operation_id="patients_list_patients",
    summary="Search patient files by name, phone or file number (paged)",
    description=(
        "Arabic spelling variants are folded (أ/إ/آ, ة/ه, ى/ي, diacritics) and names also "
        "match by similarity. A file number matches exactly; digits match phone numbers and "
        "the end of file numbers. Without q: newest files first."
    ),
)
@require_perm("patients.view")
def list_patients(request: HttpRequest, params: Query[PatientSearchParams]) -> dict[str, Any]:
    rows = services.search(
        params.q or "",
        include_inactive=params.include_inactive,
        incomplete_only=params.incomplete,
    )
    return paginate(rows, params.page, params.page_size)


@patients_router.get(
    "/duplicates",
    response={200: list[DuplicateOut], **_READ},
    operation_id="patients_find_duplicates",
    summary="Files that may be the same person (live duplicate warning)",
)
@require_perm("patients.view")
def find_duplicates(request: HttpRequest, params: Query[DuplicateParams]) -> list[Any]:
    return services.find_duplicates(**params.dict())


@patients_router.get(
    "/payers",
    response={200: list[PayerOut], **_READ},
    operation_id="patients_list_payers",
    summary="Active payers a coverage can be recorded with",
)
@require_perm("patients.view")
def list_payers(request: HttpRequest) -> list[Any]:
    return list(services.active_payers())


@patients_router.post(
    "",
    response={201: PatientOut, **_WRITE},
    operation_id="patients_create_patient",
    summary="Register a patient file",
    description=(
        "409 DUPLICATE_PATIENT with details.candidates [{id, file_no, reasons}] when similar "
        "files exist; send confirm_not_duplicate=true to register anyway. 409 "
        "NATIONAL_ID_TAKEN, NAME_REQUIRED, INVALID_DATE_OF_BIRTH, INVALID_AGE."
    ),
)
@require_perm("patients.create")
def create_patient(request: HttpRequest, payload: PatientIn) -> Status[Patient]:
    data = payload.dict()
    confirm = data.pop("confirm_not_duplicate")
    created = services.register_patient(
        services.PatientData(**data), actor=_actor(request), confirm_not_duplicate=confirm
    )
    return Status(201, created)


@patients_router.post(
    "/emergency",
    response={201: PatientOut, **_WRITE},
    operation_id="patients_register_emergency",
    summary="Emergency registration with a name and sex only (flagged incomplete)",
)
@require_perm("patients.register_emergency")
def register_emergency(request: HttpRequest, payload: EmergencyIn) -> Status[Patient]:
    created = services.register_emergency(
        name=payload.name,
        sex=payload.sex,
        age_years=payload.age_years,
        phone=payload.phone,
        actor=_actor(request),
    )
    return Status(201, created)


@patients_router.get(
    "/{int:patient_id}",
    response={200: PatientProfileOut, **_READ},
    operation_id="patients_get_patient",
    summary="A patient file with its allergies and the file it was merged into",
)
@require_perm("patients.view")
def get_patient(request: HttpRequest, patient_id: int) -> Any:
    return services.profile(_patient(patient_id))


@patients_router.patch(
    "/{int:patient_id}",
    response={200: PatientOut, **_WRITE},
    operation_id="patients_update_patient",
    summary="Edit a patient file (completes an emergency file)",
)
@require_perm("patients.edit")
def update_patient(request: HttpRequest, patient_id: int, payload: PatientPatch) -> Patient:
    return services.update_patient(
        _patient(patient_id), actor=_actor(request), **payload.dict(exclude_unset=True)
    )


# --- merge ----------------------------------------------------------------------------------


@patients_router.post(
    "/{int:patient_id}/merge",
    response={201: MergeOut, **_WRITE},
    operation_id="patients_merge_patient",
    summary="Merge a duplicate file into this one (supervisor, with a reason)",
    description=(
        "The duplicate stays as an inactive file pointing here; nothing is deleted and money "
        "does not move. 409 REASON_UNKNOWN, REASON_REQUIRED, REASON_NOTE_REQUIRED, "
        "MERGE_SAME_FILE, PATIENT_MERGED."
    ),
)
@require_perm("patients.merge")
def merge_patient(request: HttpRequest, patient_id: int, payload: MergeIn) -> Status[Any]:
    merge = services.merge_into(
        _patient(patient_id),
        duplicate=_patient(payload.duplicate_id),
        actor=_actor(request),
        reason_code=payload.reason_code,
        note=payload.note,
    )
    return Status(201, merge)


@patients_router.get(
    "/merge-reasons",
    response={200: list[MergeReasonOut], **_READ},
    operation_id="patients_list_merge_reasons",
    summary="The reason codes a supervisor gives for merging two files",
)
@require_perm("patients.merge")
def list_merge_reasons(request: HttpRequest) -> list[Any]:
    return list(services.merge_reasons())


@patients_router.get(
    "/{int:patient_id}/merges",
    response={200: list[MergeOut], **_READ},
    operation_id="patients_list_merges",
    summary="Merges into or out of this file, newest first",
)
@require_perm("patients.view")
def list_merges(request: HttpRequest, patient_id: int) -> list[Any]:
    return services.merges(_patient(patient_id))


# --- coverage on file -----------------------------------------------------------------------


@patients_router.get(
    "/{int:patient_id}/coverages",
    response={200: list[CoverageOut], **_READ},
    operation_id="patients_list_coverages",
    summary="Coverages on file, the default first",
)
@require_perm("patients.view")
def list_coverages(
    request: HttpRequest, patient_id: int, params: Query[CoverageListParams]
) -> list[Any]:
    return services.coverages(_patient(patient_id), include_inactive=params.include_inactive)


@patients_router.post(
    "/{int:patient_id}/coverages",
    response={201: CoverageOut, **_WRITE},
    operation_id="patients_create_coverage",
    summary="Record a payer on the patient's file",
    description="409 PAYER_INACTIVE, CARD_NUMBER_REQUIRED, INVALID_DATE_RANGE, INVALID_PERCENT.",
)
@require_perm("patients.manage_coverage")
def create_coverage(
    request: HttpRequest, patient_id: int, payload: CoverageIn
) -> Status[PatientCoverage]:
    data = payload.dict()
    payer = get_object_or_404(Payer, pk=data.pop("payer_id"))
    created = services.add_coverage(
        _patient(patient_id), payer=payer, actor=_actor(request), **data
    )
    return Status(201, created)


@patients_router.patch(
    "/coverages/{int:coverage_id}",
    response={200: CoverageOut, **_WRITE},
    operation_id="patients_update_coverage",
    summary="Edit a coverage on file (card, validity, member share, default)",
)
@require_perm("patients.manage_coverage")
def update_coverage(
    request: HttpRequest, coverage_id: int, payload: CoveragePatch
) -> PatientCoverage:
    coverage = get_object_or_404(PatientCoverage, pk=coverage_id)
    return services.update_coverage(
        coverage, actor=_actor(request), **payload.dict(exclude_unset=True)
    )


@patients_router.post(
    "/coverages/{int:coverage_id}/end",
    response={200: CoverageOut, **_WRITE},
    operation_id="patients_end_coverage",
    summary="End a coverage on file (kept in history)",
)
@require_perm("patients.manage_coverage")
def end_coverage(request: HttpRequest, coverage_id: int) -> PatientCoverage:
    coverage = get_object_or_404(PatientCoverage, pk=coverage_id)
    return services.end_coverage(coverage, actor=_actor(request))


# --- balance --------------------------------------------------------------------------------


@patients_router.get(
    "/{int:patient_id}/balance",
    response={200: BalanceOut, **_READ},
    operation_id="patients_get_balance",
    summary="Patient credit, pending transfers and open invoices of the person",
)
@require_perm("patients.view_balance")
def get_balance(request: HttpRequest, patient_id: int) -> Any:
    return services.balance(_patient(patient_id))
