/** Clinic API shapes, all from the generated OpenAPI schema (never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type QueueEntry = S["QueueEntryOut"];
export type QueueAction = S["QueueActionIn"]["action"];
export type Workspace = S["WorkspaceOut"];
export type PatientBrief = S["ClinicPatientOut"];
export type VisitBrief = S["VisitBriefOut"];
export type PatientSummary = S["PatientSummaryOut"];
export type Allergy = S["PatientAllergyOut"];
export type AllergyInput = S["AllergyIn"];
export type AllergyPatch = S["AllergyPatch"];
export type AllergyChip = S["AllergyChipOut"];
export type Condition = S["ConditionOut"];
export type ConditionInput = S["ConditionIn"];
export type ConditionPatch = S["ConditionPatch"];
export type DrugClass = S["DrugClassOut"];
export type Icd10 = S["Icd10Out"];
export type Note = S["NoteOut"];
export type NoteInput = S["NoteIn"];
export type NotePatch = S["NotePatch"];
export type Diagnosis = S["DiagnosisOut"];
export type DiagnosisInput = S["DiagnosisIn"];
export type Vitals = S["VitalsOut"];
export type VitalsInput = S["VitalsIn"];
export type Referral = S["ReferralOut"];
export type ReferralInput = S["ReferralIn"];
export type ReferralTargets = S["ReferralTargetsOut"];
export type HistoryVisit = S["HistoryVisitOut"];
export type LabResult = S["ResultOut"];
export type OrderSet = S["OrderSetOut"];
export type OrderSetInput = S["OrderSetIn"];
export type OrderableService = S["OrderableServiceOut"];
export type OrderableKind = OrderableService["kind"];
export type Frequency = S["FrequencyOut"];
export type PrescriptionPreview = S["PrescriptionPreviewOut"];
export type PrescriptionPreviewInput = S["PrescriptionPreviewIn"];
export type OrderInput = S["OrderIn"];
export type EstimateInput = S["EstimateIn"];
export type Estimate = S["EstimateOut"];
export type OrderItemInput = S["OrderItemIn"];
export type PrescriptionInput = S["PrescriptionIn"];
export type DoctorLine = S["DoctorLineOut"];
export type DoctorStatus = DoctorLine["status"];
export type WithdrawReason = S["WithdrawReasonOut"];
export type Route = S["PrescriptionIn"]["route"];

/** One allergy match in a 409 ALLERGY_CONFLICT (details.alerts). */
export interface AllergyAlert {
  service_id: number;
  allergy_id: number;
  match: string;
  severity: string;
  allergen: string;
  allergen_ar: string;
}
