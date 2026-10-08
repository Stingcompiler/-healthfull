"""Schemas of ``/api/orders`` for the ordering doctor (ARCHITECTURE 4.11 naming).

Doctor-facing: no prices, no billing amounts, no invoice numbers (FEATURES 3.7, 3.8). A
line's progress is the doctor's status (requested, paid, in progress, done, cancelled).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from ninja import Field, Schema

from apps.catalog.models import Service
from apps.clinical.schemas import ClinicUserRefOut, ResultOut, result_out, user_ref
from apps.orders.services import DoctorLine

OrderableKind = Literal["lab", "procedure", "drug", "consumable"]
DoctorStatusCode = Literal["requested", "paid", "in_progress", "done", "cancelled"]
RouteCode = Literal[
    "oral",
    "iv",
    "im",
    "sc",
    "topical",
    "inhaled",
    "rectal",
    "ophthalmic",
    "otic",
    "nasal",
    "other",
]


def _dec(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value).normalize(), "f")


# --- catalog --------------------------------------------------------------------------------


class CatalogParams(Schema):
    q: str = Field("", max_length=100)
    kind: OrderableKind | None = None
    limit: int = Field(30, ge=1, le=100)


class DrugClassRefOut(Schema):
    code: str
    name_ar: str
    name_en: str


class DrugInfoOut(Schema):
    generic_name: str
    brand_name: str
    form: str
    strength: str
    base_unit_code: str
    base_unit_name_ar: str
    base_unit_name_en: str
    classes: list[DrugClassRefOut]


class OrderableServiceOut(Schema):
    """A catalog service a doctor may order. Never a price (FEATURES 3.8)."""

    id: int
    code: str
    kind: OrderableKind
    name_ar: str
    name_en: str
    department_code: str | None
    drug: DrugInfoOut | None


def orderable_out(service: Service) -> dict[str, Any]:
    item = getattr(service, "stock_item", None) if service.kind == "drug" else None
    return {
        "id": service.pk,
        "code": service.code,
        "kind": service.kind,
        "name_ar": service.name_ar,
        "name_en": service.name_en,
        "department_code": service.department.code if service.department else None,
        "drug": None
        if item is None
        else {
            "generic_name": item.generic_name,
            "brand_name": item.brand_name,
            "form": item.form,
            "strength": item.strength,
            "base_unit_code": item.base_unit_code,
            "base_unit_name_ar": item.base_unit_name_ar,
            "base_unit_name_en": item.base_unit_name_en,
            "classes": [
                {"code": c.code, "name_ar": c.name_ar, "name_en": c.name_en}
                for c in item.drug_classes.all()
            ],
        },
    }


# --- prescriptions --------------------------------------------------------------------------


class FrequencyOut(Schema):
    code: str
    per_day: str | None


class PrescriptionPreviewIn(Schema):
    dose_quantity: Decimal | None = Field(None, gt=0, max_digits=10, decimal_places=3)
    frequency_code: str = Field("", max_length=20)
    duration_days: int | None = Field(None, ge=1, le=365)
    as_needed: bool = False


class PrescriptionPreviewOut(Schema):
    frequency_code: str
    frequency_per_day: str | None
    quantity: int | None


class PrescriptionIn(Schema):
    dose: str = Field("", max_length=60)
    dose_quantity: Decimal | None = Field(None, gt=0, max_digits=10, decimal_places=3)
    route: RouteCode = "oral"
    frequency_code: str = Field("", max_length=20)
    duration_days: int | None = Field(None, ge=1, le=365)
    as_needed: bool = False
    instructions: str = Field("", max_length=500)


class PrescriptionOut(Schema):
    dose: str
    dose_quantity: str | None
    route: RouteCode
    frequency_code: str
    frequency_per_day: str | None
    duration_days: int | None
    as_needed: bool
    instructions: str


# --- orders ---------------------------------------------------------------------------------


class OrderItemIn(Schema):
    service_id: int
    quantity: int | None = Field(None, ge=1, le=10000)
    note: str = Field("", max_length=500)
    pre_approval_ref: str = Field("", max_length=100)
    prescription: PrescriptionIn | None = None


class OrderIn(Schema):
    items: list[OrderItemIn] = Field(..., min_length=1, max_length=50)
    allergy_override_reason: str = Field(
        "",
        max_length=1000,
        description="Why a drug is ordered despite a matching allergy (409 ALLERGY_CONFLICT "
        "without it; details.alerts lists the matches).",
    )


class EstimateIn(Schema):
    items: list[OrderItemIn] = Field(..., min_length=1, max_length=50)


class EstimatedLineOut(Schema):
    service_id: int
    quantity: int
    patient_share: str


class EstimateOut(Schema):
    """The patient's estimated share of a draft order (FEATURES 3.8): shown to a doctor only
    when the center turns it on and the doctor holds clinical.view_estimated_cost."""

    lines: list[EstimatedLineOut]
    total: str


class AllergyOverrideOut(Schema):
    allergy_id: int
    match: str
    reason: str
    overridden_by: ClinicUserRefOut | None
    overridden_at: datetime


class CancellationOut(Schema):
    reason_code: str | None
    label_ar: str
    label_en: str
    note: str
    cancelled_at: datetime | None
    cancelled_by: ClinicUserRefOut | None


class DoctorLineOut(Schema):
    """One order of a visit as its doctor sees it (FEATURES 3.7). No prices."""

    id: int
    visit_id: int
    service_id: int
    service_code: str
    kind: OrderableKind
    name_ar: str
    name_en: str
    quantity: str
    status: DoctorStatusCode
    authorized: bool
    can_withdraw: bool
    note: str
    ordered_by: ClinicUserRefOut | None
    ordered_at: datetime
    prescription: PrescriptionOut | None
    allergy_overrides: list[AllergyOverrideOut]
    cancellation: CancellationOut | None
    result: ResultOut | None


def line_out(view: DoctorLine) -> dict[str, Any]:
    line = view.line
    rx = getattr(line, "prescription", None) if line.kind == "drug" else None
    reason = line.cancel_reason
    return {
        "id": line.pk,
        "visit_id": line.visit_id,
        "service_id": line.service_id,
        "service_code": line.service.code,
        "kind": line.kind,
        "name_ar": line.service.name_ar,
        "name_en": line.service.name_en,
        "quantity": _dec(line.quantity) or "0",
        "status": str(view.status),
        "authorized": line.authorization_id is not None
        and line.authorization is not None
        and line.authorization.revoked_at is None,
        "can_withdraw": view.can_cancel,
        "note": line.order_note,
        "ordered_by": user_ref(line.ordered_by),
        "ordered_at": line.ordered_at,
        "prescription": None
        if rx is None
        else {
            "dose": rx.dose,
            "dose_quantity": _dec(rx.dose_quantity),
            "route": rx.route,
            "frequency_code": rx.frequency_code,
            "frequency_per_day": _dec(rx.frequency_per_day),
            "duration_days": rx.duration_days,
            "as_needed": rx.as_needed,
            "instructions": rx.instructions,
        },
        "allergy_overrides": [
            {
                "allergy_id": o.allergy_id,
                "match": o.match,
                "reason": o.reason,
                "overridden_by": user_ref(o.overridden_by),
                "overridden_at": o.overridden_at,
            }
            for o in line.allergy_overrides.all()
        ],
        "cancellation": None
        if line.cancelled_at is None
        else {
            "reason_code": reason.code if reason else None,
            "label_ar": reason.label_ar if reason else "",
            "label_en": reason.label_en if reason else "",
            "note": line.cancel_note,
            "cancelled_at": line.cancelled_at,
            "cancelled_by": user_ref(line.cancelled_by),
        },
        "result": None if view.result is None else result_out(view.result),
    }


class WithdrawIn(Schema):
    reason_code: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=500)


class WithdrawReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str
    requires_note: bool
