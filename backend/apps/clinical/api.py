"""``/api/clinical``: the doctor's worklist and workspace (FEATURES 2.3, 3.1-3.4, 3.6, 3.9).

Queue (call next, call, start, complete), patient summary and history, approved results,
allergy and chronic condition registry, ICD-10 lookup, clinical notes, diagnoses, vitals,
referrals, order sets and favorites. Routers stay thin: each operation checks one
permission, looks up the rows it names, calls one function of ``apps.clinical.services`` and
builds its answer with ``apps.clinical.schemas``. Nothing here carries a price (FEATURES 3.8).
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
from apps.clinical import schemas as s
from apps.clinical import services
from apps.clinical.models import (
    Allergy,
    ChronicCondition,
    ClinicalNote,
    Diagnosis,
    OrderSet,
    Referral,
)
from apps.core.models import Department, DoctorProfile, User
from apps.patients.models import Patient
from apps.visits.models import QueueEntry, Visit

clinical_router = Router(tags=["clinical"])
add_ping(clinical_router, "clinical")

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("clinical.view")
    return user


# --- the doctor's queue ---------------------------------------------------------------------


def _worklist_out(user: User) -> list[dict[str, Any]]:
    wl = services.worklist(user)
    return [s.queue_entry_out(e, wl.allergies, wl.recorded) for e in wl.entries]


@clinical_router.get(
    "/worklist",
    response={200: list[s.QueueEntryOut], **_READ},
    operation_id="clinical_list_worklist",
    summary="Today's queue of the logged-in doctor: ready patients in serving order",
    description=(
        "Paid (or authorized) visits assigned to the doctor or unassigned in the doctor's "
        "department: waiting, called and with the doctor first, then the ones seen today. "
        "Empty for a user without a doctor profile."
    ),
)
@require_perm("clinical.view")
def list_worklist(request: HttpRequest) -> Any:
    return _worklist_out(_actor(request))


@clinical_router.post(
    "/worklist/call-next",
    response={200: s.QueueEntryOut, **_WRITE},
    operation_id="clinical_call_next",
    summary="Call the first waiting patient of the doctor's queue",
    description="409 DOCTOR_PROFILE_REQUIRED, QUEUE_EMPTY.",
)
@require_perm("visits.manage_queue")
def call_next(request: HttpRequest) -> Any:
    actor = _actor(request)
    entry = services.call_next(actor)
    return _entry_out(entry)


def _entry_out(entry: QueueEntry) -> dict[str, Any]:
    view = services.queue_entry_view(entry)
    return s.queue_entry_out(view.entries[0], view.allergies, view.recorded)


@clinical_router.post(
    "/worklist/{entry_id}/action",
    response={200: s.QueueEntryOut, **_WRITE},
    operation_id="clinical_queue_action",
    summary="Call, start, complete, mark no-show or requeue one of the doctor's patients",
    description=(
        "Completing performs the consultation line and needs visits.finish_consultation "
        "(403 otherwise); the visit stays open for its orders. 409 DOCTOR_PROFILE_REQUIRED, "
        "QUEUE_OTHER_DOCTOR, QUEUE_TRANSITION_INVALID, QUEUE_NOT_READY."
    ),
)
@require_perm("visits.manage_queue")
def queue_action(request: HttpRequest, entry_id: int, payload: s.QueueActionIn) -> Any:
    entry = get_object_or_404(QueueEntry, pk=entry_id)
    moved = services.queue_action(entry, payload.action, actor=_actor(request))
    return _entry_out(moved)


# --- visit workspace ------------------------------------------------------------------------


@clinical_router.get(
    "/visits/{visit_id}/workspace",
    response={200: s.WorkspaceOut, **_READ},
    operation_id="clinical_get_workspace",
    summary="A visit as its doctor works on it: header, queue state, notes, diagnoses, "
    "vitals and referrals",
)
@require_perm("clinical.view")
def get_workspace(request: HttpRequest, visit_id: int) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    return s.workspace_out(services.visit_workspace(visit))


# --- patient summary, history, results ------------------------------------------------------


@clinical_router.get(
    "/patients/{patient_id}/summary",
    response={200: s.PatientSummaryOut, **_READ},
    operation_id="clinical_get_patient_summary",
    summary="What a doctor sees on opening a file: allergies, chronic conditions, active "
    "medications, last 5 visits, latest approved results",
)
@require_perm("clinical.view")
def get_patient_summary(request: HttpRequest, patient_id: int) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    return s.summary_out(services.patient_summary(patient))


@clinical_router.get(
    "/patients/{patient_id}/history",
    response={200: list[s.HistoryVisitOut], **_READ},
    operation_id="clinical_list_history",
    summary="The person's visits, newest first, with diagnoses, notes and orders",
)
@require_perm("clinical.view")
def list_history(request: HttpRequest, patient_id: int) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    return [s.history_out(h) for h in services.patient_history(patient)]


@clinical_router.get(
    "/patients/{patient_id}/results",
    response={200: list[s.ResultOut], **_READ},
    operation_id="clinical_list_results",
    summary="Approved lab results of the person (or of one visit), newest first",
    description="Only approved results show; drafts never reach a doctor (FEATURES 9.4).",
)
@require_perm("clinical.view")
def list_results(request: HttpRequest, patient_id: int, params: Query[s.ResultParams]) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    visit = None
    if params.visit_id is not None:
        visit = get_object_or_404(Visit, pk=params.visit_id)
    rows = services.approved_results(patient, visit=visit, limit=params.limit)
    return [s.result_out(r) for r in rows]


# --- allergies and chronic conditions -------------------------------------------------------


@clinical_router.get(
    "/drug-classes",
    response={200: list[s.DrugClassOut], **_READ},
    operation_id="clinical_list_drug_classes",
    summary="Active drug classes, for recording a class allergy",
)
@require_perm("clinical.view")
def list_drug_classes(request: HttpRequest) -> Any:
    return list(services.drug_classes())


@clinical_router.get(
    "/patients/{patient_id}/allergies",
    response={200: list[s.PatientAllergyOut], **_READ},
    operation_id="clinical_list_allergies",
    summary="The person's allergy registry: active first, then resolved",
)
@require_perm("clinical.view")
def list_allergies(request: HttpRequest, patient_id: int) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    return [s.allergy_out(a) for a in services.allergy_registry(patient)]


@clinical_router.get(
    "/patients/{patient_id}/allergy-alerts",
    response={200: list[s.AllergyAlertOut], **_READ},
    operation_id="clinical_list_allergy_alerts",
    summary="Active allergies matching drugs of an order being written (a warning only)",
    description=(
        "service_ids may repeat (up to 100). Placing the order still refuses a match with 409 "
        "ALLERGY_CONFLICT unless an override reason is given."
    ),
)
@require_perm("clinical.view")
def list_allergy_alerts(
    request: HttpRequest, patient_id: int, params: Query[s.AllergyAlertParams]
) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    return [a.as_dict() for a in services.allergy_alerts_for(patient, params.service_ids)]


@clinical_router.post(
    "/patients/{patient_id}/allergies",
    response={201: s.PatientAllergyOut, **_WRITE},
    operation_id="clinical_create_allergy",
    summary="Record an allergy (drug, drug class, food, environmental or other)",
    description="409 DRUG_CLASS_REQUIRED, DRUG_CLASS_INACTIVE, ALLERGEN_REQUIRED.",
)
@require_perm("clinical.manage_allergies")
def create_allergy(request: HttpRequest, patient_id: int, payload: s.AllergyIn) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    allergy = services.record_allergy(
        patient,
        actor=_actor(request),
        allergen_type=payload.allergen_type,
        drug_class_id=payload.drug_class_id,
        substance=payload.substance,
        reaction=payload.reaction,
        severity=payload.severity,
        note=payload.note,
    )
    return Status(201, s.allergy_out(allergy))


@clinical_router.patch(
    "/allergies/{allergy_id}",
    response={200: s.PatientAllergyOut, **_WRITE},
    operation_id="clinical_update_allergy",
    summary="Resolve an allergy, mark it entered in error, or change severity, reaction, note",
    description=(
        "The allergen never changes; a wrong entry is marked entered_in_error, which needs a "
        "reason (409 REASON_REQUIRED) kept with who and when in the audit history."
    ),
)
@require_perm("clinical.manage_allergies")
def update_allergy(request: HttpRequest, allergy_id: int, payload: s.AllergyPatch) -> Any:
    allergy = get_object_or_404(Allergy, pk=allergy_id)
    updated = services.update_allergy(
        allergy,
        actor=_actor(request),
        status=payload.status,
        severity=payload.severity,
        reaction=payload.reaction,
        note=payload.note,
        reason=payload.reason,
    )
    return s.allergy_out(Allergy.objects.select_related("drug_class", "item").get(pk=updated.pk))


@clinical_router.get(
    "/patients/{patient_id}/conditions",
    response={200: list[s.ConditionOut], **_READ},
    operation_id="clinical_list_conditions",
    summary="The person's chronic conditions: active first, then resolved",
)
@require_perm("clinical.view")
def list_conditions(request: HttpRequest, patient_id: int) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    return [s.condition_out(c) for c in services.condition_registry(patient)]


@clinical_router.post(
    "/patients/{patient_id}/conditions",
    response={201: s.ConditionOut, **_WRITE},
    operation_id="clinical_create_condition",
    summary="Record a chronic condition by ICD-10 code, by name, or both",
    description="409 CONDITION_NAME_REQUIRED, ICD10_UNKNOWN.",
)
@require_perm("clinical.manage_conditions")
def create_condition(request: HttpRequest, patient_id: int, payload: s.ConditionIn) -> Any:
    patient = get_object_or_404(Patient, pk=patient_id)
    condition = services.record_condition(
        patient,
        actor=_actor(request),
        icd10_code=payload.icd10_code,
        name=payload.name,
        since=payload.since,
        note=payload.note,
    )
    return Status(201, s.condition_out(condition))


@clinical_router.patch(
    "/conditions/{condition_id}",
    response={200: s.ConditionOut, **_WRITE},
    operation_id="clinical_update_condition",
    summary="Resolve a chronic condition, mark it entered in error, or change its note",
    description="Marking it entered_in_error needs a reason (409 REASON_REQUIRED).",
)
@require_perm("clinical.manage_conditions")
def update_condition(request: HttpRequest, condition_id: int, payload: s.ConditionPatch) -> Any:
    condition = get_object_or_404(ChronicCondition, pk=condition_id)
    updated = services.update_condition(
        condition,
        actor=_actor(request),
        status=payload.status,
        note=payload.note,
        reason=payload.reason,
    )
    return s.condition_out(ChronicCondition.objects.select_related("icd10").get(pk=updated.pk))


# --- ICD-10, notes, diagnoses ---------------------------------------------------------------


@clinical_router.get(
    "/icd10",
    response={200: list[s.Icd10Out], **_READ},
    operation_id="clinical_search_icd10",
    summary="ICD-10 lookup by code prefix (dot optional) or by words of the title (ar/en)",
)
@require_perm("clinical.view")
def search_icd10(request: HttpRequest, params: Query[s.Icd10SearchParams]) -> Any:
    return services.search_icd10(params.q, limit=params.limit)


@clinical_router.post(
    "/visits/{visit_id}/notes",
    response={201: s.NoteOut, **_WRITE},
    operation_id="clinical_create_note",
    summary="Start a draft clinical note: complaint, history, examination, assessment, plan",
    description="409 VISIT_NOT_OPEN.",
)
@require_perm("clinical.write_note")
def create_note(request: HttpRequest, visit_id: int, payload: s.NoteIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    note = services.save_note(visit, actor=_actor(request), **payload.dict())
    return Status(201, s.note_out(note))


@clinical_router.patch(
    "/notes/{note_id}",
    response={200: s.NoteOut, **_WRITE},
    operation_id="clinical_update_note",
    summary="Change the actor's own draft note",
    description="409 NOTE_SIGNED (write a new note), NOTE_NOT_AUTHOR.",
)
@require_perm("clinical.write_note")
def update_note(request: HttpRequest, note_id: int, payload: s.NotePatch) -> Any:
    note = get_object_or_404(ClinicalNote, pk=note_id)
    fields = {k: v for k, v in payload.dict().items() if v is not None}
    saved = services.save_note(note.visit, actor=_actor(request), note=note, **fields)
    return s.note_out(saved)


@clinical_router.post(
    "/notes/{note_id}/sign",
    response={200: s.NoteOut, **_WRITE},
    operation_id="clinical_sign_note",
    summary="Sign a draft note; a signed note never changes",
    description="409 NOTE_SIGNED, NOTE_NOT_AUTHOR, NOTE_EMPTY.",
)
@require_perm("clinical.write_note")
def sign_note(request: HttpRequest, note_id: int) -> Any:
    note = get_object_or_404(ClinicalNote, pk=note_id)
    return s.note_out(services.sign_note(note, actor=_actor(request)))


@clinical_router.post(
    "/visits/{visit_id}/diagnoses",
    response={201: s.DiagnosisOut, **_WRITE},
    operation_id="clinical_create_diagnosis",
    summary="Record a diagnosis: an ICD-10 code, free text, or both",
    description="409 ICD10_UNKNOWN, DIAGNOSIS_REQUIRED, NOTE_NOT_ON_VISIT, VISIT_NOT_OPEN.",
)
@require_perm("clinical.record_diagnosis")
def create_diagnosis(request: HttpRequest, visit_id: int, payload: s.DiagnosisIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    note = None
    if payload.note_id is not None:
        note = get_object_or_404(ClinicalNote, pk=payload.note_id)
    diagnosis = services.add_diagnosis(
        visit,
        actor=_actor(request),
        icd10_code=payload.icd10_code,
        text=payload.text,
        kind=payload.kind,
        certainty=payload.certainty,
        note=note,
    )
    return Status(201, s.diagnosis_out(diagnosis))


@clinical_router.delete(
    "/diagnoses/{diagnosis_id}",
    response={204: None, **_WRITE},
    operation_id="clinical_delete_diagnosis",
    summary="Withdraw a diagnosis recorded in error (its author, while the visit is open)",
    description=(
        "The body states why (409 REASON_REQUIRED); the audit history keeps the row with who, "
        "when and why. 409 VISIT_NOT_OPEN, DIAGNOSIS_NOT_AUTHOR."
    ),
)
@require_perm("clinical.record_diagnosis")
def delete_diagnosis(
    request: HttpRequest, diagnosis_id: int, payload: s.WithdrawRecordIn
) -> Status[None]:
    diagnosis = get_object_or_404(Diagnosis, pk=diagnosis_id)
    services.remove_diagnosis(diagnosis, actor=_actor(request), reason=payload.reason)
    return Status(204, None)


# --- vitals and referrals -------------------------------------------------------------------


@clinical_router.post(
    "/visits/{visit_id}/vitals",
    response={201: s.VitalsOut, **_WRITE},
    operation_id="clinical_create_vitals",
    summary="Record vital signs (every measure optional, at least one)",
    description="409 VITALS_EMPTY, VITALS_OUT_OF_RANGE, BP_INCOMPLETE, VISIT_NOT_OPEN.",
)
@require_perm("clinical.record_vitals")
def create_vitals(request: HttpRequest, visit_id: int, payload: s.VitalsIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    data = payload.dict()
    note = data.pop("note")
    vitals = services.record_vitals(visit, actor=_actor(request), note=note, **data)
    return Status(201, s.vitals_out(vitals))


@clinical_router.get(
    "/referral-targets",
    response={200: s.ReferralTargetsOut, **_READ},
    operation_id="clinical_get_referral_targets",
    summary="Departments and doctors a patient can be referred to inside the center",
)
@require_perm("clinical.refer")
def get_referral_targets(request: HttpRequest) -> Any:
    targets = services.referral_targets()
    return {
        "departments": [s.department_ref(d) for d in targets.departments],
        "doctors": [s.doctor_ref(d) for d in targets.doctors],
    }


@clinical_router.post(
    "/visits/{visit_id}/referrals",
    response={201: s.ReferralOut, **_WRITE},
    operation_id="clinical_create_referral",
    summary="Referral note to another department or an external facility",
    description="409 DEPARTMENT_REQUIRED, FACILITY_REQUIRED, REASON_REQUIRED, VISIT_NOT_OPEN.",
)
@require_perm("clinical.refer")
def create_referral(request: HttpRequest, visit_id: int, payload: s.ReferralIn) -> Any:
    visit = get_object_or_404(Visit, pk=visit_id)
    department = None
    if payload.to_department_id is not None:
        department = get_object_or_404(Department, pk=payload.to_department_id)
    doctor = None
    if payload.to_doctor_id is not None:
        doctor = get_object_or_404(DoctorProfile, pk=payload.to_doctor_id)
    referral = services.create_referral(
        visit,
        actor=_actor(request),
        kind=payload.kind,
        reason=payload.reason,
        to_department=department,
        to_doctor=doctor,
        external_facility=payload.external_facility,
        clinical_summary=payload.clinical_summary,
        urgency=payload.urgency,
    )
    return Status(201, s.referral_out(referral))


@clinical_router.post(
    "/referrals/{referral_id}/cancel",
    response={200: s.ReferralOut, **_WRITE},
    operation_id="clinical_cancel_referral",
    summary="Cancel an issued referral with a reason (its author, while the visit is open)",
    description=(
        "The reason, who and when are stored on the referral. 409 REASON_REQUIRED, "
        "REFERRAL_CLOSED, REFERRAL_NOT_AUTHOR, VISIT_NOT_OPEN."
    ),
)
@require_perm("clinical.refer")
def cancel_referral(request: HttpRequest, referral_id: int, payload: s.ReferralCancelIn) -> Any:
    referral = get_object_or_404(Referral, pk=referral_id)
    cancelled = services.cancel_referral(referral, actor=_actor(request), reason=payload.reason)
    return s.referral_out(cancelled)


# --- order sets and favorites ---------------------------------------------------------------


@clinical_router.get(
    "/order-sets",
    response={200: list[s.OrderSetOut], **_READ},
    operation_id="clinical_list_order_sets",
    summary="Shared order sets of the doctor's department and the doctor's own favorites",
)
@require_perm("clinical.view")
def list_order_sets(request: HttpRequest) -> Any:
    return [s.order_set_out(o) for o in services.doctor_order_sets(_actor(request))]


@clinical_router.post(
    "/order-sets",
    response={201: s.OrderSetOut, **_WRITE},
    operation_id="clinical_create_favorite",
    summary="Save a group of orders as one of the doctor's favorites",
    description="409 NAME_REQUIRED, ORDER_EMPTY, SERVICE_INACTIVE.",
)
@require_perm("clinical.manage_order_sets")
def create_favorite(request: HttpRequest, payload: s.OrderSetIn) -> Any:
    order_set = services.create_favorite(
        name_ar=payload.name_ar,
        name_en=payload.name_en,
        items=[it.dict() for it in payload.items],
        actor=_actor(request),
    )
    return Status(201, s.order_set_out(order_set))


@clinical_router.delete(
    "/order-sets/{order_set_id}",
    response={204: None, **_WRITE},
    operation_id="clinical_delete_favorite",
    summary="Remove one of the doctor's favorites",
    description="409 ORDER_SET_NOT_OWNER, ORDER_SET_INACTIVE.",
)
@require_perm("clinical.manage_order_sets")
def delete_favorite(request: HttpRequest, order_set_id: int) -> Status[None]:
    order_set = get_object_or_404(OrderSet, pk=order_set_id)
    services.deactivate_order_set(order_set, actor=_actor(request))
    return Status(204, None)
