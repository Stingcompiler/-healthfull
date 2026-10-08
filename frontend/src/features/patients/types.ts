/** API shapes of /api/patients, named after the generated OpenAPI schemas (`make api`). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type PatientListItem = S["PatientListOut"];
export type PatientFile = S["PatientOut"];
export type PatientProfile = S["PatientProfileOut"];
export type PatientBrief = S["PatientBriefOut"];
export type PatientInput = S["PatientIn"];
export type PatientPatch = S["PatientPatch"];
export type EmergencyInput = S["EmergencyIn"];
export type DuplicateCandidate = S["DuplicateOut"];
export type DuplicateQuery = S["DuplicateParams"];
export type MergeInput = S["MergeIn"];
export type MergeRecord = S["MergeOut"];
export type Payer = S["PayerOut"];
export type Coverage = S["CoverageOut"];
export type CoverageInput = S["CoverageIn"];
export type CoveragePatch = S["CoveragePatch"];
export type Balance = S["BalanceOut"];
export type PatientPage = S["Page_PatientListOut_"];

export type MergeReason = S["MergeReasonOut"];

export type Sex = PatientListItem["sex"];

export type ImportJob = S["ImportJobOut"];
export type ImportRow = S["ImportRowOut"];
