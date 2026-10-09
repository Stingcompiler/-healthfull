"""Nursing read services (FEATURES 3.4, 10.3, 10.5): what a nurse works from.

* :func:`nursing_visits`: inpatients (admitted now, any visit date, in bed order), then the
  open visits created today in arrival order (walk-in pharmacy sales left out), each with the
  patient's active allergies, how many vitals sets the visit has and when the last was taken,
  the paid or authorized procedures waiting, the queue state and, for an inpatient, the
  admission and bed. This is the nurse's way to a visit's vitals.
* :func:`nursing_chart`: one visit's vitals and nursing notes (newest first), its procedure
  lines and its admission.

Writes go through ``apps.clinical.services`` (``record_vitals``, ``add_nursing_note``) and
``apps.orders.services`` (``perform_procedure``). Nothing here carries a price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.catalog.models import ServiceKind
from apps.clinical.models import Allergy, NursingNote, Vitals
from apps.clinical.services import active_allergies
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patient_services
from apps.patients.models import Patient
from apps.visits.models import (
    Admission,
    AdmissionStatus,
    BedStay,
    QueueEntry,
    Visit,
    VisitStatus,
    VisitType,
)

__all__ = [
    "NursingChart",
    "NursingVisitRow",
    "allergies_by_patient",
    "nursing_chart",
    "nursing_visits",
]


@dataclass(frozen=True, slots=True)
class NursingVisitRow:
    visit: Visit
    allergies: list[Allergy] = field(default_factory=list)
    vitals_count: int = 0
    last_vitals_at: datetime | None = None
    procedures_waiting: int = 0
    queue_entry: QueueEntry | None = None
    admission: Admission | None = None
    bed: BedStay | None = None


@dataclass(frozen=True, slots=True)
class NursingChart:
    visit: Visit
    allergies: list[Allergy] = field(default_factory=list)
    vitals: list[Vitals] = field(default_factory=list)
    notes: list[NursingNote] = field(default_factory=list)
    procedures: list[ServiceLine] = field(default_factory=list)
    admission: Admission | None = None
    bed: BedStay | None = None


def allergies_by_patient(patients: list[Patient]) -> dict[int, list[Allergy]]:
    """Active allergies per patient id (each person's merged files included)."""
    return {p.pk: active_allergies(p) for p in {p.pk: p for p in patients}.values()}


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone())
    return start, start + timedelta(days=1)


def _open_stays(visit_ids: list[int]) -> dict[int, BedStay]:
    return {
        st.admission.visit_id: st
        for st in BedStay.objects.filter(
            ended_at__isnull=True,
            admission__status=AdmissionStatus.ADMITTED,
            admission__visit_id__in=visit_ids,
        ).select_related("admission", "bed__room")
    }


def nursing_visits(
    *, q: str | None = None, today: date | None = None, limit: int = 200
) -> list[NursingVisitRow]:
    """Inpatients, then today's open visits (see the module docstring)."""
    start, end = _day_bounds(today or timezone.localdate())
    admitted = Admission.objects.filter(status=AdmissionStatus.ADMITTED).values("visit_id")
    visits = (
        Visit.objects.filter(
            Q(pk__in=admitted)
            | Q(
                status=VisitStatus.OPEN,
                created_at__gte=start,
                created_at__lt=end,
            )
        )
        .exclude(visit_type=VisitType.PHARMACY_SALE)
        .select_related("patient", "department", "doctor__user", "payer")
        .annotate(
            vitals_count=Count("vitals", distinct=True),
            last_vitals_at=Max("vitals__recorded_at"),
        )
    )
    if q and q.strip():
        visits = visits.filter(patient_id__in=patient_services.search(q).values("pk"))
    rows = list(visits.order_by("created_at", "id")[:limit])
    ids = [v.pk for v in rows]
    stays = _open_stays(ids)
    waiting: dict[int, int] = {}
    for visit_id in (
        orders.worklist([ServiceKind.PROCEDURE])
        .filter(visit_id__in=ids)
        .values_list("visit_id", flat=True)
    ):
        waiting[visit_id] = waiting.get(visit_id, 0) + 1
    queue: dict[int, QueueEntry] = {}
    for entry in QueueEntry.objects.filter(visit_id__in=ids).order_by("created_at", "id"):
        queue[entry.visit_id] = entry  # the latest entry of each visit
    allergies = allergies_by_patient([v.patient for v in rows])
    out = [
        NursingVisitRow(
            visit=v,
            allergies=allergies.get(v.patient_id, []),
            vitals_count=getattr(v, "vitals_count", 0),
            last_vitals_at=getattr(v, "last_vitals_at", None),
            procedures_waiting=waiting.get(v.pk, 0),
            queue_entry=queue.get(v.pk),
            admission=stays[v.pk].admission if v.pk in stays else None,
            bed=stays.get(v.pk),
        )
        for v in rows
    ]
    inpatients = sorted(
        (r for r in out if r.bed is not None),
        key=lambda r: r.bed.bed.code if r.bed is not None else "",
    )
    return inpatients + [r for r in out if r.bed is None]


def nursing_chart(visit: Visit) -> NursingChart:
    """One visit as a nurse works on it: vitals, nursing notes, procedures, admission."""
    loaded = Visit.objects.select_related("patient", "department", "doctor__user", "payer").get(
        pk=visit.pk
    )
    stay = _open_stays([loaded.pk]).get(loaded.pk)
    admission = (
        stay.admission
        if stay is not None
        else Admission.objects.filter(visit=loaded).select_related("discharged_by").first()
    )
    return NursingChart(
        visit=loaded,
        allergies=active_allergies(loaded.patient),
        vitals=list(
            Vitals.objects.filter(visit=loaded)
            .select_related("recorded_by")
            .order_by("-recorded_at", "-id")
        ),
        notes=list(
            NursingNote.objects.filter(visit=loaded)
            .select_related("author", "service_line__service")
            .order_by("-created_at", "-id")
        ),
        procedures=list(
            ServiceLine.objects.filter(visit=loaded, kind=ServiceKind.PROCEDURE)
            .select_related("service", "authorization", "performed_by", "ordered_by")
            .order_by("ordered_at", "id")
        ),
        admission=admission,
        bed=stay,
    )
