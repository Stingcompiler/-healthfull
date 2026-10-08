"""Clinical services for doctors and nurses (FEATURES 3, 10.3).

* Allergy and chronic condition registry; prescribing a drug whose stock item matches an
  active allergy (the same item, one of its drug classes, or a described substance in its
  name) raises ``ALLERGY_ALERT`` with the matches until the doctor acknowledges it
  (FEATURES 3.2). Orders go through ``orders.services.create_service_lines``.
* Clinical notes are drafts until signed; a signed note never changes (corrections are a new
  note). Only the author edits a draft.
* Diagnoses with ICD-10 lookup (code prefix, or words of the English/Arabic title folded the
  same way as patient search), vitals with plausibility checks, referrals, order sets and
  favorites, nursing notes, and the patient summary a doctor sees on opening a file.

Nothing here carries prices: doctors never see billing (FEATURES 3.8).
"""

from __future__ import annotations

import importlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.catalog import services as catalog
from apps.catalog.models import Service, ServiceKind
from apps.clinical.models import (
    AllergenType,
    Allergy,
    Certainty,
    ChronicCondition,
    ClinicalNote,
    Diagnosis,
    DiagnosisKind,
    Icd10Code,
    NoteStatus,
    NursingNote,
    NursingNoteKind,
    OrderSet,
    OrderSetItem,
    RecordStatus,
    Referral,
    ReferralKind,
    ReferralStatus,
    Severity,
    Urgency,
    Vitals,
)
from apps.core.db import NormalizeText
from apps.core.models import Department, DoctorProfile, Policy, User
from apps.core.services import require_permission
from apps.orders.models import FulfilmentStatus, ServiceLine
from apps.patients import services as patient_services
from apps.patients.models import Patient
from apps.pharmacy.models import DrugClass, Item
from apps.visits.models import Visit, VisitStatus
from domain import coverage as dc
from domain.errors import DomainError
from domain.money import q

__all__ = [
    "VITAL_RANGES",
    "AllergyAlert",
    "PatientSummary",
    "add_diagnosis",
    "add_nursing_note",
    "allergy_alerts",
    "cancel_referral",
    "complete_referral",
    "create_order_set",
    "create_referral",
    "estimated_cost",
    "order_lines",
    "order_set_items",
    "order_sets_for",
    "patient_summary",
    "prescription_quantity",
    "reassign_patient",
    "record_allergy",
    "record_condition",
    "record_vitals",
    "save_note",
    "search_icd10",
    "set_allergy_status",
    "set_condition_status",
    "sign_note",
]

#: Plausible ranges (inclusive) per vital sign; the database has the same backstop.
VITAL_RANGES: dict[str, tuple[Decimal, Decimal]] = {
    "temperature_c": (Decimal(25), Decimal(45)),
    "pulse_bpm": (Decimal(0), Decimal(300)),
    "respiratory_rate": (Decimal(0), Decimal(120)),
    "bp_systolic": (Decimal(0), Decimal(350)),
    "bp_diastolic": (Decimal(0), Decimal(250)),
    "spo2_percent": (Decimal(0), Decimal(100)),
    "weight_kg": (Decimal("0.01"), Decimal(500)),
    "height_cm": (Decimal("0.1"), Decimal(272)),
    "blood_glucose_mg_dl": (Decimal(0), Decimal(32767)),
    "pain_score": (Decimal(0), Decimal(10)),
}
_CODE_RE = re.compile(r"^[A-Za-z]\d{1,2}(\.?\d{0,2})?$")


def _orders() -> ModuleType:
    return importlib.import_module("apps.orders.services")


def _open_visit(visit: Visit) -> Visit:
    if visit.status != VisitStatus.OPEN:
        raise DomainError("VISIT_NOT_OPEN", "The visit is not open")
    return visit


def _choice(value: str, choices: type[Any], code: str) -> str:
    if value not in choices.values:
        raise DomainError(code, "Unknown value", value=value)
    return value


# --- allergies and prescribing alerts -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AllergyAlert:
    """An active allergy that matches a drug being prescribed."""

    service_id: int
    allergy_id: int
    match: str  # "item", "drug_class" or "substance"
    severity: str
    allergen: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "allergy_id": self.allergy_id,
            "match": self.match,
            "severity": self.severity,
            "allergen": self.allergen,
        }


def record_allergy(
    patient: Patient,
    *,
    actor: User,
    allergen_type: str,
    drug_class: DrugClass | None = None,
    item: Item | None = None,
    substance: str = "",
    reaction: str = "",
    severity: str = Severity.MODERATE,
    note: str = "",
) -> Allergy:
    """Add an allergy to the registry (FEATURES 3.2)."""
    _choice(allergen_type, AllergenType, "INVALID_ALLERGEN_TYPE")
    _choice(severity, Severity, "INVALID_SEVERITY")
    if allergen_type == AllergenType.DRUG_CLASS and drug_class is None:
        raise DomainError("DRUG_CLASS_REQUIRED", "A drug class allergy names the class")
    if drug_class is None and item is None and not substance.strip():
        raise DomainError("ALLERGEN_REQUIRED", "Name the drug, class or substance")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="record allergy"):
        return Allergy.objects.create(
            patient=patient_services.resolve(patient),
            allergen_type=allergen_type,
            drug_class=drug_class,
            item=item,
            substance=substance.strip()[:200],
            reaction=reaction.strip()[:300],
            severity=severity,
            note=note,
            recorded_by=actor,
        )


def set_allergy_status(allergy: Allergy, *, status: str, actor: User, note: str = "") -> Allergy:
    """Resolve an allergy or mark it entered in error (history keeps the old row)."""
    _choice(status, RecordStatus, "INVALID_STATUS")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"allergy {status}"):
        locked = Allergy.objects.select_for_update().get(pk=allergy.pk)
        locked.status = status
        if note:
            locked.note = note
        locked.save(update_fields=["status", "note", "updated_at"])
    return locked


def _drug_items(services: Iterable[Service]) -> dict[int, Item]:
    ids = [s.pk for s in services if s.kind in (ServiceKind.DRUG, ServiceKind.CONSUMABLE)]
    return {
        it.service_id: it
        for it in Item.objects.filter(service_id__in=ids).prefetch_related("drug_classes")
    }


def allergy_alerts(patient: Patient, services: Iterable[Service]) -> list[AllergyAlert]:
    """Active allergies of the patient (and merged files) matching the drugs in ``services``.

    A match is the same stock item, one of the item's drug classes, or a described
    substance contained in the item's generic or brand name (Arabic/English folding).
    """
    svc_list = list(services)
    items = _drug_items(svc_list)
    if not items:
        return []
    allergies = list(
        Allergy.objects.filter(
            patient_id__in=patient_services.file_ids(patient_services.resolve(patient)),
            status=RecordStatus.ACTIVE,
        ).select_related("drug_class", "item")
    )
    if not allergies:
        return []
    substances = {
        a.pk: patient_services.normalize_text(a.substance) for a in allergies if a.substance
    }
    alerts: list[AllergyAlert] = []
    for service_id, item in sorted(items.items()):
        names = patient_services.normalize_text(f"{item.generic_name} {item.brand_name}")
        class_ids = {c.pk for c in item.drug_classes.all()}
        for allergy in allergies:
            match = ""
            if allergy.item_id is not None and allergy.item_id == item.pk:
                match = "item"
            elif allergy.drug_class_id is not None and allergy.drug_class_id in class_ids:
                match = "drug_class"
            elif (folded := substances.get(allergy.pk)) and folded in names:
                match = "substance"
            if match:
                allergen = (
                    allergy.substance
                    or (allergy.drug_class.name_en if allergy.drug_class else "")
                    or (allergy.item.generic_name if allergy.item else "")
                )
                alerts.append(
                    AllergyAlert(service_id, allergy.pk, match, allergy.severity, allergen)
                )
    return alerts


def prescription_quantity(
    *, dose_quantity: Decimal, frequency_per_day: Decimal, duration_days: int
) -> int:
    """Base units to dispense: dose x frequency x days, rounded up (FEATURES 3.5)."""
    if dose_quantity <= 0 or frequency_per_day <= 0 or duration_days <= 0:
        raise DomainError("INVALID_PRESCRIPTION", "Dose, frequency and duration must be positive")
    return math.ceil(dose_quantity * frequency_per_day * duration_days)


def order_lines(
    visit: Visit,
    items: Sequence[Mapping[str, Any]],
    *,
    actor: User,
    acknowledge_allergies: bool = False,
) -> Any:
    """Order services on a visit after the allergy check (FEATURES 3.2, 3.5).

    ``items`` are passed to ``orders.services.create_service_lines`` (each has a
    ``service``). With matching allergies the order is refused with ``ALLERGY_ALERT``
    (``details.alerts``) until the doctor acknowledges.
    """
    _open_visit(visit)
    if not items:
        raise DomainError("ORDER_EMPTY", "Nothing to order")
    alerts = allergy_alerts(visit.patient, [i["service"] for i in items])
    if alerts and not acknowledge_allergies:
        raise DomainError(
            "ALLERGY_ALERT",
            "The patient is allergic to a prescribed drug",
            alerts=[a.as_dict() for a in alerts],
        )
    reason = "order (allergy alert acknowledged)" if alerts else "order"
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=reason):
        return _orders().create_service_lines(visit, [dict(i) for i in items], actor)


# --- chronic conditions ---------------------------------------------------------------------


def record_condition(
    patient: Patient,
    *,
    actor: User,
    icd10: Icd10Code | None = None,
    name: str = "",
    since: Any = None,
    note: str = "",
) -> ChronicCondition:
    if icd10 is None and not name.strip():
        raise DomainError("CONDITION_NAME_REQUIRED", "Name the condition or pick an ICD-10 code")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="record condition"):
        return ChronicCondition.objects.create(
            patient=patient_services.resolve(patient),
            icd10=icd10,
            name=name.strip()[:200],
            since=since,
            note=note,
            recorded_by=actor,
        )


def set_condition_status(
    condition: ChronicCondition, *, status: str, actor: User
) -> ChronicCondition:
    _choice(status, RecordStatus, "INVALID_STATUS")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"condition {status}"):
        locked = ChronicCondition.objects.select_for_update().get(pk=condition.pk)
        locked.status = status
        locked.save(update_fields=["status", "updated_at"])
    return locked


# --- notes and diagnoses --------------------------------------------------------------------

_NOTE_FIELDS = ("complaint", "history", "examination", "assessment", "plan")


def save_note(
    visit: Visit,
    *,
    actor: User,
    note: ClinicalNote | None = None,
    **fields: str,
) -> ClinicalNote:
    """Create a draft note, or update the actor's own draft (FEATURES 3.3)."""
    unknown = sorted(set(fields) - set(_NOTE_FIELDS))
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "These fields cannot be edited", fields=unknown)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="clinical note"):
        if note is None:
            _open_visit(visit)
            return ClinicalNote.objects.create(visit=visit, author=actor, **fields)
        locked = ClinicalNote.objects.select_for_update().get(pk=note.pk)
        if locked.status == NoteStatus.SIGNED:
            raise DomainError("NOTE_SIGNED", "A signed note never changes; write a new note")
        if locked.author_id != actor.pk:
            raise DomainError("NOTE_NOT_AUTHOR", "Only the author edits a draft note")
        for name, value in fields.items():
            setattr(locked, name, value)
        locked.save(update_fields=[*fields, "updated_at"])
    return locked


def sign_note(note: ClinicalNote, *, actor: User) -> ClinicalNote:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="sign note"):
        locked = ClinicalNote.objects.select_for_update().get(pk=note.pk)
        if locked.status == NoteStatus.SIGNED:
            raise DomainError("NOTE_SIGNED", "The note is already signed")
        if locked.author_id != actor.pk:
            raise DomainError("NOTE_NOT_AUTHOR", "Only the author signs a note")
        if not any(getattr(locked, f).strip() for f in _NOTE_FIELDS):
            raise DomainError("NOTE_EMPTY", "An empty note cannot be signed")
        locked.status = NoteStatus.SIGNED
        locked.signed_at = timezone.now()
        locked.save(update_fields=["status", "signed_at", "updated_at"])
    return locked


def add_diagnosis(
    visit: Visit,
    *,
    actor: User,
    icd10_code: str | None = None,
    text: str = "",
    kind: str = DiagnosisKind.PRIMARY,
    certainty: str = Certainty.PROVISIONAL,
    note: ClinicalNote | None = None,
) -> Diagnosis:
    """Record a diagnosis: an ICD-10 code, free text, or both (FEATURES 3.3)."""
    _choice(kind, DiagnosisKind, "INVALID_DIAGNOSIS_KIND")
    _choice(certainty, Certainty, "INVALID_CERTAINTY")
    icd = None
    if icd10_code:
        icd = Icd10Code.objects.filter(code__iexact=icd10_code.strip(), active=True).first()
        if icd is None:
            raise DomainError("ICD10_UNKNOWN", "Unknown ICD-10 code", icd10=icd10_code)
    if icd is None and not text.strip():
        raise DomainError("DIAGNOSIS_REQUIRED", "Give an ICD-10 code or a diagnosis text")
    if note is not None and note.visit_id != visit.pk:
        raise DomainError("NOTE_NOT_ON_VISIT", "The note belongs to another visit")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="diagnosis"):
        return Diagnosis.objects.create(
            visit=_open_visit(visit),
            note=note,
            icd10=icd,
            text=text.strip()[:300],
            kind=kind,
            certainty=certainty,
            recorded_by=actor,
        )


def search_icd10(query: str, *, limit: int = 20) -> list[Icd10Code]:
    """ICD-10 lookup by code prefix (dot optional) or by words of the title (en/ar)."""
    term = " ".join(query.split())
    if not term:
        return []
    active = Icd10Code.objects.filter(active=True)
    compact = term.replace(" ", "").upper()
    if _CODE_RE.match(compact):
        dotted = compact if "." in compact or len(compact) <= 3 else f"{compact[:3]}.{compact[3:]}"
        return list(active.filter(code__startswith=dotted).order_by("code")[:limit])
    words = [w for w in patient_services.normalize_text(term).split(" ") if w]
    qs: QuerySet[Icd10Code] = active.annotate(
        en=NormalizeText("title_en"), ar=NormalizeText("title_ar")
    )
    for word in words:
        qs = qs.filter(Q(en__contains=word) | Q(ar__contains=word))
    return list(qs.order_by("code")[:limit])


# --- vitals ---------------------------------------------------------------------------------


def record_vitals(
    visit: Visit,
    *,
    actor: User,
    recorded_at: datetime | None = None,
    note: str = "",
    **measures: Decimal | int | None,
) -> Vitals:
    """Record vital signs (nurse or doctor, FEATURES 3.4). Every measure is optional."""
    unknown = sorted(set(measures) - set(VITAL_RANGES))
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "Unknown vital signs", fields=unknown)
    given = {k: v for k, v in measures.items() if v is not None}
    if not given:
        raise DomainError("VITALS_EMPTY", "Record at least one vital sign")
    for name, value in given.items():
        low, high = VITAL_RANGES[name]
        if isinstance(value, bool) or not low <= Decimal(value) <= high:
            raise DomainError(
                "VITALS_OUT_OF_RANGE", "Implausible vital sign", field=name, value=str(value)
            )
    sys_bp, dia_bp = given.get("bp_systolic"), given.get("bp_diastolic")
    if (sys_bp is None) != (dia_bp is None):
        raise DomainError("BP_INCOMPLETE", "Blood pressure needs systolic and diastolic")
    if sys_bp is not None and dia_bp is not None and Decimal(dia_bp) >= Decimal(sys_bp):
        raise DomainError("VITALS_OUT_OF_RANGE", "Diastolic must be below systolic")
    when = recorded_at or timezone.now()
    if when > timezone.now() + timedelta(minutes=5):
        raise DomainError("INVALID_TIME", "Vitals cannot be recorded in the future")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="vitals"):
        return Vitals.objects.create(
            visit=_open_visit(visit),
            recorded_by=actor,
            recorded_at=when,
            note=note.strip()[:300],
            **given,
        )


# --- referrals ------------------------------------------------------------------------------


def create_referral(
    visit: Visit,
    *,
    actor: User,
    kind: str,
    reason: str,
    to_department: Department | None = None,
    to_doctor: DoctorProfile | None = None,
    external_facility: str = "",
    clinical_summary: str = "",
    urgency: str = Urgency.ROUTINE,
) -> Referral:
    """Referral note to another department or an external facility (FEATURES 3.9)."""
    _choice(kind, ReferralKind, "INVALID_REFERRAL_KIND")
    _choice(urgency, Urgency, "INVALID_URGENCY")
    if not reason.strip():
        raise DomainError("REASON_REQUIRED", "A referral states its reason")
    if kind == ReferralKind.INTERNAL:
        if to_department is None and to_doctor is not None:
            to_department = to_doctor.department
        if to_department is None:
            raise DomainError("DEPARTMENT_REQUIRED", "An internal referral names a department")
    elif not external_facility.strip():
        raise DomainError("FACILITY_REQUIRED", "An external referral names the facility")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="referral"):
        return Referral.objects.create(
            visit=_open_visit(visit),
            kind=kind,
            to_department=to_department,
            to_doctor=to_doctor,
            external_facility=external_facility.strip()[:200],
            reason=reason.strip(),
            clinical_summary=clinical_summary,
            urgency=urgency,
            referred_by=actor,
        )


def _close_referral(referral: Referral, status: str, actor: User) -> Referral:
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"referral {status}"):
        locked = Referral.objects.select_for_update().get(pk=referral.pk)
        if locked.status != ReferralStatus.ISSUED:
            raise DomainError("REFERRAL_CLOSED", "The referral is already closed")
        locked.status = status
        locked.save(update_fields=["status", "updated_at"])
    return locked


def complete_referral(referral: Referral, *, actor: User) -> Referral:
    return _close_referral(referral, ReferralStatus.COMPLETED, actor)


def cancel_referral(referral: Referral, *, actor: User) -> Referral:
    return _close_referral(referral, ReferralStatus.CANCELLED, actor)


# --- order sets -----------------------------------------------------------------------------


def create_order_set(
    *,
    name_ar: str,
    name_en: str,
    items: Sequence[Mapping[str, Any]],
    actor: User,
    personal: bool = True,
    department: Department | None = None,
) -> OrderSet:
    """A reusable group of orders; ``personal`` makes it the actor's favorite (FEATURES 3.6).

    Each item: ``service`` and optional ``quantity``, ``dose``, ``frequency_code``,
    ``duration_days``, ``instructions``.
    """
    if not (name_ar.strip() or name_en.strip()):
        raise DomainError("NAME_REQUIRED", "An order set needs a name")
    if not items:
        raise DomainError("ORDER_EMPTY", "An order set needs at least one service")
    allowed = {"service", "quantity", "dose", "frequency_code", "duration_days", "instructions"}
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="order set"):
        order_set = OrderSet.objects.create(
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            owner=actor if personal else None,
            department=department,
        )
        for position, raw in enumerate(items):
            extra = sorted(set(raw) - allowed)
            if extra:
                raise DomainError("FIELD_NOT_EDITABLE", "Unknown order set fields", fields=extra)
            service: Service = raw["service"]
            if not service.active:
                raise DomainError("SERVICE_INACTIVE", "The service is inactive", service=service.pk)
            quantity = Decimal(raw.get("quantity", 1))
            if quantity <= 0:
                raise DomainError("INVALID_QUANTITY", "Quantities are positive")
            OrderSetItem.objects.create(
                order_set=order_set,
                service=service,
                quantity=quantity,
                dose=str(raw.get("dose", ""))[:60],
                frequency_code=str(raw.get("frequency_code", ""))[:20],
                duration_days=raw.get("duration_days"),
                instructions=str(raw.get("instructions", ""))[:300],
                sort_order=position,
            )
    return order_set


def order_sets_for(user: User, *, department: Department | None = None) -> QuerySet[OrderSet]:
    """Shared order sets (optionally of a department) and the user's own favorites."""
    shared = Q(owner__isnull=True)
    if department is not None:
        shared &= Q(department__isnull=True) | Q(department=department)
    return OrderSet.objects.filter(active=True).filter(shared | Q(owner=user))


def order_set_items(order_set: OrderSet) -> list[dict[str, Any]]:
    """The set's active orders as ``orders.services.LineInput`` fields, for :func:`order_lines`.

    Drug items carry their dose, frequency, duration and instructions as the prescription;
    other items carry the instructions as the order note.
    """
    out: list[dict[str, Any]] = []
    for it in order_set.items.select_related("service").order_by("sort_order", "id"):
        if not it.service.active:
            continue
        entry: dict[str, Any] = {"service": it.service, "quantity": it.quantity}
        if it.service.kind == ServiceKind.DRUG:
            entry["prescription"] = {
                "dose": it.dose,
                "frequency_code": it.frequency_code,
                "duration_days": it.duration_days,
                "instructions": it.instructions,
            }
        elif it.instructions:
            entry["note"] = it.instructions
        out.append(entry)
    return out


# --- nursing notes --------------------------------------------------------------------------


def add_nursing_note(
    visit: Visit,
    *,
    actor: User,
    text: str,
    kind: str = NursingNoteKind.GENERAL,
    service_line: ServiceLine | None = None,
) -> NursingNote:
    """Nursing note on a visit, optionally about one service line (FEATURES 10.3)."""
    _choice(kind, NursingNoteKind, "INVALID_NOTE_KIND")
    if not text.strip():
        raise DomainError("NOTE_EMPTY", "A nursing note needs text")
    if service_line is not None and service_line.visit_id != visit.pk:
        raise DomainError("LINE_NOT_ON_VISIT", "The line belongs to another visit")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="nursing note"):
        return NursingNote.objects.create(
            visit=visit, kind=kind, service_line=service_line, text=text.strip(), author=actor
        )


# --- patient summary ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatientSummary:
    """What a doctor sees on opening a file (FEATURES 3.1). No prices."""

    patient: Patient
    allergies: list[Allergy] = field(default_factory=list)
    conditions: list[ChronicCondition] = field(default_factory=list)
    recent_visits: list[Visit] = field(default_factory=list)
    active_medications: list[ServiceLine] = field(default_factory=list)
    latest_results: list[Any] = field(default_factory=list)


def patient_summary(patient: Patient, *, medication_days: int = 30) -> PatientSummary:
    """Allergies (active), chronic conditions, last 5 visits, recent drug orders that were
    not cancelled, and the latest approved lab results (unapproved results never show).
    """
    from apps.lab.models import ResultStatus, ResultVersion

    who = patient_services.resolve(patient)
    ids = patient_services.file_ids(who)
    since = timezone.now() - timedelta(days=medication_days)
    return PatientSummary(
        patient=who,
        allergies=list(
            Allergy.objects.filter(patient_id__in=ids, status=RecordStatus.ACTIVE).order_by(
                "-recorded_at"
            )
        ),
        conditions=list(
            ChronicCondition.objects.filter(
                patient_id__in=ids, status=RecordStatus.ACTIVE
            ).order_by("-recorded_at")
        ),
        recent_visits=list(
            Visit.objects.filter(patient_id__in=ids).order_by("-created_at", "-id")[:5]
        ),
        active_medications=list(
            ServiceLine.objects.filter(
                visit__patient_id__in=ids, kind=ServiceKind.DRUG, ordered_at__gte=since
            )
            .exclude(fulfilment_status=FulfilmentStatus.CANCELLED)
            .select_related("service")
            .order_by("-ordered_at")
        ),
        latest_results=list(
            ResultVersion.objects.filter(
                result_set__service_line__visit__patient_id__in=ids,
                status=ResultStatus.APPROVED,
            )
            .select_related("result_set__test")
            .order_by("-approved_at")[:10]
        ),
    )


# --- merge support and estimated cost -----------------------------------------------------


def reassign_patient(source: Patient, target: Patient, *, actor: User) -> int:
    """Move allergies and chronic conditions of a merged file to the surviving file.

    Called by ``apps.patients.services.merge_patients`` inside its transaction: clinical
    safety data follows the person (FEATURES 1.4). Returns how many records moved.
    """
    moved = 0
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="merge: clinical"):
        for allergy in Allergy.objects.select_for_update().filter(patient=source):
            allergy.patient = target
            allergy.save(update_fields=["patient", "updated_at"])
            moved += 1
        for condition in ChronicCondition.objects.select_for_update().filter(patient=source):
            condition.patient = target
            condition.save(update_fields=["patient", "updated_at"])
            moved += 1
    return moved


@dataclass(frozen=True, slots=True)
class EstimatedCost:
    """What the patient would pay for an order today (FEATURES 3.8): an estimate only."""

    service_id: int
    quantity: int
    patient_share: Decimal


def estimated_cost(
    visit: Visit, items: Sequence[tuple[Service, int]], *, actor: User
) -> list[EstimatedCost]:
    """The patient's estimated share of ``items`` at today's prices and the visit's coverage.

    Shown to a doctor only when the center enables it (``Policy.show_estimated_cost``) and
    the doctor holds ``clinical.view_estimated_cost`` (FEATURES 3.8); doctors otherwise
    never see prices.

    Raises:
        PermissionRequired: without ``clinical.view_estimated_cost``.
        DomainError: ``ESTIMATED_COST_DISABLED``, ``PRICE_NOT_FOUND``,
            ``NO_EFFECTIVE_PRICE_LIST``, ``INVALID_QUANTITY``.
    """
    if not Policy.load().show_estimated_cost:
        raise DomainError("ESTIMATED_COST_DISABLED", "The center does not show estimated costs")
    require_permission(actor, "clinical.view_estimated_cost")
    on = timezone.localdate()
    payer = visit.payer
    prices = catalog.effective_prices([svc for svc, _ in items], on=on, payer=payer)
    out = []
    for svc, quantity in items:
        if isinstance(quantity, bool) or int(quantity) < 1:
            raise DomainError("INVALID_QUANTITY", "Quantity must be a whole number >= 1")
        gross = q(prices[svc.pk].unit_price * int(quantity))
        rule, excluded = None, False
        if payer is not None:
            resolved = catalog.resolve_coverage(payer, svc)
            rule, excluded = resolved.domain_rule, resolved.excluded
        split = dc.split_line(gross, Decimal(0), rule, excluded=excluded)
        out.append(EstimatedCost(svc.pk, int(quantity), split.patient_share))
    return out
