"""e2e builders of the lab module (``manage.py e2e_fixture``, test databases only).

``lab_order``: a new adult patient with a visit, lab tests ordered by the doctor, invoiced
and (unless ``pay`` is false) paid in cash: the paid tests wait on the lab work list.

``lab_progress``: moves one lab line along the bench through the lab services, acting as
the seed lab users (``labtech`` receives and enters, ``labsup`` approves and amends):
``received``, ``entered`` (values given or normal defaults), ``approved``, ``amended``
(approved, then amended and approved again with ``amended_values``).

Both go through the services, so a refused step (an unpaid line, an incomplete result)
fails the fixture exactly as the screen would.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils import timezone

from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.services import require_permission
from apps.lab import services as lab
from apps.lab.models import ResultSet, ResultStatus
from apps.orders.models import ServiceLine
from domain.errors import DomainError

#: Normal values of the seeded tests (``apps/core/e2e/catalog.py``), by test code.
_NORMAL: dict[str, dict[str, str]] = {
    "CBC": {"WBC": "7.0", "HGB": "14.5", "PLT": "250"},
    "BFMP": {"MP": "negative"},
    "FBS": {"GLU": "90"},
    "RBS": {"GLU": "110"},
    "RFT": {"UREA": "30", "CREAT": "1.0"},
}

STAGES = ("received", "entered", "approved", "amended")


@fixture(
    "lab_order",
    summary=(
        "A new adult patient (`patient_fields` override) with a visit, `tests` (lab service "
        "codes, default LAB-CBC) ordered by `doctor`, invoiced and paid in cash unless `pay` "
        "is false. Returns patient, visit, lab_lines, invoice."
    ),
    params=("patient_fields", "tests", "pay", "doctor"),
)
def lab_order(p: Params) -> Json:
    fields: dict[str, Any] = {"sex": "male", "date_of_birth": "1985-03-01"}
    fields.update(p.mapping("patient_fields"))
    made = run_nested("patient", fields)
    opened = run_nested(
        "visit", {"patient": made["patient"]["id"], "doctor": p.text("doctor", "doctor")}
    )
    vid = opened["visit"]["id"]
    codes = p.items("tests") or ["LAB-CBC"]
    ordered = run_nested("order", {"visit": vid, "items": [{"service": c} for c in codes]})
    approved = run_nested("approve_invoice", {"visit": vid})
    invoice = approved["invoice"]
    if p.flag("pay", True):
        paid = run_nested("pay", {"visit": vid})
        invoice = paid["invoices"][0] if paid["invoices"] else invoice
    lab_ids = [ln["id"] for ln in ordered["lines"] if ln["kind"] == "lab"]
    lines = ServiceLine.objects.filter(pk__in=lab_ids).select_related("service").order_by("id")
    return {
        "patient": made["patient"],
        "visit": opened["visit"],
        "lab_lines": [
            {
                "id": ln.pk,
                "service": ln.service.code,
                "billing_status": ln.billing_status,
                "fulfilment_status": ln.fulfilment_status,
            }
            for ln in lines
        ],
        "invoice": invoice,
    }


def _values(p: Params, key: str, code: str) -> dict[str, str]:
    given = {str(k): str(v) for k, v in p.mapping(key).items()}
    if given:
        return given
    if code not in _NORMAL:
        raise DomainError("FIXTURE_PARAM_INVALID", f"{key}: no default values for {code}")
    return dict(_NORMAL[code])


@fixture(
    "lab_progress",
    summary=(
        "Move lab `line` (id) to `stage` (received, entered, approved, amended) as `labtech` "
        "and `labsup`; `values` / `amended_values` by parameter code (normal defaults)."
    ),
    params=("line", "stage", "values", "amended_values", "tech", "supervisor"),
)
def lab_progress(p: Params) -> Json:
    target = p.choice("stage", STAGES, "approved")
    line_id = p.integer("line")
    if line_id is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "line: required")
    tech = p.user("tech", "labtech")
    sup = p.user("supervisor", "labsup")
    require_permission(tech, "lab.receive_sample")
    require_permission(tech, "lab.enter_results")
    line = ServiceLine.objects.select_related("visit").get(pk=line_id)
    sample = lab.collect_and_receive(visit=line.visit, lines=[line], actor=tech)
    rs = ResultSet.objects.select_related("test").get(service_line=line)
    if target != "received":
        lab.enter_results(line, values=_values(p, "values", rs.test.code), actor=tech)
    if target in ("approved", "amended"):
        lab.approve_results(line, actor=sup)
    if target == "amended":
        lab.start_amendment(line, actor=sup, reason_code="ENTRY_ERROR", note="e2e amendment")
        amended = {str(k): str(v) for k, v in p.mapping("amended_values").items()}
        if amended:
            lab.enter_results(line, values=amended, actor=sup)
        lab.approve_results(line, actor=sup)
    versions = list(rs.versions.order_by("version_no").values("id", "version_no", "status"))
    current = next((v for v in versions if v["status"] == ResultStatus.APPROVED), None)
    return {
        "line": line_id,
        "sample": {"id": sample.pk, "accession_no": sample.accession_no},
        "stage": str(lab.line_stage(line)),
        "versions": versions,
        "current_version": current["id"] if current else None,
        "on": date.isoformat(timezone.localdate()),
    }


@fixture(
    "lab_screens",
    summary=(
        "The lab screens with data, in one run: a paid CBC entered with a critical "
        "haemoglobin (awaiting approval) and a malaria test approved then amended."
    ),
    params=(),
)
def lab_screens(p: Params) -> Json:
    order = run_nested(
        "lab_order",
        {
            "tests": ["LAB-CBC", "LAB-BFMP"],
            "patient_fields": {"full_name_en": "Amna Hassan Ali Mohamed"},
        },
    )
    cbc, bfmp = order["lab_lines"]
    entered = run_nested(
        "lab_progress",
        {
            "line": cbc["id"],
            "stage": "entered",
            "values": {"WBC": "7.2", "HGB": "5.1", "PLT": "260"},
        },
    )
    amended = run_nested(
        "lab_progress",
        {
            "line": bfmp["id"],
            "stage": "amended",
            "values": {"MP": "positive"},
            "amended_values": {"MP": "negative"},
        },
    )
    return {"entered": entered, "amended": amended}
