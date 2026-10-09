"""``/api/orders/procedures``: the procedure work list and one-tap done (FEATURES 10.1, 10.2).

Mounted on the orders router. Every operation needs ``orders.perform_procedure`` (nurses,
doctors). The list holds only paid or authorized open procedure lines (invariant 1); the
patient's active allergies come with each line because the nurse is about to inject or
dress. No prices.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, Query, Router, Schema

from api.errors import PermissionRequired
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.core.models import User
from apps.orders import procedures
from apps.orders.models import ServiceLine
from apps.patients.schemas import PatientBriefOut

procedures_router = Router()  # tagged "orders" by the parent router

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}

SeverityCode = Literal["mild", "moderate", "severe", "life_threatening"]


class ProcedureRefOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class ProcedurePersonOut(Schema):
    id: int
    name_ar: str
    name_en: str


class ProcedureAllergyOut(Schema):
    id: int
    label_ar: str
    label_en: str
    severity: SeverityCode


class ProcedureLineOut(Schema):
    id: int
    service: ProcedureRefOut
    quantity: int
    note: str = Field(..., description="The doctor's order note")
    department: ProcedureRefOut | None
    patient: PatientBriefOut
    allergies: list[ProcedureAllergyOut]
    allergies_recorded: bool = Field(..., description="false: the registry was never filled in")
    visit_id: int
    visit_number: str
    ordered_at: datetime
    ordered_by: ProcedurePersonOut | None
    authorized: bool = Field(
        ..., description="Performed under a perform-first authorization (not yet paid)"
    )
    performed: bool
    performed_at: datetime | None
    performed_by: ProcedurePersonOut | None
    performed_note: str


class ProcedureListParams(Schema):
    department_id: int | None = None
    q: str | None = Field(None, max_length=100)


class ProcedureDoneIn(Schema):
    note: str = Field("", max_length=500)


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("orders.perform_procedure")
    return user


@procedures_router.get(
    "",
    response={200: list[ProcedureLineOut], **_READ},
    operation_id="orders_list_procedure_worklist",
    summary="Paid or authorized procedures waiting to be done, oldest order first",
)
@require_perm("orders.perform_procedure")
def list_worklist(request: HttpRequest, params: Query[ProcedureListParams]) -> Any:
    return procedures.worklist(department=params.department_id, q=params.q)


@procedures_router.get(
    "/done",
    response={200: list[ProcedureLineOut], **_READ},
    operation_id="orders_list_procedures_done",
    summary="Procedures done today, newest first",
)
@require_perm("orders.perform_procedure")
def list_done(request: HttpRequest) -> Any:
    return procedures.done_today()


@procedures_router.post(
    "/{line_id}/done",
    response={200: ProcedureLineOut, **_WRITE},
    operation_id="orders_perform_procedure",
    summary="Mark a procedure done: records who and when, with an optional note",
    description=(
        "409 LINE_NOT_ELIGIBLE (neither paid nor authorized), LINE_ALREADY_PERFORMED, "
        "LINE_CANCELLED, LINE_NOT_PROCEDURE."
    ),
)
@require_perm("orders.perform_procedure")
def mark_done(request: HttpRequest, line_id: int, payload: ProcedureDoneIn) -> Any:
    line = get_object_or_404(ServiceLine, pk=line_id)
    return procedures.mark_done(line, actor=_actor(request), note=payload.note)
