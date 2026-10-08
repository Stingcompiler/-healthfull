"""Clinical services for doctors and nurses (FEATURES 3, 10.3).

* Allergy and chronic condition registry; prescribing a drug whose stock item matches an
  active allergy (the same item, one of its drug classes, or a described substance in its
  name) is refused with ``ALLERGY_CONFLICT`` and the matches unless the prescriber gives an
  override reason, which is stored with who and when (``AllergyOverride``, FEATURES 3.2,
  invariant 4). Orders go through ``orders.services.create_service_lines``; a prescription's
  quantity is computed from dose, frequency and duration (``domain.prescription``).
* The doctor's worklist (FEATURES 2.3, 3): the paid, ready entries of the doctor's own queue
  today, with call next, call, start, complete and no-show.
* Clinical notes are drafts until signed; a signed note never changes (corrections are a new
  note). Only the author edits a draft.
* Diagnoses with ICD-10 lookup (code prefix, or words of the English/Arabic title folded the
  same way as patient search), vitals with plausibility checks, referrals, order sets and
  favorites, nursing notes, and the patient summary a doctor sees on opening a file.

Nothing here carries prices: doctors never see billing (FEATURES 3.8).
"""

from __future__ import annotations

import importlib
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
    AllergyOverride,
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
from apps.orders.models import FulfilmentStatus, Route, ServiceLine
from apps.patients import services as patient_services
from apps.patients.models import Patient
from apps.pharmacy.models import DrugClass, Item
from apps.visits import services as visit_services
from apps.visits.models import ACTIVE_QUEUE_STATUSES, QueueEntry, QueueStatus, Visit, VisitStatus
from domain import coverage as dc
from domain import prescription as dp
from domain.errors import DomainError
from domain.money import q

__all__ = [
    "ALLERGY_OVERRIDE_REASON_MIN",
    "QUEUE_ACTIONS",
    "VITAL_RANGES",
    "AllergyAlert",
    "EstimatedCost",
    "EstimatedOrder",
    "Frequency",
    "HistoryEntry",
    "PatientSummary",
    "ReferralTargets",
    "VisitWorkspace",
    "Worklist",
    "active_allergies",
    "add_diagnosis",
    "add_nursing_note",
    "allergies_recorded",
    "allergy_alerts",
    "allergy_alerts_for",
    "allergy_registry",
    "approved_results",
    "call_next",
    "cancel_referral",
    "complete_referral",
    "condition_registry",
    "create_favorite",
    "create_order_set",
    "create_referral",
    "deactivate_order_set",
    "doctor_order_sets",
    "doctor_profile",
    "doctor_queue",
    "drug_classes",
    "estimate_order",
    "estimated_cost",
    "frequencies",
    "icd10_by_code",
    "order_lines",
    "order_set_items",
    "order_sets_for",
    "patient_history",
    "patient_summary",
    "place_orders",
    "prepare_order_items",
    "prescription_quantity",
    "preview_prescription",
    "queue_action",
    "queue_entry_view",
    "reassign_patient",
    "record_allergy",
    "record_condition",
    "record_vitals",
    "referral_targets",
    "remove_diagnosis",
    "save_note",
    "search_icd10",
    "set_allergy_status",
    "set_condition_status",
    "sign_note",
    "update_allergy",
    "update_condition",
    "visit_queue_entry",
    "visit_workspace",
    "worklist",
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
#: Fewest characters of an allergy override reason (invariant 4: a reason that says something).
ALLERGY_OVERRIDE_REASON_MIN = 3
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


def _withdrawal_reason(reason: str | None) -> str:
    """The stated reason for withdrawing clinical data (invariant 4), kept in the audit
    history's context.

    Raises:
        DomainError: ``REASON_REQUIRED``.
    """
    why = " ".join((reason or "").split())
    if not why:
        raise DomainError("REASON_REQUIRED", "State why the record is withdrawn")
    return why[:200]


# --- allergies and prescribing alerts -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AllergyAlert:
    """An active allergy that matches a drug being prescribed."""

    service_id: int
    allergy_id: int
    match: str  # "item", "drug_class" or "substance"
    severity: str
    allergen: str
    allergen_ar: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "allergy_id": self.allergy_id,
            "match": self.match,
            "severity": self.severity,
            "allergen": self.allergen,
            "allergen_ar": self.allergen_ar or self.allergen,
        }


def record_allergy(
    patient: Patient,
    *,
    actor: User,
    allergen_type: str,
    drug_class: DrugClass | None = None,
    drug_class_id: int | None = None,
    item: Item | None = None,
    substance: str = "",
    reaction: str = "",
    severity: str = Severity.MODERATE,
    note: str = "",
) -> Allergy:
    """Add an allergy to the registry (FEATURES 3.2).

    The drug class is given as a row or by id (``drug_class_id``); a new allergy names an
    active class only.

    Raises:
        DomainError: ``INVALID_ALLERGEN_TYPE``, ``INVALID_SEVERITY``, ``DRUG_CLASS_INACTIVE``
            (unknown or retired class), ``DRUG_CLASS_REQUIRED``, ``ALLERGEN_REQUIRED``.
    """
    if drug_class is None and drug_class_id is not None:
        drug_class = DrugClass.objects.filter(pk=drug_class_id).first()
        if drug_class is None:
            raise DomainError(
                "DRUG_CLASS_INACTIVE", "The drug class is unknown or retired", id=drug_class_id
            )
    if drug_class is not None and not drug_class.active:
        raise DomainError(
            "DRUG_CLASS_INACTIVE", "The drug class is unknown or retired", id=drug_class.pk
        )
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


def set_allergy_status(
    allergy: Allergy, *, status: str, actor: User, note: str = "", reason: str = ""
) -> Allergy:
    """Resolve an allergy or mark it entered in error (history keeps the old row)."""
    return update_allergy(allergy, actor=actor, status=status, note=note or None, reason=reason)


def update_allergy(
    allergy: Allergy,
    *,
    actor: User,
    status: str | None = None,
    severity: str | None = None,
    reaction: str | None = None,
    note: str | None = None,
    reason: str = "",
) -> Allergy:
    """Change an allergy's status, severity, reaction or note (FEATURES 3.2).

    The allergen itself never changes: a wrong entry is marked ``entered_in_error`` and a new
    one recorded, so the history shows what alerted when. Marking it in error stops its
    prescribing alerts, so it needs a ``reason``, kept with who and when in the audit
    history (invariant 4). ``None`` leaves a field as it is.

    Raises:
        DomainError: ``INVALID_STATUS``, ``INVALID_SEVERITY``, ``NOTHING_TO_CHANGE``,
            ``REASON_REQUIRED``.
    """
    changes: dict[str, str] = {}
    if status is not None:
        changes["status"] = _choice(status, RecordStatus, "INVALID_STATUS")
    if severity is not None:
        changes["severity"] = _choice(severity, Severity, "INVALID_SEVERITY")
    if reaction is not None:
        changes["reaction"] = reaction.strip()[:300]
    if note is not None:
        changes["note"] = note.strip()
    if not changes:
        raise DomainError("NOTHING_TO_CHANGE", "Nothing to change")
    context = f"allergy {status}" if status else "allergy update"
    if status == RecordStatus.ERROR:
        context = f"{context}: {_withdrawal_reason(reason)}"
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=context):
        locked = Allergy.objects.select_for_update().get(pk=allergy.pk)
        for name, value in changes.items():
            setattr(locked, name, value)
        locked.save(update_fields=[*changes, "updated_at"])
    return locked


def drug_classes() -> QuerySet[DrugClass]:
    """Active drug classes, for recording a class allergy."""
    return DrugClass.objects.filter(active=True).order_by("name_en", "code")


def _drug_items(services: Iterable[Service]) -> dict[int, Item]:
    ids = [s.pk for s in services if s.kind in (ServiceKind.DRUG, ServiceKind.CONSUMABLE)]
    return {
        it.service_id: it
        for it in Item.objects.filter(service_id__in=ids).prefetch_related("drug_classes")
    }


def allergy_alerts_for(patient: Patient, service_ids: Iterable[int]) -> list[AllergyAlert]:
    """The allergy matches of services named by id, for a warning while an order is written
    (FEATURES 3.2). Placing the order still refuses them (``ALLERGY_CONFLICT``)."""
    wanted = sorted(set(service_ids))[:100]
    return allergy_alerts(patient, Service.objects.filter(pk__in=wanted))


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
                allergen_ar = (
                    allergy.substance
                    or (allergy.drug_class.name_ar if allergy.drug_class else "")
                    or allergen
                )
                alerts.append(
                    AllergyAlert(
                        service_id, allergy.pk, match, allergy.severity, allergen, allergen_ar
                    )
                )
    return alerts


def prescription_quantity(
    *, dose_quantity: Decimal, frequency_per_day: Decimal, duration_days: int
) -> int:
    """Base units to dispense: dose x frequency x days, rounded up (FEATURES 3.5)."""
    return dp.dispense_quantity(dose_quantity, frequency_per_day, duration_days)


@dataclass(frozen=True, slots=True)
class Frequency:
    """A prescription frequency code and its doses per day (``None``: single or as needed)."""

    code: str
    per_day: Decimal | None


def frequencies() -> list[Frequency]:
    """The frequency codes the prescription builder offers, in the domain's order."""
    return [Frequency(code, per_day) for code, per_day in dp.FREQUENCIES.items()]


def preview_prescription(
    *,
    dose_quantity: Decimal | None,
    frequency_code: str = "",
    frequency_per_day: Decimal | None = None,
    duration_days: int | None = None,
    as_needed: bool = False,
) -> dp.Prescription:
    """The doses per day and the quantity a prescription would order (FEATURES 3.5).

    The prescription builder shows it before the order is placed; :func:`order_lines` computes
    the same quantity again when the order is placed. ``quantity`` is ``None`` when it
    cannot be counted (as needed, a single dose without a dose quantity, no duration).

    Raises:
        DomainError: ``UNKNOWN_FREQUENCY``, ``FREQUENCY_MISMATCH``, ``INVALID_PRESCRIPTION``.
    """
    return dp.resolve(
        dose_quantity=dose_quantity,
        frequency_code=frequency_code,
        frequency_per_day=frequency_per_day,
        duration_days=duration_days,
        as_needed=as_needed,
    )


def _decimal_or_none(value: Any, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool | float):
        raise DomainError("INVALID_PRESCRIPTION", "Not a decimal number", field=name)
    try:
        return Decimal(str(value))
    except ArithmeticError as exc:
        raise DomainError("INVALID_PRESCRIPTION", "Not a decimal number", field=name) from exc


def _int_or_none(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainError("INVALID_PRESCRIPTION", "Not a whole number", field=name)
    return value


def prepare_order_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Resolve services and fill each drug's quantity from its prescription (FEATURES 3.5).

    A prescription's frequency code fills its doses per day (``domain.prescription``). A drug
    line without a quantity gets ``ceil(dose x doses per day x days)``; one that cannot be
    counted (as needed, no duration) needs an explicit quantity (``QUANTITY_REQUIRED``). A
    stated quantity is kept when it covers the course (the prescriber may round up to a whole
    pack) and refused below it (``QUANTITY_BELOW_PRESCRIPTION``).

    Raises:
        DomainError: ``ORDER_EMPTY``, ``SERVICE_INACTIVE``, ``QUANTITY_REQUIRED``,
            ``QUANTITY_BELOW_PRESCRIPTION``,
            ``PRESCRIPTION_NOT_DRUG``, ``UNKNOWN_FREQUENCY``, ``FREQUENCY_MISMATCH``,
            ``INVALID_PRESCRIPTION``.
    """
    if not items:
        raise DomainError("ORDER_EMPTY", "Nothing to order")
    ids = [i["service"] if isinstance(i["service"], int) else i["service"].pk for i in items]
    services = Service.objects.in_bulk(ids)
    out: list[dict[str, Any]] = []
    for raw, sid in zip(items, ids, strict=True):
        service = services.get(sid)
        if service is None or not service.active:
            raise DomainError(
                "SERVICE_INACTIVE", "The service is unknown or inactive", service_id=sid
            )
        item: dict[str, Any] = {**raw, "service": service}
        rx = raw.get("prescription")
        if rx is not None:
            if service.kind != ServiceKind.DRUG:
                raise DomainError("PRESCRIPTION_NOT_DRUG", "Only drug lines carry a prescription")
            detail = dict(rx)
            resolved = dp.resolve(
                dose_quantity=_decimal_or_none(detail.get("dose_quantity"), "dose_quantity"),
                frequency_code=str(detail.get("frequency_code") or ""),
                frequency_per_day=_decimal_or_none(
                    detail.get("frequency_per_day"), "frequency_per_day"
                ),
                duration_days=_int_or_none(detail.get("duration_days"), "duration_days"),
                as_needed=bool(detail.get("as_needed")),
            )
            detail["frequency_code"] = resolved.frequency_code
            detail["frequency_per_day"] = resolved.frequency_per_day
            item["prescription"] = detail
            quantity = dp.order_quantity(resolved.quantity, item.get("quantity"))
            if quantity is None:
                raise DomainError(
                    "QUANTITY_REQUIRED",
                    "State the quantity of an as-needed or open-ended prescription",
                    service_id=sid,
                )
            item["quantity"] = quantity
        elif item.get("quantity") is None:
            item.pop("quantity", None)
        out.append(item)
    return out


def order_lines(
    visit: Visit,
    items: Sequence[Mapping[str, Any]],
    *,
    actor: User,
    allergy_override_reason: str = "",
) -> list[ServiceLine]:
    """Order services on a visit after the allergy check (FEATURES 3.2, 3.5).

    ``items`` (each with a ``service``: a ``Service`` or its id) go through
    :func:`prepare_order_items`, then ``orders.services.create_service_lines``. With matching
    allergies the order is refused with ``ALLERGY_CONFLICT`` (``details.alerts``) unless
    ``allergy_override_reason`` says why the drug is given anyway, in at least
    :data:`ALLERGY_OVERRIDE_REASON_MIN` characters; the override is then stored per ordered
    line and matching allergy, with who and when (invariant 4).

    Raises:
        DomainError: ``VISIT_NOT_OPEN``, ``ALLERGY_CONFLICT``,
            ``ALLERGY_OVERRIDE_REASON_TOO_SHORT``, the errors of
            :func:`prepare_order_items` and of ``orders.services.create_service_lines``.
    """
    _open_visit(visit)
    prepared = prepare_order_items(items)
    alerts = allergy_alerts(visit.patient, [i["service"] for i in prepared])
    reason = allergy_override_reason.strip()
    if alerts and not reason:
        raise DomainError(
            "ALLERGY_CONFLICT",
            "The patient is allergic to a prescribed drug; give a reason to override",
            alerts=[a.as_dict() for a in alerts],
        )
    if alerts and len(reason) < ALLERGY_OVERRIDE_REASON_MIN:
        raise DomainError(
            "ALLERGY_OVERRIDE_REASON_TOO_SHORT",
            "Say why the drug is given despite the allergy",
            min_length=ALLERGY_OVERRIDE_REASON_MIN,
        )
    context = f"order (allergy override: {reason})"[:250] if alerts else "order"
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=context):
        lines = list(_orders().create_service_lines(visit, prepared, actor))
        if alerts:
            now = timezone.now()
            by_service: dict[int, list[ServiceLine]] = {}
            for line in lines:
                by_service.setdefault(line.service_id, []).append(line)
            AllergyOverride.objects.bulk_create(
                AllergyOverride(
                    service_line=line,
                    allergy_id=alert.allergy_id,
                    match=alert.match,
                    reason=reason[:1000],
                    overridden_by=actor,
                    overridden_at=now,
                )
                for alert in alerts
                for line in by_service.get(alert.service_id, [])
            )
    return lines


def place_orders(
    visit: Visit,
    items: Sequence[Mapping[str, Any]],
    *,
    actor: User,
    allergy_override_reason: str = "",
) -> list[Any]:
    """:func:`order_lines`, answered in the doctor's view of the new lines
    (``orders.services.DoctorLine``: status, never prices)."""
    created = {
        ln.pk
        for ln in order_lines(
            visit, items, actor=actor, allergy_override_reason=allergy_override_reason
        )
    }
    return [d for d in _orders().doctor_lines(visit) if d.line.pk in created]


# --- chronic conditions ---------------------------------------------------------------------


def record_condition(
    patient: Patient,
    *,
    actor: User,
    icd10: Icd10Code | None = None,
    icd10_code: str | None = None,
    name: str = "",
    since: Any = None,
    note: str = "",
) -> ChronicCondition:
    """Add a chronic condition by ICD-10 row or code, by name, or both (FEATURES 3.2).

    Raises:
        DomainError: ``ICD10_UNKNOWN``, ``CONDITION_NAME_REQUIRED``.
    """
    if icd10 is None:
        icd10 = icd10_by_code(icd10_code)
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
    condition: ChronicCondition, *, status: str, actor: User, reason: str = ""
) -> ChronicCondition:
    return update_condition(condition, actor=actor, status=status, reason=reason)


def update_condition(
    condition: ChronicCondition,
    *,
    actor: User,
    status: str | None = None,
    note: str | None = None,
    reason: str = "",
) -> ChronicCondition:
    """Resolve a chronic condition, mark it entered in error, or change its note.

    Marking it in error needs a ``reason``, kept with who and when in the audit history
    (invariant 4).

    Raises:
        DomainError: ``INVALID_STATUS``, ``NOTHING_TO_CHANGE``, ``REASON_REQUIRED``.
    """
    changes: dict[str, str] = {}
    if status is not None:
        changes["status"] = _choice(status, RecordStatus, "INVALID_STATUS")
    if note is not None:
        changes["note"] = note.strip()
    if not changes:
        raise DomainError("NOTHING_TO_CHANGE", "Nothing to change")
    context = f"condition {status}" if status else "condition update"
    if status == RecordStatus.ERROR:
        context = f"{context}: {_withdrawal_reason(reason)}"
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=context):
        locked = ChronicCondition.objects.select_for_update().get(pk=condition.pk)
        for name, value in changes.items():
            setattr(locked, name, value)
        locked.save(update_fields=[*changes, "updated_at"])
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


def remove_diagnosis(diagnosis: Diagnosis, *, actor: User, reason: str) -> None:
    """Withdraw a diagnosis recorded in error, while the visit is open, by its author.

    The deletion is kept in the audit history with who, when, why and the removed row.

    Raises:
        DomainError: ``REASON_REQUIRED``, ``VISIT_NOT_OPEN``, ``DIAGNOSIS_NOT_AUTHOR``.
    """
    why = _withdrawal_reason(reason)
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"remove diagnosis: {why}"),
    ):
        locked = Diagnosis.objects.select_for_update().select_related("visit").get(pk=diagnosis.pk)
        _open_visit(locked.visit)
        if locked.recorded_by_id != actor.pk:
            raise DomainError("DIAGNOSIS_NOT_AUTHOR", "Only who recorded a diagnosis removes it")
        locked.delete()


def icd10_by_code(code: str | None) -> Icd10Code | None:
    """The active ICD-10 row of a code (case-insensitive), ``None`` for no code.

    Raises:
        DomainError: ``ICD10_UNKNOWN``.
    """
    if not code or not code.strip():
        return None
    found = Icd10Code.objects.filter(code__iexact=code.strip(), active=True).first()
    if found is None:
        raise DomainError("ICD10_UNKNOWN", "Unknown ICD-10 code", icd10=code)
    return found


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


def complete_referral(referral: Referral, *, actor: User) -> Referral:
    """Mark an issued referral completed.

    Raises:
        DomainError: ``REFERRAL_CLOSED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="referral completed"):
        locked = Referral.objects.select_for_update().get(pk=referral.pk)
        if locked.status != ReferralStatus.ISSUED:
            raise DomainError("REFERRAL_CLOSED", "The referral is already closed")
        locked.status = ReferralStatus.COMPLETED
        locked.save(update_fields=["status", "updated_at"])
    return locked


def cancel_referral(referral: Referral, *, actor: User, reason: str) -> Referral:
    """Cancel an issued referral with a reason, by the doctor who wrote it, while its visit
    is open. The reason, who and when are stored on the row (invariant 4).

    Raises:
        DomainError: ``REASON_REQUIRED``, ``REFERRAL_CLOSED``, ``REFERRAL_NOT_AUTHOR``,
            ``VISIT_NOT_OPEN``.
    """
    reason = reason.strip()
    if not reason:
        raise DomainError("REASON_REQUIRED", "A cancelled referral states why")
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"referral cancelled: {reason[:200]}"),
    ):
        locked = Referral.objects.select_for_update().select_related("visit").get(pk=referral.pk)
        if locked.status != ReferralStatus.ISSUED:
            raise DomainError("REFERRAL_CLOSED", "The referral is already closed")
        if locked.referred_by_id != actor.pk:
            raise DomainError("REFERRAL_NOT_AUTHOR", "Only who wrote a referral cancels it")
        _open_visit(locked.visit)
        locked.status = ReferralStatus.CANCELLED
        locked.cancel_reason = reason
        locked.cancelled_by = actor
        locked.cancelled_at = timezone.now()
        locked.save(
            update_fields=["status", "cancel_reason", "cancelled_by", "cancelled_at", "updated_at"]
        )
    return locked


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

    Each item: ``service`` and optional ``quantity``, ``dose``, ``dose_quantity``,
    ``route``, ``frequency_code``, ``duration_days``, ``as_needed``, ``instructions``. A drug
    keeps its route and dose quantity, so a reapplied favorite orders the same prescription
    and its quantity follows dose x frequency x duration again (FEATURES 3.5, 3.6).

    Raises:
        DomainError: ``NAME_REQUIRED``, ``ORDER_EMPTY``, ``FIELD_NOT_EDITABLE``,
            ``SERVICE_INACTIVE``, ``INVALID_QUANTITY``, ``INVALID_ROUTE``.
    """
    if not (name_ar.strip() or name_en.strip()):
        raise DomainError("NAME_REQUIRED", "An order set needs a name")
    if not items:
        raise DomainError("ORDER_EMPTY", "An order set needs at least one service")
    allowed = {
        "service",
        "quantity",
        "dose",
        "dose_quantity",
        "route",
        "frequency_code",
        "duration_days",
        "as_needed",
        "instructions",
    }
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
            dose_quantity = raw.get("dose_quantity")
            dose_quantity = None if dose_quantity is None else Decimal(dose_quantity)
            if quantity <= 0 or (dose_quantity is not None and dose_quantity <= 0):
                raise DomainError("INVALID_QUANTITY", "Quantities are positive")
            route = str(raw.get("route") or "")
            if route and route not in Route.values:
                raise DomainError("INVALID_ROUTE", "Unknown route", value=route)
            is_drug = service.kind == ServiceKind.DRUG
            OrderSetItem.objects.create(
                order_set=order_set,
                service=service,
                quantity=quantity,
                dose=str(raw.get("dose", ""))[:60],
                dose_quantity=dose_quantity if is_drug else None,
                route=(route or Route.ORAL) if is_drug else "",
                frequency_code=str(raw.get("frequency_code", ""))[:20],
                duration_days=raw.get("duration_days"),
                as_needed=bool(raw.get("as_needed", False)) and is_drug,
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
                "dose_quantity": it.dose_quantity,
                "route": it.route or Route.ORAL,
                "frequency_code": it.frequency_code,
                "duration_days": it.duration_days,
                "as_needed": it.as_needed,
                "instructions": it.instructions,
            }
        elif it.instructions:
            entry["note"] = it.instructions
        out.append(entry)
    return out


def doctor_order_sets(user: User) -> list[OrderSet]:
    """The order sets a doctor chooses from: shared ones (of the doctor's department or of
    every department) and the doctor's own favorites, with their items (FEATURES 3.6)."""
    profile = doctor_profile(user)
    return list(
        order_sets_for(user, department=profile.department if profile else None)
        .prefetch_related("items__service")
        .order_by("sort_order", "name_en", "id")
    )


def create_favorite(
    *, name_ar: str, name_en: str, items: Sequence[Mapping[str, Any]], actor: User
) -> OrderSet:
    """Save orders as one of the actor's favorites (FEATURES 3.6). Items name their
    ``service_id``; the other fields are those of :func:`create_order_set`.

    Raises:
        DomainError: ``SERVICE_INACTIVE`` (unknown service), the errors of
            :func:`create_order_set`.
    """
    found = Service.objects.in_bulk([it["service_id"] for it in items])
    resolved: list[dict[str, Any]] = []
    for raw in items:
        service = found.get(raw["service_id"])
        if service is None:
            raise DomainError(
                "SERVICE_INACTIVE", "The service is unknown", service=raw["service_id"]
            )
        entry = {k: v for k, v in raw.items() if k != "service_id" and v is not None}
        resolved.append({**entry, "service": service})
    created = create_order_set(
        name_ar=name_ar, name_en=name_en, items=resolved, actor=actor, personal=True
    )
    return OrderSet.objects.prefetch_related("items__service").get(pk=created.pk)


def deactivate_order_set(order_set: OrderSet, *, actor: User) -> OrderSet:
    """Remove one of the actor's favorites (FEATURES 3.6). Shared sets are administered
    centrally, never from the doctor's screen.

    Raises:
        DomainError: ``ORDER_SET_NOT_OWNER``, ``ORDER_SET_INACTIVE``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="remove favorite"):
        locked = OrderSet.objects.select_for_update().get(pk=order_set.pk)
        if locked.owner_id != actor.pk:
            raise DomainError("ORDER_SET_NOT_OWNER", "Only the doctor who saved it removes it")
        if not locked.active:
            raise DomainError("ORDER_SET_INACTIVE", "The order set was already removed")
        locked.active = False
        locked.save(update_fields=["active", "updated_at"])
    return locked


# --- the doctor's queue (FEATURES 2.3, FLOW step 3) ------------------------------------------


def doctor_profile(user: User) -> DoctorProfile | None:
    """The user's active doctor profile, if they see patients."""
    return DoctorProfile.objects.filter(user=user, active=True).select_related("department").first()


def doctor_queue(user: User, *, include_done: bool = True) -> list[QueueEntry]:
    """Today's queue of the logged-in doctor, in serving order (FEATURES 2.3).

    Entries assigned to the doctor, and unassigned entries of the doctor's department, whose
    consultation is paid or authorized (``visits.services.queue``: invariant 1). Waiting,
    called and in-progress entries come first; with ``include_done`` the ones seen today
    follow. A user without a doctor profile has no queue.
    """
    profile = doctor_profile(user)
    if profile is None:
        return []
    statuses = [*ACTIVE_QUEUE_STATUSES, *([QueueStatus.DONE] if include_done else [])]
    mine = Q(doctor=profile) | Q(doctor__isnull=True, department_id=profile.department_id)
    entries = list(
        visit_services.queue(statuses=statuses)
        .filter(mine)
        .select_related("visit__department", "visit__payer", "visit__doctor__user", "doctor__user")
    )
    active = [e for e in entries if e.status != QueueStatus.DONE]
    done = sorted(
        (e for e in entries if e.status == QueueStatus.DONE),
        key=lambda e: e.done_at or e.created_at,
        reverse=True,
    )
    return active + done


@dataclass(frozen=True, slots=True)
class Worklist:
    """The doctor's queue with each patient's active allergies (FEATURES 2.3, 3.2)."""

    entries: list[QueueEntry]
    allergies: dict[int, list[Allergy]]
    recorded: set[int]


def worklist(user: User, *, include_done: bool = True) -> Worklist:
    """:func:`doctor_queue` plus, per patient file, the active allergies of the person
    (every merged file) and whether any allergy entry was ever recorded."""
    entries = doctor_queue(user, include_done=include_done)
    patients = {e.visit.patient_id: e.visit.patient for e in entries}
    allergies: dict[int, list[Allergy]] = {}
    recorded: set[int] = set()
    for pid, patient in patients.items():
        allergies[pid] = active_allergies(patient)
        if allergies[pid] or allergies_recorded(patient):
            recorded.add(pid)
    return Worklist(entries=entries, allergies=allergies, recorded=recorded)


def queue_entry_view(entry: QueueEntry) -> Worklist:
    """One queue entry as the worklist shows it, with the patient's allergies (after a
    queue action)."""
    loaded = QueueEntry.objects.select_related(
        "visit__patient", "visit__department", "visit__payer", "visit__doctor__user", "doctor__user"
    ).get(pk=entry.pk)
    patient = loaded.visit.patient
    allergies = active_allergies(patient)
    recorded = {patient.pk} if allergies or allergies_recorded(patient) else set()
    return Worklist(entries=[loaded], allergies={patient.pk: allergies}, recorded=recorded)


#: Doctor actions on a queue entry and the ``visits.services`` move each one makes.
QUEUE_ACTIONS = frozenset({"call", "start", "complete", "no_show", "requeue"})


def _own_entry(entry: QueueEntry, actor: User) -> DoctorProfile:
    profile = doctor_profile(actor)
    if profile is None:
        raise DomainError("DOCTOR_PROFILE_REQUIRED", "Only a doctor works a clinic queue")
    if entry.doctor_id not in (None, profile.pk) or (
        entry.doctor_id is None and entry.department_id != profile.department_id
    ):
        raise DomainError("QUEUE_OTHER_DOCTOR", "This patient waits for another doctor")
    return profile


def queue_action(entry: QueueEntry, action: str, *, actor: User) -> QueueEntry:
    """Call, start, complete, mark no-show or requeue one of the doctor's queue entries.

    Calling or starting an unassigned entry of the doctor's department claims it (and its
    visit, when it has no doctor): it leaves the other doctors' work lists and they get
    ``QUEUE_OTHER_DOCTOR`` from then on. Completing performs the consultation line
    (``visits.services.finish_consultation``); the visit stays open for the orders' billing
    and results.

    Completing needs ``visits.finish_consultation``, as finishing from the visits board does:
    it performs the consultation fee line, the doctor's act (FLOW step 3).

    Raises:
        PermissionRequired: ``complete`` by an actor without ``visits.finish_consultation``.
        DomainError: ``INVALID_QUEUE_ACTION``, ``DOCTOR_PROFILE_REQUIRED``,
            ``QUEUE_OTHER_DOCTOR``, ``QUEUE_TRANSITION_INVALID``, ``QUEUE_NOT_READY``.
    """
    if action not in QUEUE_ACTIONS:
        raise DomainError("INVALID_QUEUE_ACTION", "Unknown queue action", action=action)
    if action == "complete":
        require_permission(actor, "visits.finish_consultation")
    profile = _own_entry(entry, actor)
    if action == "call":
        return visit_services.call_patient(entry, actor=actor, doctor=profile)
    if action == "start":
        return visit_services.start_consultation(entry, actor=actor, doctor=profile)
    moves = {
        "complete": visit_services.finish_consultation,
        "no_show": visit_services.mark_no_show,
        "requeue": visit_services.requeue,
    }
    return moves[action](entry, actor=actor)


def call_next(actor: User) -> QueueEntry:
    """Call the first waiting patient of the doctor's queue (FEATURES 2.3).

    Raises:
        DomainError: ``DOCTOR_PROFILE_REQUIRED``, ``QUEUE_EMPTY``.
    """
    if doctor_profile(actor) is None:
        raise DomainError("DOCTOR_PROFILE_REQUIRED", "Only a doctor works a clinic queue")
    waiting = [e for e in doctor_queue(actor, include_done=False) if e.status == "waiting"]
    if not waiting:
        raise DomainError("QUEUE_EMPTY", "Nobody is waiting in your queue")
    return queue_action(waiting[0], "call", actor=actor)


def visit_queue_entry(visit: Visit) -> QueueEntry | None:
    """The visit's current queue entry: an active one, else the latest."""
    entries = QueueEntry.objects.filter(visit=visit).order_by("-created_at", "-id")
    active = entries.filter(status__in=ACTIVE_QUEUE_STATUSES).first()
    return active or entries.first()


@dataclass(frozen=True, slots=True)
class VisitWorkspace:
    """One visit as its doctor works on it (FEATURES 3.3, 3.4, 3.9). No prices."""

    visit: Visit
    queue_entry: QueueEntry | None
    notes: list[ClinicalNote] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    vitals: list[Vitals] = field(default_factory=list)
    referrals: list[Referral] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    allergies_recorded: bool = False


def visit_workspace(visit: Visit) -> VisitWorkspace:
    """The visit with its queue entry, notes (oldest first), diagnoses (primary first),
    vitals (newest first) and referrals (newest first)."""
    loaded = Visit.objects.select_related("patient", "department", "doctor__user", "payer").get(
        pk=visit.pk
    )
    allergies = active_allergies(loaded.patient)
    return VisitWorkspace(
        visit=loaded,
        queue_entry=visit_queue_entry(loaded),
        allergies=allergies,
        allergies_recorded=bool(allergies) or allergies_recorded(loaded.patient),
        notes=list(
            ClinicalNote.objects.filter(visit=loaded)
            .select_related("author")
            .order_by("created_at", "id")
        ),
        diagnoses=list(
            Diagnosis.objects.filter(visit=loaded)
            .select_related("icd10", "recorded_by")
            .order_by("kind", "recorded_at", "id")
        ),
        vitals=list(
            Vitals.objects.filter(visit=loaded)
            .select_related("recorded_by")
            .order_by("-recorded_at", "-id")
        ),
        referrals=list(
            Referral.objects.filter(visit=loaded)
            .select_related("to_department", "to_doctor__user", "referred_by", "cancelled_by")
            .order_by("-created_at", "-id")
        ),
    )


@dataclass(frozen=True, slots=True)
class ReferralTargets:
    """Where a doctor may refer a patient inside the center (FEATURES 3.9)."""

    departments: list[Department]
    doctors: list[DoctorProfile]


def referral_targets() -> ReferralTargets:
    """Active departments and active doctors, for an internal referral."""
    return ReferralTargets(
        departments=list(Department.objects.filter(active=True).order_by("sort_order", "code")),
        doctors=list(
            DoctorProfile.objects.filter(active=True, user__is_active=True)
            .select_related("user", "department")
            .order_by("department__sort_order", "department__code", "user__username")
        ),
    )


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
    allergies_recorded: bool = False


def patient_summary(patient: Patient, *, medication_days: int = 30) -> PatientSummary:
    """Allergies (active), whether any allergy entry was ever recorded, chronic conditions,
    last 5 visits, recent drug orders that were not cancelled, and the latest approved lab
    results (unapproved results never show).
    """
    from apps.lab.models import ResultStatus, ResultVersion

    who = patient_services.resolve(patient)
    ids = patient_services.file_ids(who)
    since = timezone.now() - timedelta(days=medication_days)
    allergies = list(
        Allergy.objects.filter(patient_id__in=ids, status=RecordStatus.ACTIVE)
        .select_related("drug_class", "item")
        .order_by("-recorded_at", "-id")
    )
    return PatientSummary(
        patient=who,
        allergies=allergies,
        allergies_recorded=bool(allergies) or Allergy.objects.filter(patient_id__in=ids).exists(),
        conditions=list(
            ChronicCondition.objects.filter(patient_id__in=ids, status=RecordStatus.ACTIVE)
            .select_related("icd10")
            .order_by("-recorded_at", "-id")
        ),
        recent_visits=list(
            Visit.objects.filter(patient_id__in=ids)
            .select_related("department", "doctor__user", "payer")
            .order_by("-created_at", "-id")[:5]
        ),
        active_medications=list(
            ServiceLine.objects.filter(
                visit__patient_id__in=ids, kind=ServiceKind.DRUG, ordered_at__gte=since
            )
            .exclude(fulfilment_status=FulfilmentStatus.CANCELLED)
            .select_related("service", "authorization", "prescription")
            .order_by("-ordered_at", "-id")
        ),
        latest_results=list(
            ResultVersion.objects.filter(
                result_set__service_line__visit__patient_id__in=ids,
                status=ResultStatus.APPROVED,
            )
            .select_related("result_set__test__service", "result_set__service_line")
            .prefetch_related("values__parameter")
            .order_by("-approved_at", "-id")[:10]
        ),
    )


def allergy_registry(patient: Patient) -> list[Allergy]:
    """Every allergy entry of the person (every merged file) except entries made in error:
    active first, then resolved ones, newest first (FEATURES 3.2)."""
    who = patient_services.resolve(patient)
    rows = (
        Allergy.objects.filter(patient_id__in=patient_services.file_ids(who))
        .exclude(status=RecordStatus.ERROR)
        .select_related("drug_class", "item")
        .order_by("-recorded_at", "-id")
    )
    return sorted(rows, key=lambda a: a.status != RecordStatus.ACTIVE)


def condition_registry(patient: Patient) -> list[ChronicCondition]:
    """Every chronic condition of the person except entries made in error, active first."""
    who = patient_services.resolve(patient)
    rows = (
        ChronicCondition.objects.filter(patient_id__in=patient_services.file_ids(who))
        .exclude(status=RecordStatus.ERROR)
        .select_related("icd10")
        .order_by("-recorded_at", "-id")
    )
    return sorted(rows, key=lambda c: c.status != RecordStatus.ACTIVE)


def active_allergies(patient: Patient) -> list[Allergy]:
    """The person's active allergies (every merged file), newest first."""
    who = patient_services.resolve(patient)
    return list(
        Allergy.objects.filter(
            patient_id__in=patient_services.file_ids(who), status=RecordStatus.ACTIVE
        )
        .select_related("drug_class", "item")
        .order_by("-recorded_at", "-id")
    )


def allergies_recorded(patient: Patient) -> bool:
    """Whether the registry holds any allergy entry for the person (active or not)."""
    who = patient_services.resolve(patient)
    return Allergy.objects.filter(patient_id__in=patient_services.file_ids(who)).exists()


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One past visit as a doctor reviews it: diagnoses, notes and orders. No prices."""

    visit: Visit
    diagnoses: list[Diagnosis] = field(default_factory=list)
    notes: list[ClinicalNote] = field(default_factory=list)
    lines: list[ServiceLine] = field(default_factory=list)


#: Order kinds shown in a clinical history (the consultation fee and bed days are billing).
_CLINICAL_KINDS = (ServiceKind.LAB, ServiceKind.PROCEDURE, ServiceKind.DRUG, ServiceKind.CONSUMABLE)


def patient_history(patient: Patient, *, limit: int = 20) -> list[HistoryEntry]:
    """The person's visits, newest first, with their diagnoses, notes and orders (FEATURES 3.1).

    Every merged file is included; cancelled visits are left out.
    """
    who = patient_services.resolve(patient)
    visits = list(
        Visit.objects.filter(patient_id__in=patient_services.file_ids(who))
        .exclude(status=VisitStatus.CANCELLED)
        .select_related("department", "doctor__user", "payer")
        .order_by("-created_at", "-id")[: max(1, min(limit, 100))]
    )
    ids = [v.pk for v in visits]
    diagnoses: dict[int, list[Diagnosis]] = {}
    for d in (
        Diagnosis.objects.filter(visit_id__in=ids)
        .select_related("icd10")
        .order_by("kind", "recorded_at", "id")
    ):
        diagnoses.setdefault(d.visit_id, []).append(d)
    notes: dict[int, list[ClinicalNote]] = {}
    for n in ClinicalNote.objects.filter(visit_id__in=ids).select_related("author"):
        notes.setdefault(n.visit_id, []).append(n)
    lines: dict[int, list[ServiceLine]] = {}
    for ln in (
        ServiceLine.objects.filter(visit_id__in=ids, kind__in=_CLINICAL_KINDS)
        .select_related("service", "authorization", "prescription")
        .order_by("id")
    ):
        lines.setdefault(ln.visit_id, []).append(ln)
    return [
        HistoryEntry(v, diagnoses.get(v.pk, []), notes.get(v.pk, []), lines.get(v.pk, []))
        for v in visits
    ]


def approved_results(patient: Patient, *, visit: Visit | None = None, limit: int = 20) -> list[Any]:
    """Approved lab results of the person (or of one visit), newest first, with values.

    Only the current approved version of a result shows; drafts never reach a doctor
    (FEATURES 9.4), and an amended version is replaced by its amendment.
    """
    from apps.lab.models import ResultStatus, ResultVersion

    who = patient_services.resolve(patient)
    qs = ResultVersion.objects.filter(
        result_set__service_line__visit__patient_id__in=patient_services.file_ids(who),
        status=ResultStatus.APPROVED,
    )
    if visit is not None:
        qs = qs.filter(result_set__service_line__visit=visit)
    return list(
        qs.select_related("result_set__test__service", "result_set__service_line")
        .prefetch_related("values__parameter")
        .order_by("-approved_at", "-id")[: max(1, min(limit, 100))]
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


@dataclass(frozen=True, slots=True)
class EstimatedOrder:
    """The patient's estimated share of a draft order, per line and in total (FEATURES 3.8)."""

    lines: list[EstimatedCost]
    total: Decimal


def estimate_order(
    visit: Visit, items: Sequence[Mapping[str, Any]], *, actor: User
) -> EstimatedOrder:
    """:func:`estimated_cost` of a draft order as the doctor builds it.

    ``items`` are shaped like :func:`order_lines` items (service id, optional quantity and
    prescription): drug quantities are computed the same way as when the order is placed.

    Raises:
        PermissionRequired: without ``clinical.view_estimated_cost``.
        DomainError: ``ESTIMATED_COST_DISABLED``, the errors of :func:`prepare_order_items`
            and of :func:`estimated_cost`.
    """
    if not Policy.load().show_estimated_cost:
        raise DomainError("ESTIMATED_COST_DISABLED", "The center does not show estimated costs")
    require_permission(actor, "clinical.view_estimated_cost")
    prepared = prepare_order_items(items)
    lines = estimated_cost(
        visit, [(i["service"], int(i.get("quantity") or 1)) for i in prepared], actor=actor
    )
    return EstimatedOrder(lines=lines, total=q(sum((ln.patient_share for ln in lines), Decimal(0))))
