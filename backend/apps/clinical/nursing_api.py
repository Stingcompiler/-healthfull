"""``/api/clinical/nursing``: the nurse's visits, a visit's nursing chart and nursing notes
(FEATURES 3.4, 10.3).

Mounted on the clinical router. Reading needs ``clinical.view`` (the clinical record, like
the doctor's workspace); a note needs ``clinical.write_nursing_note``. Vitals are recorded
with ``POST /api/clinical/visits/{visit_id}/vitals`` (``clinical.record_vitals``), so the
doctor's workspace shows them. No prices.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, Query, Router, Schema, Status

from api.errors import PermissionRequired
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.clinical import nursing, services
from apps.clinical.models import NursingNote
from apps.clinical.schemas import (
    AllergyChipOut,
    ClinicPatientOut,
    ClinicUserRefOut,
    VisitBriefOut,
    VitalsOut,
    allergy_chip,
    patient_brief,
    user_ref,
    visit_brief,
    vitals_out,
)
from apps.core.models import User
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.visits.models import Admission, BedStay, QueueEntry, Visit

nursing_router = Router()  # tagged "clinical" by the parent router

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}

NursingNoteKindCode = Literal["general", "procedure", "handover"]
QueueStatusCode = Literal["waiting", "called", "in_progress", "done", "no_show", "cancelled"]
LineStateCode = Literal["requested", "invoiced", "paid", "performed", "cancelled"]


class NursingRefOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class NursingQueueOut(Schema):
    status: QueueStatusCode
    token_no: int


class NursingAdmissionOut(Schema):
    id: int
    number: str
    status: Literal["admitted", "discharged", "cancelled"]
    admitted_at: datetime
    bed: NursingRefOut | None
    ward: NursingRefOut | None


class NursingVisitOut(Schema):
    visit: VisitBriefOut
    patient: ClinicPatientOut
    allergies: list[AllergyChipOut]
    allergies_recorded: bool = Field(..., description="false: the registry was never filled in")
    vitals_count: int
    last_vitals_at: datetime | None
    procedures_waiting: int = Field(..., description="Paid or authorized procedures not done")
    queue: NursingQueueOut | None
    admission: NursingAdmissionOut | None


class NursingNoteOut(Schema):
    id: int
    kind: NursingNoteKindCode
    text: str
    author: ClinicUserRefOut | None
    created_at: datetime
    service_line_id: int | None


class NursingProcedureOut(Schema):
    id: int
    service: NursingRefOut
    quantity: int
    note: str
    state: LineStateCode
    ordered_at: datetime
    performed_at: datetime | None
    performed_by: ClinicUserRefOut | None
    performed_note: str


class NursingChartOut(Schema):
    visit: VisitBriefOut
    patient: ClinicPatientOut
    allergies: list[AllergyChipOut]
    allergies_recorded: bool
    vitals: list[VitalsOut]
    notes: list[NursingNoteOut]
    procedures: list[NursingProcedureOut]
    admission: NursingAdmissionOut | None


class NursingVisitParams(Schema):
    q: str | None = Field(None, max_length=100)


class NursingNoteIn(Schema):
    text: str = Field(..., min_length=1, max_length=4000)
    kind: NursingNoteKindCode = "general"


# --- builders -------------------------------------------------------------------------------


def _ref(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


def _queue(entry: QueueEntry | None) -> dict[str, Any] | None:
    return None if entry is None else {"status": entry.status, "token_no": entry.token_no}


def _admission(admission: Admission | None, stay: BedStay | None) -> dict[str, Any] | None:
    if admission is None:
        return None
    if stay is None:
        stay = (
            BedStay.objects.filter(admission=admission)
            .select_related("bed__room")
            .order_by("-started_at", "-id")
            .first()
        )
    return {
        "id": admission.pk,
        "number": admission.number,
        "status": admission.status,
        "admitted_at": admission.admitted_at,
        "bed": None if stay is None else _ref(stay.bed),
        "ward": None if stay is None else _ref(stay.bed.room),
    }


def _row(r: nursing.NursingVisitRow) -> dict[str, Any]:
    return {
        "visit": visit_brief(r.visit),
        "patient": patient_brief(r.visit.patient),
        "allergies": [allergy_chip(a) for a in r.allergies.active],
        "allergies_recorded": r.allergies.recorded,
        "vitals_count": r.vitals_count,
        "last_vitals_at": r.last_vitals_at,
        "procedures_waiting": r.procedures_waiting,
        "queue": _queue(r.queue_entry),
        "admission": _admission(r.admission, r.bed),
    }


def _note(n: NursingNote) -> dict[str, Any]:
    return {
        "id": n.pk,
        "kind": n.kind,
        "text": n.text,
        "author": user_ref(n.author),
        "created_at": n.created_at,
        "service_line_id": n.service_line_id,
    }


def _procedure(line: ServiceLine) -> dict[str, Any]:
    return {
        "id": line.pk,
        "service": _ref(line.service),
        "quantity": orders.whole_quantity(line.quantity),
        "note": line.order_note,
        "state": str(orders.line_state(line)),
        "ordered_at": line.ordered_at,
        "performed_at": line.performed_at,
        "performed_by": user_ref(line.performed_by),
        "performed_note": line.performed_note,
    }


def _chart(chart: nursing.NursingChart) -> dict[str, Any]:
    return {
        "visit": visit_brief(chart.visit),
        "patient": patient_brief(chart.visit.patient),
        "allergies": [allergy_chip(a) for a in chart.allergies.active],
        "allergies_recorded": chart.allergies.recorded,
        "vitals": [vitals_out(v) for v in chart.vitals],
        "notes": [_note(n) for n in chart.notes],
        "procedures": [_procedure(ln) for ln in chart.procedures],
        "admission": _admission(chart.admission, chart.bed),
    }


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("clinical.view")
    return user


# --- operations -----------------------------------------------------------------------------


@nursing_router.get(
    "/visits",
    response={200: list[NursingVisitOut], **_READ},
    operation_id="clinical_list_nursing_visits",
    summary="Inpatients, then today's open visits in arrival order, for vitals and notes",
)
@require_perm("clinical.view")
def list_visits(request: HttpRequest, params: Query[NursingVisitParams]) -> Any:
    return [_row(r) for r in nursing.nursing_visits(q=params.q)]


@nursing_router.get(
    "/visits/{visit_id}",
    response={200: NursingChartOut, **_READ},
    operation_id="clinical_get_nursing_chart",
    summary="A visit's vitals, nursing notes, procedures and admission",
)
@require_perm("clinical.view")
def get_chart(request: HttpRequest, visit_id: int) -> Any:
    return _chart(nursing.nursing_chart(get_object_or_404(Visit, pk=visit_id)))


@nursing_router.post(
    "/visits/{visit_id}/notes",
    response={201: NursingNoteOut, **_WRITE},
    operation_id="clinical_create_nursing_note",
    summary="Add a nursing note to a visit",
    description="409 NOTE_EMPTY, INVALID_NOTE_KIND, VISIT_CANCELLED.",
)
@require_perm("clinical.write_nursing_note")
def create_note(request: HttpRequest, visit_id: int, payload: NursingNoteIn) -> Any:
    note = services.add_nursing_note(
        get_object_or_404(Visit, pk=visit_id),
        actor=_actor(request),
        text=payload.text,
        kind=payload.kind,
    )
    return Status(201, _note(note))
