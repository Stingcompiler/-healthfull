"""Schemas of ``/api/clinical`` (ARCHITECTURE 4.11 naming: ``In``, ``Out``, ``Patch``).

Doctors and nurses read every one of these: nothing here carries a price or a billing state
(FEATURES 3.8, 14.3). Builders (``*_out``) turn service results into the plain dicts the
operations return, so routers stay one service call plus one builder.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from ninja import Field, Schema

from apps.clinical.models import Allergy, ChronicCondition, Icd10Code
from apps.clinical.services import PatientSummary, VisitWorkspace
from apps.core.models import Department, DoctorProfile, User
from apps.patients.models import Patient
from apps.visits.models import QueueEntry, Visit

SeverityCode = Literal["mild", "moderate", "severe", "life_threatening"]
RecordStatusCode = Literal["active", "inactive", "entered_in_error"]
AllergenTypeCode = Literal["drug", "drug_class", "food", "environmental", "other"]
QueueStatusCode = Literal["waiting", "called", "in_progress", "done", "no_show", "cancelled"]
QueueActionCode = Literal["call", "start", "complete", "no_show", "requeue"]
VisitTypeCode = Literal["new", "follow_up", "emergency", "pharmacy_sale", "inpatient"]
VisitStatusCode = Literal["open", "closed", "cancelled"]
DiagnosisKindCode = Literal["primary", "secondary"]
CertaintyCode = Literal["provisional", "confirmed"]
ReferralKindCode = Literal["internal", "external"]
UrgencyCode = Literal["routine", "urgent", "emergency"]
ReferralStatusCode = Literal["issued", "completed", "cancelled"]
NoteStatusCode = Literal["draft", "signed"]
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


# --- references ----------------------------------------------------------------------------


class DepartmentRefOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class ClinicUserRefOut(Schema):
    id: int
    name_ar: str
    name_en: str


class DoctorRefOut(Schema):
    id: int
    department_id: int
    name_ar: str
    name_en: str


class ClinicPayerRefOut(Schema):
    code: str
    name_ar: str
    name_en: str


def department_ref(dept: Department | None) -> dict[str, Any] | None:
    if dept is None:
        return None
    return {"id": dept.pk, "code": dept.code, "name_ar": dept.name_ar, "name_en": dept.name_en}


def user_ref(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.pk, "name_ar": user.display_name_ar, "name_en": user.display_name_en}


def doctor_ref(doctor: DoctorProfile | None) -> dict[str, Any] | None:
    if doctor is None:
        return None
    return {
        "id": doctor.pk,
        "department_id": doctor.department_id,
        "name_ar": doctor.user.display_name_ar,
        "name_en": doctor.user.display_name_en,
    }


# --- patients and visits -------------------------------------------------------------------


class AllergyChipOut(Schema):
    """An active allergy as a prominent chip (PatientCard)."""

    id: int
    label_ar: str
    label_en: str
    severity: SeverityCode


class ClinicPatientOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: Literal["male", "female"]
    date_of_birth: date | None
    dob_is_estimated: bool
    phone: str
    is_incomplete: bool


class VisitBriefOut(Schema):
    id: int
    number: str
    visit_type: VisitTypeCode
    status: VisitStatusCode
    created_at: datetime
    chief_complaint: str
    department: DepartmentRefOut | None
    doctor: DoctorRefOut | None
    payer: ClinicPayerRefOut | None


def allergy_labels(allergy: Allergy) -> tuple[str, str]:
    """The allergen's name in Arabic and English (a described substance is kept as written)."""
    if allergy.substance:
        return allergy.substance, allergy.substance
    if allergy.drug_class is not None:
        return allergy.drug_class.name_ar, allergy.drug_class.name_en
    if allergy.item is not None:
        return allergy.item.generic_name, allergy.item.generic_name
    return "", ""  # pragma: no cover - the database requires an allergen


def allergy_chip(allergy: Allergy) -> dict[str, Any]:
    label_ar, label_en = allergy_labels(allergy)
    return {
        "id": allergy.pk,
        "label_ar": label_ar,
        "label_en": label_en,
        "severity": allergy.severity,
    }


def patient_brief(patient: Patient) -> dict[str, Any]:
    return {
        "id": patient.pk,
        "file_no": patient.file_no,
        "full_name_ar": patient.full_name_ar,
        "full_name_en": patient.full_name_en,
        "sex": patient.sex,
        "date_of_birth": patient.date_of_birth,
        "dob_is_estimated": patient.dob_is_estimated,
        "phone": patient.phone,
        "is_incomplete": patient.is_incomplete,
    }


def visit_brief(visit: Visit) -> dict[str, Any]:
    payer = visit.payer
    return {
        "id": visit.pk,
        "number": visit.number,
        "visit_type": visit.visit_type,
        "status": visit.status,
        "created_at": visit.created_at,
        "chief_complaint": visit.chief_complaint,
        "department": department_ref(visit.department),
        "doctor": doctor_ref(visit.doctor),
        "payer": None
        if payer is None
        else {"code": payer.code, "name_ar": payer.name_ar, "name_en": payer.name_en},
    }


# --- the doctor's queue --------------------------------------------------------------------


class QueueEntryOut(Schema):
    id: int
    token_no: int
    priority: int
    status: QueueStatusCode
    queue_date: date
    created_at: datetime
    called_at: datetime | None
    started_at: datetime | None
    done_at: datetime | None
    visit: VisitBriefOut
    patient: ClinicPatientOut
    allergies: list[AllergyChipOut]
    allergies_recorded: bool


class QueueActionIn(Schema):
    action: QueueActionCode


def queue_entry_out(
    entry: QueueEntry, allergies: dict[int, list[Allergy]], recorded: set[int]
) -> dict[str, Any]:
    patient = entry.visit.patient
    return {
        "id": entry.pk,
        "token_no": entry.token_no,
        "priority": entry.priority,
        "status": entry.status,
        "queue_date": entry.queue_date,
        "created_at": entry.created_at,
        "called_at": entry.called_at,
        "started_at": entry.started_at,
        "done_at": entry.done_at,
        "visit": visit_brief(entry.visit),
        "patient": patient_brief(patient),
        "allergies": [allergy_chip(a) for a in allergies.get(patient.pk, [])],
        "allergies_recorded": patient.pk in recorded,
    }


# --- allergies and conditions --------------------------------------------------------------


class DrugClassOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class PatientAllergyOut(Schema):
    id: int
    allergen_type: AllergenTypeCode
    drug_class: DrugClassOut | None
    substance: str
    label_ar: str
    label_en: str
    reaction: str
    severity: SeverityCode
    status: RecordStatusCode
    note: str
    recorded_at: datetime


class AllergyIn(Schema):
    allergen_type: AllergenTypeCode
    drug_class_id: int | None = None
    substance: str = Field("", max_length=200)
    reaction: str = Field("", max_length=300)
    severity: SeverityCode = "moderate"
    note: str = Field("", max_length=1000)


class AllergyPatch(Schema):
    status: RecordStatusCode | None = None
    severity: SeverityCode | None = None
    reaction: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=1000)
    #: Why the allergy is marked entered in error (required then, invariant 4).
    reason: str = Field("", max_length=200)


def allergy_out(allergy: Allergy) -> dict[str, Any]:
    label_ar, label_en = allergy_labels(allergy)
    cls = allergy.drug_class
    return {
        "id": allergy.pk,
        "allergen_type": allergy.allergen_type,
        "drug_class": None
        if cls is None
        else {"id": cls.pk, "code": cls.code, "name_ar": cls.name_ar, "name_en": cls.name_en},
        "substance": allergy.substance,
        "label_ar": label_ar,
        "label_en": label_en,
        "reaction": allergy.reaction,
        "severity": allergy.severity,
        "status": allergy.status,
        "note": allergy.note,
        "recorded_at": allergy.recorded_at,
    }


class Icd10Out(Schema):
    code: str
    title_en: str
    title_ar: str


def icd10_out(code: Icd10Code | None) -> dict[str, Any] | None:
    if code is None:
        return None
    return {"code": code.code, "title_en": code.title_en, "title_ar": code.title_ar}


class ConditionOut(Schema):
    id: int
    icd10: Icd10Out | None
    name: str
    since: date | None
    status: RecordStatusCode
    note: str
    recorded_at: datetime


class ConditionIn(Schema):
    icd10_code: str | None = Field(None, max_length=10)
    name: str = Field("", max_length=200)
    since: date | None = None
    note: str = Field("", max_length=1000)


class ConditionPatch(Schema):
    status: RecordStatusCode | None = None
    note: str | None = Field(None, max_length=1000)
    #: Why the condition is marked entered in error (required then, invariant 4).
    reason: str = Field("", max_length=200)


def condition_out(condition: ChronicCondition) -> dict[str, Any]:
    return {
        "id": condition.pk,
        "icd10": icd10_out(condition.icd10),
        "name": condition.name,
        "since": condition.since,
        "status": condition.status,
        "note": condition.note,
        "recorded_at": condition.recorded_at,
    }


class Icd10SearchParams(Schema):
    q: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(20, ge=1, le=50)


# --- results, summary and history ----------------------------------------------------------


class ResultValueOut(Schema):
    parameter_code: str
    name_ar: str
    name_en: str
    value: str
    unit: str
    reference: str
    flag: str


class ResultOut(Schema):
    """An approved lab result as the doctor sees it (FEATURES 3.7, 9.4)."""

    id: int
    line_id: int
    visit_id: int
    test_code: str
    name_ar: str
    name_en: str
    version_no: int
    amended: bool
    approved_at: datetime | None
    comment: str
    values: list[ResultValueOut]


def _reference(value: Any) -> str:
    if value.reference_text:
        return str(value.reference_text)
    low, high = _dec(value.reference_low), _dec(value.reference_high)
    if low is not None and high is not None:
        return f"{low} - {high}"
    if low is not None:
        return f">= {low}"
    if high is not None:
        return f"<= {high}"
    return ""


def result_out(version: Any) -> dict[str, Any]:
    result_set = version.result_set
    service = result_set.test.service
    values = sorted(
        version.values.all(), key=lambda v: (v.parameter.sort_order, v.parameter.code, v.pk)
    )
    return {
        "id": version.pk,
        "line_id": result_set.service_line_id,
        "visit_id": result_set.service_line.visit_id,
        "test_code": result_set.test.code,
        "name_ar": service.name_ar,
        "name_en": service.name_en,
        "version_no": version.version_no,
        "amended": version.amends_id is not None,
        "approved_at": version.approved_at,
        "comment": version.comment,
        "values": [
            {
                "parameter_code": v.parameter.code,
                "name_ar": v.parameter.name_ar,
                "name_en": v.parameter.name_en,
                "value": v.value_text if v.value_numeric is None else (_dec(v.value_numeric) or ""),
                "unit": v.unit or v.parameter.unit,
                "reference": _reference(v),
                "flag": v.flag,
            }
            for v in values
        ],
    }


class MedicationOut(Schema):
    """A recent drug order (FEATURES 3.1 active medications). No prices."""

    line_id: int
    visit_id: int
    service_code: str
    name_ar: str
    name_en: str
    quantity: str
    dose: str
    frequency_code: str
    duration_days: int | None
    ordered_at: datetime


def medication_out(line: Any) -> dict[str, Any]:
    rx = getattr(line, "prescription", None)
    return {
        "line_id": line.pk,
        "visit_id": line.visit_id,
        "service_code": line.service.code,
        "name_ar": line.service.name_ar,
        "name_en": line.service.name_en,
        "quantity": _dec(line.quantity) or "0",
        "dose": rx.dose if rx else "",
        "frequency_code": rx.frequency_code if rx else "",
        "duration_days": rx.duration_days if rx else None,
        "ordered_at": line.ordered_at,
    }


class PatientSummaryOut(Schema):
    patient: ClinicPatientOut
    allergies: list[PatientAllergyOut]
    allergies_recorded: bool
    conditions: list[ConditionOut]
    active_medications: list[MedicationOut]
    recent_visits: list[VisitBriefOut]
    latest_results: list[ResultOut]


def summary_out(summary: PatientSummary) -> dict[str, Any]:
    return {
        "patient": patient_brief(summary.patient),
        "allergies": [allergy_out(a) for a in summary.allergies],
        "allergies_recorded": summary.allergies_recorded,
        "conditions": [condition_out(c) for c in summary.conditions],
        "active_medications": [medication_out(m) for m in summary.active_medications],
        "recent_visits": [visit_brief(v) for v in summary.recent_visits],
        "latest_results": [result_out(r) for r in summary.latest_results],
    }


class DiagnosisOut(Schema):
    id: int
    icd10: Icd10Out | None
    text: str
    kind: DiagnosisKindCode
    certainty: CertaintyCode
    recorded_by: ClinicUserRefOut | None
    recorded_at: datetime


def diagnosis_out(diagnosis: Any) -> dict[str, Any]:
    return {
        "id": diagnosis.pk,
        "icd10": icd10_out(diagnosis.icd10),
        "text": diagnosis.text,
        "kind": diagnosis.kind,
        "certainty": diagnosis.certainty,
        "recorded_by": user_ref(diagnosis.recorded_by),
        "recorded_at": diagnosis.recorded_at,
    }


class NoteOut(Schema):
    id: int
    visit_id: int
    author: ClinicUserRefOut | None
    complaint: str
    history: str
    examination: str
    assessment: str
    plan: str
    status: NoteStatusCode
    signed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def note_out(note: Any) -> dict[str, Any]:
    return {
        "id": note.pk,
        "visit_id": note.visit_id,
        "author": user_ref(note.author),
        "complaint": note.complaint,
        "history": note.history,
        "examination": note.examination,
        "assessment": note.assessment,
        "plan": note.plan,
        "status": note.status,
        "signed_at": note.signed_at,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


class HistoryLineOut(Schema):
    id: int
    service_code: str
    name_ar: str
    name_en: str
    kind: str
    quantity: str
    status: Literal["requested", "paid", "in_progress", "done", "cancelled"]


class HistoryVisitOut(Schema):
    visit: VisitBriefOut
    diagnoses: list[DiagnosisOut]
    notes: list[NoteOut]
    lines: list[HistoryLineOut]


def history_out(entry: Any) -> dict[str, Any]:
    from apps.orders.services import doctor_status

    return {
        "visit": visit_brief(entry.visit),
        "diagnoses": [diagnosis_out(d) for d in entry.diagnoses],
        "notes": [note_out(n) for n in entry.notes],
        "lines": [
            {
                "id": ln.pk,
                "service_code": ln.service.code,
                "name_ar": ln.service.name_ar,
                "name_en": ln.service.name_en,
                "kind": ln.kind,
                "quantity": _dec(ln.quantity) or "0",
                "status": str(doctor_status(ln)),
            }
            for ln in entry.lines
        ],
    }


class AllergyAlertParams(Schema):
    service_ids: list[int] = Field(default_factory=list, max_length=100)


class AllergyAlertOut(Schema):
    """An active allergy matching a drug being written (same as ALLERGY_CONFLICT details)."""

    service_id: int
    allergy_id: int
    match: Literal["item", "drug_class", "substance"]
    severity: SeverityCode
    allergen: str
    allergen_ar: str


class ResultParams(Schema):
    visit_id: int | None = None
    limit: int = Field(20, ge=1, le=100)


# --- notes, diagnoses, vitals, referrals ---------------------------------------------------


class NoteIn(Schema):
    complaint: str = Field("", max_length=5000)
    history: str = Field("", max_length=5000)
    examination: str = Field("", max_length=5000)
    assessment: str = Field("", max_length=5000)
    plan: str = Field("", max_length=5000)


class NotePatch(Schema):
    complaint: str | None = Field(None, max_length=5000)
    history: str | None = Field(None, max_length=5000)
    examination: str | None = Field(None, max_length=5000)
    assessment: str | None = Field(None, max_length=5000)
    plan: str | None = Field(None, max_length=5000)


class DiagnosisIn(Schema):
    icd10_code: str | None = Field(None, max_length=10)
    text: str = Field("", max_length=300)
    kind: DiagnosisKindCode = "primary"
    certainty: CertaintyCode = "provisional"
    note_id: int | None = None


class VitalsIn(Schema):
    temperature_c: Decimal | None = Field(None, max_digits=4, decimal_places=1)
    pulse_bpm: int | None = None
    respiratory_rate: int | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    spo2_percent: int | None = None
    weight_kg: Decimal | None = Field(None, max_digits=5, decimal_places=2)
    height_cm: Decimal | None = Field(None, max_digits=5, decimal_places=1)
    blood_glucose_mg_dl: int | None = None
    pain_score: int | None = None
    note: str = Field("", max_length=300)


class VitalsOut(Schema):
    id: int
    temperature_c: str | None
    pulse_bpm: int | None
    respiratory_rate: int | None
    bp_systolic: int | None
    bp_diastolic: int | None
    spo2_percent: int | None
    weight_kg: str | None
    height_cm: str | None
    blood_glucose_mg_dl: int | None
    pain_score: int | None
    note: str
    recorded_by: ClinicUserRefOut | None
    recorded_at: datetime


def vitals_out(v: Any) -> dict[str, Any]:
    return {
        "id": v.pk,
        "temperature_c": _dec(v.temperature_c),
        "pulse_bpm": v.pulse_bpm,
        "respiratory_rate": v.respiratory_rate,
        "bp_systolic": v.bp_systolic,
        "bp_diastolic": v.bp_diastolic,
        "spo2_percent": v.spo2_percent,
        "weight_kg": _dec(v.weight_kg),
        "height_cm": _dec(v.height_cm),
        "blood_glucose_mg_dl": v.blood_glucose_mg_dl,
        "pain_score": v.pain_score,
        "note": v.note,
        "recorded_by": user_ref(v.recorded_by),
        "recorded_at": v.recorded_at,
    }


class ReferralIn(Schema):
    kind: ReferralKindCode
    reason: str = Field(..., min_length=1, max_length=2000)
    to_department_id: int | None = None
    to_doctor_id: int | None = None
    external_facility: str = Field("", max_length=200)
    clinical_summary: str = Field("", max_length=5000)
    urgency: UrgencyCode = "routine"


class ReferralOut(Schema):
    id: int
    kind: ReferralKindCode
    to_department: DepartmentRefOut | None
    to_doctor: DoctorRefOut | None
    external_facility: str
    reason: str
    clinical_summary: str
    urgency: UrgencyCode
    status: ReferralStatusCode
    referred_by: ClinicUserRefOut | None
    created_at: datetime
    cancel_reason: str
    cancelled_by: ClinicUserRefOut | None
    cancelled_at: datetime | None


class ReferralCancelIn(Schema):
    reason: str = Field(..., max_length=1000)


class WithdrawRecordIn(Schema):
    """Why a clinical record is withdrawn (invariant 4)."""

    reason: str = Field(..., max_length=200)


def referral_out(r: Any) -> dict[str, Any]:
    return {
        "id": r.pk,
        "kind": r.kind,
        "to_department": department_ref(r.to_department),
        "to_doctor": doctor_ref(r.to_doctor),
        "external_facility": r.external_facility,
        "reason": r.reason,
        "clinical_summary": r.clinical_summary,
        "urgency": r.urgency,
        "status": r.status,
        "referred_by": user_ref(r.referred_by),
        "created_at": r.created_at,
        "cancel_reason": r.cancel_reason,
        "cancelled_by": user_ref(r.cancelled_by),
        "cancelled_at": r.cancelled_at,
    }


class ReferralTargetsOut(Schema):
    departments: list[DepartmentRefOut]
    doctors: list[DoctorRefOut]


class WorkspaceOut(Schema):
    """One visit as its doctor works on it: the header, queue state and clinical record."""

    visit: VisitBriefOut
    patient: ClinicPatientOut
    queue_entry_id: int | None
    queue_status: QueueStatusCode | None
    allergies: list[AllergyChipOut]
    allergies_recorded: bool
    notes: list[NoteOut]
    diagnoses: list[DiagnosisOut]
    vitals: list[VitalsOut]
    referrals: list[ReferralOut]


def workspace_out(ws: VisitWorkspace) -> dict[str, Any]:
    entry = ws.queue_entry
    return {
        "visit": visit_brief(ws.visit),
        "patient": patient_brief(ws.visit.patient),
        "queue_entry_id": entry.pk if entry else None,
        "queue_status": entry.status if entry else None,
        "allergies": [allergy_chip(a) for a in ws.allergies],
        "allergies_recorded": ws.allergies_recorded,
        "notes": [note_out(n) for n in ws.notes],
        "diagnoses": [diagnosis_out(d) for d in ws.diagnoses],
        "vitals": [vitals_out(v) for v in ws.vitals],
        "referrals": [referral_out(r) for r in ws.referrals],
    }


# --- order sets and favorites --------------------------------------------------------------


class OrderSetItemOut(Schema):
    service_id: int
    service_code: str
    kind: str
    name_ar: str
    name_en: str
    quantity: str
    dose: str
    dose_quantity: str | None
    route: RouteCode | None
    frequency_code: str
    duration_days: int | None
    as_needed: bool
    instructions: str


class OrderSetOut(Schema):
    id: int
    name_ar: str
    name_en: str
    personal: bool
    department_id: int | None
    items: list[OrderSetItemOut]


class OrderSetItemIn(Schema):
    service_id: int
    quantity: int = Field(1, ge=1, le=10000)
    dose: str = Field("", max_length=60)
    dose_quantity: Decimal | None = Field(None, gt=0, max_digits=10, decimal_places=3)
    route: RouteCode | None = None
    frequency_code: str = Field("", max_length=20)
    duration_days: int | None = Field(None, ge=1, le=365)
    as_needed: bool = False
    instructions: str = Field("", max_length=300)


class OrderSetIn(Schema):
    name_ar: str = Field("", max_length=150)
    name_en: str = Field("", max_length=150)
    items: list[OrderSetItemIn] = Field(..., min_length=1, max_length=50)


def order_set_out(order_set: Any) -> dict[str, Any]:
    items = [it for it in order_set.items.all() if it.service.active]
    items.sort(key=lambda it: (it.sort_order, it.pk))
    return {
        "id": order_set.pk,
        "name_ar": order_set.name_ar,
        "name_en": order_set.name_en,
        "personal": order_set.owner_id is not None,
        "department_id": order_set.department_id,
        "items": [
            {
                "service_id": it.service_id,
                "service_code": it.service.code,
                "kind": it.service.kind,
                "name_ar": it.service.name_ar,
                "name_en": it.service.name_en,
                "quantity": _dec(it.quantity) or "1",
                "dose": it.dose,
                "dose_quantity": _dec(it.dose_quantity),
                "route": it.route or None,
                "frequency_code": it.frequency_code,
                "duration_days": it.duration_days,
                "as_needed": it.as_needed,
                "instructions": it.instructions,
            }
            for it in items
        ],
    }
