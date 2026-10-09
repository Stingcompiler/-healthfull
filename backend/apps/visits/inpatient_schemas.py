"""Schemas of ``/api/visits/inpatient`` (FEATURES 10.5): the bed board and admissions.

Class names start with ``Inpatient`` so they never collide with another app's OpenAPI
component. No prices: nurses and doctors read these; the nights are counts only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ninja import Field, Schema

from apps.patients.schemas import PatientBriefOut
from apps.visits.models import Admission, Bed, BedCharge, BedStay
from apps.visits.services import BedBoard, BedView

BedStatusCode = Literal["available", "occupied", "maintenance"]
AdmissionStatusCode = Literal["admitted", "discharged", "cancelled"]


class InpatientRefOut(Schema):
    """A named row (room, service, bed): code and both names."""

    id: int
    code: str
    name_ar: str
    name_en: str


class InpatientPersonOut(Schema):
    id: int
    name_ar: str
    name_en: str


class InpatientOccupantOut(Schema):
    admission_id: int
    number: str
    visit_id: int
    visit_number: str
    patient: PatientBriefOut
    admitted_at: datetime
    in_bed_since: datetime
    admitting_doctor: InpatientPersonOut
    diagnosis: str
    nights_charged: int
    nights_due: int = Field(..., description="Passed nights not charged yet (the daily run)")
    nights_at_discharge: int = Field(
        ..., description="Nights a discharge now would charge (at least one for the stay)"
    )


class InpatientBedOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    status: BedStatusCode
    service: InpatientRefOut
    occupant: InpatientOccupantOut | None


class InpatientWardOut(Schema):
    room: InpatientRefOut | None = Field(..., description="null: beds outside any ward")
    beds: list[InpatientBedOut]


class InpatientCountsOut(Schema):
    available: int
    occupied: int
    maintenance: int


class InpatientBoardOut(Schema):
    wards: list[InpatientWardOut]
    counts: InpatientCountsOut
    nights_due: int


class InpatientAdmissionOut(Schema):
    id: int
    number: str
    status: AdmissionStatusCode
    visit_id: int
    visit_number: str
    patient: PatientBriefOut
    bed: InpatientRefOut | None = Field(..., description="The current bed (last bed when out)")
    admitted_at: datetime
    admitted_by: InpatientPersonOut
    admitting_doctor: InpatientPersonOut
    diagnosis: str
    discharged_at: datetime | None
    discharged_by: InpatientPersonOut | None
    discharge_summary: str
    nights_charged: int


class InpatientAdmitIn(Schema):
    patient_id: int
    visit_id: int | None = Field(
        None, description="An open visit of the patient; null opens a new inpatient visit"
    )
    bed_id: int
    doctor_id: int
    diagnosis: str = Field("", max_length=300)


class InpatientTransferIn(Schema):
    bed_id: int


class InpatientDischargeIn(Schema):
    summary: str = Field("", max_length=2000)


class InpatientBedStatusIn(Schema):
    status: Literal["available", "maintenance"]


class InpatientChargeOut(Schema):
    charged: int = Field(..., description="Bed night lines created")
    admissions: int = Field(..., description="Admissions that got at least one line")


# --- builders -------------------------------------------------------------------------------


def _ref(row: Any) -> dict[str, Any]:
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


def _person(user: Any) -> dict[str, Any]:
    return {"id": user.pk, "name_ar": user.display_name_ar, "name_en": user.display_name_en}


def _occupant(view: BedView) -> dict[str, Any] | None:
    adm, stay = view.admission, view.stay
    if adm is None or stay is None:
        return None
    return {
        "admission_id": adm.pk,
        "number": adm.number,
        "visit_id": adm.visit_id,
        "visit_number": adm.visit.number,
        "patient": adm.patient,
        "admitted_at": adm.admitted_at,
        "in_bed_since": stay.started_at,
        "admitting_doctor": _person(adm.admitting_doctor.user),
        "diagnosis": adm.admission_diagnosis,
        "nights_charged": view.nights_charged,
        "nights_due": view.nights_due,
        "nights_at_discharge": view.nights_at_discharge,
    }


def _bed(view: BedView) -> dict[str, Any]:
    bed: Bed = view.bed
    return {
        **_ref(bed),
        "status": bed.status,
        "service": _ref(bed.bed_service),
        "occupant": _occupant(view),
    }


def board_out(board: BedBoard) -> dict[str, Any]:
    return {
        "wards": [
            {
                "room": None if w.room is None else _ref(w.room),
                "beds": [_bed(v) for v in w.beds],
            }
            for w in board.wards
        ],
        "counts": {
            "available": board.counts.get("available", 0),
            "occupied": board.counts.get("occupied", 0),
            "maintenance": board.counts.get("maintenance", 0),
        },
        "nights_due": board.nights_due,
    }


def admission_out(admission: Admission) -> dict[str, Any]:
    adm = Admission.objects.select_related(
        "visit", "patient", "admitted_by", "admitting_doctor__user", "discharged_by"
    ).get(pk=admission.pk)
    stay = (
        BedStay.objects.filter(admission=adm)
        .select_related("bed")
        .order_by("-started_at", "-id")
        .first()
    )
    return {
        "id": adm.pk,
        "number": adm.number,
        "status": adm.status,
        "visit_id": adm.visit_id,
        "visit_number": adm.visit.number,
        "patient": adm.patient,
        "bed": None if stay is None else _ref(stay.bed),
        "admitted_at": adm.admitted_at,
        "admitted_by": _person(adm.admitted_by),
        "admitting_doctor": _person(adm.admitting_doctor.user),
        "diagnosis": adm.admission_diagnosis,
        "discharged_at": adm.discharged_at,
        "discharged_by": None if adm.discharged_by is None else _person(adm.discharged_by),
        "discharge_summary": adm.discharge_summary,
        "nights_charged": BedCharge.objects.filter(admission=adm).count(),
    }


def charge_out(created: list[BedCharge]) -> dict[str, Any]:
    return {"charged": len(created), "admissions": len({c.admission_id for c in created})}
