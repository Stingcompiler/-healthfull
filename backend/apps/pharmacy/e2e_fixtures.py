"""e2e builders of the pharmacy module (``manage.py e2e_fixture``, test databases only).

``pharmacy_dispensed``: a new cash patient whose prescription (``items``, default 10 tablets
of paracetamol) is invoiced, paid (unless ``pay`` is false, then authorized perform-first by
``admin``) and dispensed from the ``PHA`` store by ``pharmacist``: the returns screen has a
dispense to take units back from (ADR 0018). Everything goes through the services.
"""

from __future__ import annotations

from typing import Any

from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.models import User
from apps.core.services import require_permission
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.pharmacy import services as ps
from apps.pharmacy.models import DispenseLine, Store
from apps.visits.models import Visit
from domain.errors import DomainError


@fixture(
    "pharmacy_dispensed",
    summary=(
        "A new cash patient (`patient_fields`) with `items` (default DRG-PARA500 x 10) "
        "invoiced and paid (or, with `pay` false, authorized perform-first), then dispensed "
        "from PHA by `pharmacist`. Returns patient, visit, dispense and its lines."
    ),
    params=("patient_fields", "items", "pay"),
)
def pharmacy_dispensed(p: Params) -> Json:
    actor = p.actor("pharmacist")
    require_permission(actor, "pharmacy.dispense")
    made = run_nested("patient", p.mapping("patient_fields"))
    opened = run_nested("visit", {"patient": made["patient"]["id"], "coverage": "cash"})
    vid = opened["visit"]["id"]
    items: list[Any] = p.items("items") or [{"service": "DRG-PARA500", "quantity": 10}]
    ordered = run_nested("order", {"visit": vid, "items": items})
    line_ids = [ln["id"] for ln in ordered["lines"]]
    if p.flag("pay", True):
        run_nested("approve_invoice", {"visit": vid})
        run_nested("pay", {"visit": vid})
    else:
        admin = User.objects.get(username="admin")
        orders.authorize_perform_first(
            list(ServiceLine.objects.filter(pk__in=line_ids)), actor=admin, reason="EMERGENCY"
        )
    store = Store.objects.filter(code="PHA").first()
    if store is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "The seeded PHA store is missing")
    record = ps.dispense(
        visit=Visit.objects.get(pk=vid),
        store=store,
        actor=actor,
        requests=[
            ps.DispenseRequest(service_line_id=ln.pk, quantity=int(ln.quantity))
            for ln in ServiceLine.objects.filter(pk__in=line_ids).order_by("id")
        ],
    )
    return {
        "patient": made["patient"],
        "visit": opened["visit"],
        "dispense": {"id": record.pk, "number": record.number},
        "lines": [
            {"id": dl.pk, "service_line_id": dl.service_line_id, "qty_base": int(dl.qty_base)}
            for dl in DispenseLine.objects.filter(dispense=record).order_by("id")
        ],
    }
