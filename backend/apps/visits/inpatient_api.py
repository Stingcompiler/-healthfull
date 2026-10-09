"""``/api/visits/inpatient``: minimal inpatient for the nursing screens (FEATURES 10.5).

The bed board (wards, beds, occupants, nights due), admit (on an open visit or a new
inpatient visit), bed transfer, discharge, taking a free bed out of service, and the daily
bed charge run that adds each passed night as a line for the cashier to invoice. Mounted on
the visits router; each operation checks one permission and calls one function of
``apps.visits.services``. No prices.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Status

from api.errors import PermissionRequired
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.core.models import DoctorProfile, User
from apps.patients.models import Patient
from apps.visits import inpatient_schemas as s
from apps.visits import services
from apps.visits.models import Admission, Bed, Visit

inpatient_router = Router()  # tagged "visits" by the parent router

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("visits.view")
    return user


@inpatient_router.get(
    "/board",
    response={200: s.InpatientBoardOut, **_READ},
    operation_id="visits_get_bed_board",
    summary="Wards and beds with their occupants and the nights due (bed board)",
)
@require_perm("visits.view")
def get_board(request: HttpRequest) -> Any:
    return s.board_out(services.bed_board())


@inpatient_router.post(
    "/admissions",
    response={201: s.InpatientAdmissionOut, **_WRITE},
    operation_id="visits_admit_patient",
    summary="Admit a patient to a free bed, on an open visit or a new inpatient visit",
    description=(
        "409 VISIT_PATIENT_MISMATCH, VISIT_NOT_ADMITTABLE, VISIT_NOT_OPEN, ALREADY_ADMITTED, "
        "PATIENT_ALREADY_ADMITTED, BED_NOT_AVAILABLE, BED_SERVICE_INVALID, PATIENT_MERGED, "
        "PATIENT_INACTIVE, DOCTOR_INACTIVE, COVERAGE_INVALID, CARD_NUMBER_REQUIRED."
    ),
)
@require_perm("visits.admit")
def admit(request: HttpRequest, payload: s.InpatientAdmitIn) -> Any:
    admission = services.admit_patient(
        get_object_or_404(Patient, pk=payload.patient_id),
        visit=None if payload.visit_id is None else get_object_or_404(Visit, pk=payload.visit_id),
        bed=get_object_or_404(Bed, pk=payload.bed_id),
        doctor=get_object_or_404(DoctorProfile, pk=payload.doctor_id),
        actor=_actor(request),
        diagnosis=payload.diagnosis,
    )
    return Status(201, s.admission_out(admission))


@inpatient_router.get(
    "/admissions/{admission_id}",
    response={200: s.InpatientAdmissionOut, **_READ},
    operation_id="visits_get_admission",
    summary="One admission with its current bed and the nights charged",
)
@require_perm("visits.view")
def get_admission(request: HttpRequest, admission_id: int) -> Any:
    return s.admission_out(get_object_or_404(Admission, pk=admission_id))


@inpatient_router.post(
    "/admissions/{admission_id}/transfer",
    response={200: s.InpatientAdmissionOut, **_WRITE},
    operation_id="visits_transfer_bed",
    summary="Move an admitted patient to another free bed",
    description="409 NOT_ADMITTED, SAME_BED, BED_NOT_AVAILABLE, BED_SERVICE_INVALID.",
)
@require_perm("visits.manage_beds")
def transfer(request: HttpRequest, admission_id: int, payload: s.InpatientTransferIn) -> Any:
    admission = get_object_or_404(Admission, pk=admission_id)
    services.transfer_bed(
        admission, bed=get_object_or_404(Bed, pk=payload.bed_id), actor=_actor(request)
    )
    return s.admission_out(admission)


@inpatient_router.post(
    "/admissions/{admission_id}/discharge",
    response={200: s.InpatientAdmissionOut, **_WRITE},
    operation_id="visits_discharge_patient",
    summary="Discharge: charge the remaining nights, free the bed and close the visit",
    description="409 NOT_ADMITTED.",
)
@require_perm("visits.discharge")
def discharge(request: HttpRequest, admission_id: int, payload: s.InpatientDischargeIn) -> Any:
    admission = get_object_or_404(Admission, pk=admission_id)
    return s.admission_out(
        services.discharge(admission, actor=_actor(request), summary=payload.summary.strip())
    )


@inpatient_router.post(
    "/beds/{bed_id}/status",
    response={200: s.InpatientRefOut, **_WRITE},
    operation_id="visits_set_bed_status",
    summary="Take a free bed out of service or back into service",
    description="409 BED_OCCUPIED, INVALID_BED_STATUS.",
)
@require_perm("visits.manage_beds")
def set_bed_status(request: HttpRequest, bed_id: int, payload: s.InpatientBedStatusIn) -> Any:
    bed = services.set_bed_status(
        get_object_or_404(Bed, pk=bed_id), status=payload.status, actor=_actor(request)
    )
    return {"id": bed.pk, "code": bed.code, "name_ar": bed.name_ar, "name_en": bed.name_en}


@inpatient_router.post(
    "/charge-due",
    response={200: s.InpatientChargeOut, **_WRITE},
    operation_id="visits_charge_bed_nights",
    summary="Add every open admission's passed nights as bed day lines (the daily run)",
    description=(
        "Idempotent: a night is charged once. The lines are given under the admission's "
        "documented perform-first exception and wait for the cashier's invoice."
    ),
)
@require_perm("visits.manage_beds")
def charge_due(request: HttpRequest) -> Any:
    return s.charge_out(services.charge_due_bed_nights(actor=_actor(request)))
