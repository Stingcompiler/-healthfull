/**
 * Administration API shapes, straight from the generated OpenAPI schema
 * (`make api`). Nothing here is hand-written.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type UserOut = S["UserOut"];
export type UserIn = S["UserIn"];
export type UserPatch = S["UserPatch"];
export type RoleOut = S["RoleOut"];
export type PermissionMatrixOut = S["PermissionMatrixOut"];
export type PermissionRowOut = S["PermissionRowOut"];
export type MatrixChangeIn = S["MatrixChangeIn"];
export type CenterProfileOut = S["CenterProfileOut"];
export type CenterProfileIn = S["CenterProfileIn"];
export type PolicyOut = S["PolicyOut"];
export type PolicyIn = S["PolicyIn"];
export type DepartmentOut = S["DepartmentOut"];
export type DepartmentIn = S["DepartmentIn"];
export type DepartmentPatch = S["DepartmentPatch"];
export type RoomOut = S["RoomOut"];
export type RoomIn = S["RoomIn"];
export type RoomPatch = S["RoomPatch"];
export type DoctorOut = S["DoctorOut"];
export type DoctorIn = S["DoctorIn"];
export type DoctorCandidateOut = S["DoctorCandidateOut"];
export type DoctorPatch = S["DoctorPatch"];
export type ScheduleSessionIn = S["ScheduleSessionIn"];
export type ReasonCodeOut = S["ReasonCodeOut"];
export type ReasonCodeIn = S["ReasonCodeIn"];
export type ReasonCodePatch = S["ReasonCodePatch"];
export type SequencesOut = S["SequencesOut"];
export type PrintTemplateOut = S["PrintTemplateOut"];
export type PrintTemplateIn = S["PrintTemplateIn"];
export type ServiceOut = S["ServiceOut"];
export type ServiceIn = S["ServiceIn"];
export type ServicePatch = S["ServicePatch"];
export type CategoryOut = S["CategoryOut"];
export type PriceListOut = S["PriceListOut"];
export type PriceListIn = S["PriceListIn"];
export type VersionOut = S["VersionOut"];
export type VersionIn = S["VersionIn"];
export type PriceItemOut = S["PriceItemOut"];
export type PriceChangeIn = S["PriceChangeIn"];
export type BulkUpdateIn = S["BulkUpdateIn"];
export type BulkPreviewOut = S["BulkPreviewOut"];
export type PayerListOut = S["PayerListOut"];
export type PayerOut = S["PayerOut"];
export type PayerIn = S["PayerIn"];
export type PayerPatch = S["PayerPatch"];
export type CoverageRuleOut = S["CoverageRuleOut"];
export type CoverageRuleIn = S["CoverageRuleIn"];
export type CoverageRulePatch = S["CoverageRulePatch"];
export type ExclusionOut = S["ExclusionOut"];
export type ExclusionIn = S["ExclusionIn"];
export type CoveragePreviewIn = S["CoveragePreviewIn"];
export type CoveragePreviewOut = S["CoveragePreviewOut"];

export type RoleCode = UserIn["roles"][number];
export type ServiceKind = ServiceOut["kind"];
export type ReasonCategory = ReasonCodeIn["category"];
export type RuleKind = CoverageRuleOut["rule_kind"];
export type PayerKind = PayerOut["kind"];
export type ClaimPeriod = PayerOut["claim_period"];

export const SERVICE_KINDS: readonly ServiceKind[] = ["consultation", "lab", "procedure", "drug", "consumable", "bed"];
export const RULE_KINDS: readonly RuleKind[] = ["percentage", "copay", "ceiling"];
export const PAYER_KINDS: readonly PayerKind[] = ["insurance", "company", "government", "ngo", "other"];
export const CLAIM_PERIODS: readonly ClaimPeriod[] = ["weekly", "biweekly", "monthly", "quarterly"];
export const REASON_CATEGORIES: readonly ReasonCategory[] = [
  "line_cancel",
  "visit_cancel",
  "discount",
  "refund",
  "credit_note",
  "stock_adjust",
  "variance",
  "override",
  "writeoff",
  "perform_first",
  "transfer_reject",
  "result_amend",
  "sample_reject",
];
