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
export type CenterPageOut = S["CenterPageOut"];
export type CenterPageIn = S["CenterPageIn"];
export type AnnouncementOut = S["AnnouncementOut"];
export type CenterMediaOut = S["CenterMediaOut"];
export type CenterMediaPatch = S["CenterMediaPatch"];
export type MediaKind = CenterMediaOut["kind"];
export type CenterFaqOut = S["CenterFaqOut"];
export type CenterFaqIn = S["CenterFaqIn"];
export type CenterFaqPatch = S["CenterFaqPatch"];
export type TestimonialOut = S["TestimonialOut"];
export type TestimonialIn = S["TestimonialIn"];
export type TestimonialPatch = S["TestimonialPatch"];
export type DoctorSiteProfileOut = S["DoctorSiteProfileOut"];
export type DoctorSiteProfilePatch = S["DoctorSiteProfilePatch"];
export type SitePayerOut = S["SitePayerOut"];
export type SiteServiceOut = S["SiteServiceOut"];
export type AnnouncementIn = S["AnnouncementIn"];
export type AnnouncementPatch = S["AnnouncementPatch"];
export type PolicyOut = S["PolicyOut"];
export type PolicyIn = S["PolicyIn"];
export type PublicSiteSettingsOut = S["PublicSiteSettingsOut"];
export type PublicSiteSettingsIn = S["PublicSiteSettingsIn"];
export type DepartmentOut = S["DepartmentOut"];
export type DepartmentIn = S["DepartmentIn"];
export type DepartmentPatch = S["DepartmentPatch"];
export type BankOut = S["BankOut"];
export type BankIn = S["BankIn"];
export type BankPatch = S["BankPatch"];
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
// A record keyed by every category the API accepts, so a category added on the backend fails the
// type check here until the admin screen lists it (and its label is added to admin.json).
const REASON_CATEGORY_SET: Record<ReasonCategory, true> = {
  line_cancel: true,
  visit_cancel: true,
  discount: true,
  refund: true,
  credit_note: true,
  stock_adjust: true,
  variance: true,
  override: true,
  writeoff: true,
  perform_first: true,
  transfer_reject: true,
  result_amend: true,
  sample_reject: true,
  patient_merge: true,
  appointment_cancel: true,
  admission_cancel: true,
};
export const REASON_CATEGORIES = Object.keys(REASON_CATEGORY_SET) as ReasonCategory[];
