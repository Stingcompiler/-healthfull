"""The procedure desk (FEATURES 10.1, 10.2): reads and the done mark for
``apps.orders.procedures_api``.

Lines come from ``apps.orders.services`` (``procedure_worklist``, ``procedures_done``,
``perform_procedure``); each carries the patient's active allergies from
``apps.clinical.nursing``. Returns plain dicts shaped like ``ProcedureLineOut``; no prices.
"""

from __future__ import annotations

from typing import Any

from apps.clinical.nursing import AllergyState, allergies_by_patient
from apps.clinical.schemas import allergy_chip
from apps.core.models import User
from apps.orders import services as orders
from apps.orders.models import FulfilmentStatus, ServiceLine

__all__ = ["done_today", "line_json", "mark_done", "worklist"]


def _ref(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": row.pk, "code": row.code, "name_ar": row.name_ar, "name_en": row.name_en}


def _person(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.pk, "name_ar": user.display_name_ar, "name_en": user.display_name_en}


def line_json(line: ServiceLine, allergies: AllergyState) -> dict[str, Any]:
    return {
        "id": line.pk,
        "service": _ref(line.service),
        "quantity": orders.whole_quantity(line.quantity),
        "note": line.order_note,
        "department": _ref(line.department),
        "patient": line.visit.patient,
        "allergies": [allergy_chip(a) for a in allergies.active],
        "allergies_recorded": allergies.recorded,
        "visit_id": line.visit_id,
        "visit_number": line.visit.number,
        "ordered_at": line.ordered_at,
        "ordered_by": _person(line.ordered_by),
        "authorized": line.authorization_id is not None and line.billing_status != "settled",
        "performed": line.fulfilment_status == FulfilmentStatus.PERFORMED,
        "performed_at": line.performed_at,
        "performed_by": _person(line.performed_by),
        "performed_note": line.performed_note,
    }


def _rows(lines: list[ServiceLine]) -> list[dict[str, Any]]:
    allergies = allergies_by_patient([ln.visit.patient for ln in lines])
    none = AllergyState([], False)
    return [line_json(ln, allergies.get(ln.visit.patient_id, none)) for ln in lines]


def worklist(*, department: int | None = None, q: str | None = None) -> list[dict[str, Any]]:
    return _rows(orders.procedure_worklist(department=department, q=q))


def done_today() -> list[dict[str, Any]]:
    return _rows(orders.procedures_done())


def mark_done(line: ServiceLine, *, actor: User, note: str = "") -> dict[str, Any]:
    done = orders.perform_procedure(line, actor, note=note)
    fresh = ServiceLine.objects.select_related(
        "visit__patient", "service", "department", "ordered_by", "performed_by"
    ).get(pk=done.pk)
    return _rows([fresh])[0]
