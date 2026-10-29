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
from apps.visits.models import Admission, AdmissionStatus, AppointmentSource, Bed
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


@fixture(
    "online_request",
    summary=(
        "An online booking request (status requested, ADR 0029 E) for a caller named "
        "`contact_name` with `doctor` (default doctor) in the first free slot from `days_ahead` "
        "days after today on (default 2, the next 14 days are tried), expiring in two hours, as "
        "the portal's system user."
    ),
    params=("doctor", "days_ahead", "contact_name"),
)
def online_request(p: Params) -> Json:
    from apps.portal.services import portal_actor

    doctor = p.doctor("doctor", default="doctor")
    if doctor is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "A doctor is required")
    ahead = p.integer("days_ahead")
    first = timezone.localdate() + timedelta(days=2 if ahead is None else ahead)
    for offset in range(14):
        day = first + timedelta(days=offset)
        slots = visits.available_slots(doctor, day)
        if slots:
            break
    else:
        raise DomainError("FIXTURE_PARAM_INVALID", "The doctor has no free slot in two weeks")
    start, _ = slots[0]
    row = visits.book_appointment(
        doctor=doctor,
        starts_at=start,
        actor=portal_actor(),
        contact_name=p.text("contact_name", "Online caller"),
        contact_phone="0912345678",
        source=AppointmentSource.PORTAL,
        expires_at=timezone.now() + timedelta(hours=2),
    )
    return {
        "id": row.pk,
        "starts_at": row.starts_at.isoformat(),
        "day": day.isoformat(),
        "doctor_id": doctor.pk,
        "doctor_name_en": doctor.user.display_name_en,
        "doctor_name_ar": doctor.user.display_name_ar,
    }
