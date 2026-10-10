"""e2e builders of the nursing module (``manage.py e2e_fixture``, test databases only).

``nursing_admission``: an admission made ``days_ago`` days earlier (through
``apps.visits.services.admit_patient`` with that admission time), so a spec can see a bed
night fall due without waiting for midnight. ``nursing_discharge_all``: discharges every open
admission, leaving the seeded beds free for the next spec (the e2e database is shared).
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.e2e.fixtures import Json, Params, fixture, patient_json
from apps.core.services import require_permission
from apps.visits import services as visits
from apps.visits.models import Admission, AdmissionStatus, Bed
from domain.errors import DomainError


@fixture(
    "nursing_admission",
    summary=(
        "Admit `patient` to bed `bed` (a seeded code such as M-02) `days_ago` days ago "
        "(default 1) under `doctor` (default doctor), on a new inpatient visit. As `nurse`."
    ),
    params=("patient", "bed", "days_ago", "doctor", "diagnosis"),
)
def nursing_admission(p: Params) -> Json:
    actor = p.actor("nurse")
    require_permission(actor, "visits.admit")
    patient = p.patient()
    bed = Bed.objects.filter(code=p.text("bed")).first()
    if bed is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "Unknown bed code", bed=p.text("bed"))
    doctor = p.doctor("doctor", default="doctor")
    if doctor is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "A doctor is required")
    days = p.integer("days_ago")
    at = timezone.now() - timedelta(days=1 if days is None else days)
    adm = visits.admit_patient(
        patient,
        bed=bed,
        doctor=doctor,
        actor=actor,
        diagnosis=p.text("diagnosis"),
        at=at,
    )
    return {
        "id": adm.pk,
        "number": adm.number,
        "visit_id": adm.visit_id,
        "bed": bed.code,
        "patient": patient_json(patient),
    }


@fixture(
    "nursing_discharge_all",
    summary="Discharge every open admission (frees the seeded beds). As `nurse`.",
    params=(),
)
def nursing_discharge_all(p: Params) -> Json:
    actor = p.actor("nurse")
    require_permission(actor, "visits.discharge")
    done = []
    for adm in Admission.objects.filter(status=AdmissionStatus.ADMITTED).order_by("pk"):
        visits.discharge(adm, actor=actor, summary="e2e clean-up")
        done.append(adm.number)
    return {"discharged": done}
