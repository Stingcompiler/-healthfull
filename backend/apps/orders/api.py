"""``/api/orders``: what a doctor orders and how far each order has come (FEATURES 3.5, 3.7,
4.1, 4.2).

The orderable catalog (no prices), prescription frequencies and the quantity a prescription
orders, a visit's orders in the doctor's view (requested, paid, in progress, done, cancelled,
with the approved result inline), placing orders (refused with 409 ``ALLERGY_CONFLICT``
unless an override reason is given) and withdrawing an order that has not reached the
cashier. Perform-first authorizations (FEATURES 4.4) are mounted at ``/perform-first`` from
``apps.orders.perform_first_api``. Routers stay thin: business rules live in ``domain``,
``apps.orders.services`` and ``apps.clinical.services``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status

from api.errors import PermissionRequired
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.clinical import services as clinical
from apps.core.models import User
from apps.orders import schemas as s
from apps.orders import services
from apps.orders.models import ServiceLine
from apps.orders.perform_first_api import perform_first_router
from apps.orders.procedures_api import procedures_router
from apps.visits.models import Visit

orders_router = Router(tags=["orders"])
add_ping(orders_router, "orders")

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("orders.view")
    return user


def _item(it: s.OrderItemIn) -> dict[str, Any]:
    return {
        "service": it.service_id,
        "quantity": it.quantity,
        "note": it.note,
        "pre_approval_ref": it.pre_approval_ref,
        **({"prescription": it.prescription.dict()} if it.prescription else {}),
    }


@orders_router.get(
    "/catalog",
    response={200: list[s.OrderableServiceOut], **_READ},
    operation_id="orders_list_catalog",
    summary="Services a doctor may order (lab, procedure, drug, consumable), without prices",
    description="Search by code prefix or words of the Arabic or English name.",
)
@require_perm("orders.create")
def list_catalog(request: HttpRequest, params: Query[s.CatalogParams]) -> Any:
    rows = services.orderable_services(
        params.q, kinds=[params.kind] if params.kind else None, limit=params.limit
    )
    return [s.orderable_out(svc) for svc in rows]


@orders_router.get(
    "/frequencies",
    response={200: list[s.FrequencyOut], **_READ},
    operation_id="orders_list_frequencies",
    summary="Prescription frequency codes and their doses per day",
)
@require_perm("orders.create")
def list_frequencies(request: HttpRequest) -> Any:
    return [
        {"code": f.code, "per_day": None if f.per_day is None else str(f.per_day)}
        for f in clinical.frequencies()
    ]


@orders_router.post(
    "/prescription-preview",
    response={200: s.PrescriptionPreviewOut, **_WRITE},
    operation_id="orders_preview_prescription",
    summary="The quantity a prescription would order: ceil(dose x doses per day x days)",
    description=(
        "quantity is null when it cannot be counted (as needed, no dose quantity, no "
        "duration). 409 UNKNOWN_FREQUENCY, FREQUENCY_MISMATCH, INVALID_PRESCRIPTION."
    ),
)
@require_perm("orders.create")
def preview_prescription(request: HttpRequest, payload: s.PrescriptionPreviewIn) -> Any:
    rx = clinical.preview_prescription(
        dose_quantity=payload.dose_quantity,
        frequency_code=payload.frequency_code,
        duration_days=payload.duration_days,
        as_needed=payload.as_needed,
    )
    return {
        "frequency_code": rx.frequency_code,
        "frequency_per_day": None if rx.frequency_per_day is None else str(rx.frequency_per_day),
        "quantity": rx.quantity,
    }


@orders_router.get(
    "/visits/{visit_id}/lines",
    response={200: list[s.DoctorLineOut], **_READ},
    operation_id="orders_list_visit_lines",
    summary="A visit's orders in the doctor's view: status per line, approved results inline",
    description=(
        "Clinical content (prescriptions, approved results, allergy override reasons): "
        "restricted to clinical.view holders like the rest of the clinical record."
    ),
)
@require_perm("clinical.view")
def list_visit_lines(request: HttpRequest, visit_id: int) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    return [s.line_out(d) for d in services.doctor_lines(visit)]


@orders_router.post(
    "/visits/{visit_id}/lines",
    response={201: list[s.DoctorLineOut], **_WRITE},
    operation_id="orders_create_lines",
    summary="Order lab tests, procedures and drugs on a visit",
    description=(
        "A drug with dose quantity, frequency and duration gets its quantity computed; an "
        "as-needed one needs a quantity. A drug matching an active allergy is refused with "
        "409 ALLERGY_CONFLICT (details.alerts: service_id, allergy_id, match, severity, "
        "allergen, allergen_ar) unless allergy_override_reason is given; the override is "
        "stored with who and when. Also 409 VISIT_NOT_OPEN, SERVICE_INACTIVE, "
        "QUANTITY_REQUIRED, PRESCRIPTION_NOT_DRUG, UNKNOWN_FREQUENCY, FREQUENCY_MISMATCH, "
        "INVALID_PRESCRIPTION."
    ),
)
@require_perm("orders.create")
def create_lines(request: HttpRequest, visit_id: int, payload: s.OrderIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    views = clinical.place_orders(
        visit,
        [_item(it) for it in payload.items],
        actor=_actor(request),
        allergy_override_reason=payload.allergy_override_reason,
    )
    return Status(201, [s.line_out(d) for d in views])


@orders_router.post(
    "/visits/{visit_id}/estimate",
    response={200: s.EstimateOut, **_WRITE},
    operation_id="orders_estimate_cost",
    summary="Estimated patient share of a draft order at today's prices (center option)",
    description=(
        "FEATURES 3.8: the only doctor-facing money. 409 ESTIMATED_COST_DISABLED unless the "
        "center turns it on; 403 without clinical.view_estimated_cost. Also 409 "
        "PRICE_NOT_FOUND, NO_EFFECTIVE_PRICE_LIST and the prescription errors of ordering."
    ),
)
@require_perm("orders.create")
def estimate_cost(request: HttpRequest, visit_id: int, payload: s.EstimateIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    estimate = clinical.estimate_order(
        visit, [_item(it) for it in payload.items], actor=_actor(request)
    )
    return {
        "lines": [
            {
                "service_id": ln.service_id,
                "quantity": ln.quantity,
                "patient_share": str(ln.patient_share),
            }
            for ln in estimate.lines
        ],
        "total": str(estimate.total),
    }


@orders_router.get(
    "/withdraw-reasons",
    response={200: list[s.WithdrawReasonOut], **_READ},
    operation_id="orders_list_withdraw_reasons",
    summary="Reasons a doctor chooses from to withdraw an order",
)
@require_perm("orders.cancel_line")
def list_withdraw_reasons(request: HttpRequest) -> Any:
    return services.withdraw_reasons()


@orders_router.post(
    "/lines/{line_id}/withdraw",
    response={200: s.DoctorLineOut, **_WRITE},
    operation_id="orders_withdraw_line",
    summary="Withdraw an order that has not reached the cashier, with a reason",
    description=(
        "A billed order is cancelled by a credit note at billing (409 CREDIT_NOTE_REQUIRED); "
        "one already started or partly given belongs to its work list (409 LINE_IN_PROGRESS). "
        "The answer is the doctor's clinical line view, so the caller also needs clinical.view "
        "(403 otherwise). Also 409 LINE_NOT_CLINICAL, LINE_ALREADY_CANCELLED, "
        "LINE_ALREADY_PERFORMED, REASON_UNKNOWN, REASON_NOTE_REQUIRED."
    ),
)
@require_perm("orders.cancel_line")
def withdraw_line(request: HttpRequest, line_id: int, payload: s.WithdrawIn) -> Any:
    line = get_object_or_404(ServiceLine, pk=line_id)
    view = services.withdraw_order(
        line, reason=payload.reason_code, note=payload.note, actor=_actor(request)
    )
    return s.line_out(view)


# Perform-first authorizations (FEATURES 4.4), owned by the cashier module.
orders_router.add_router("/perform-first", perform_first_router)

# The procedure work list and one-tap done (FEATURES 10.1, 10.2), owned by the nursing module.
orders_router.add_router("/procedures", procedures_router)
