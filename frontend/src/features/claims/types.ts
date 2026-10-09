/** Named aliases of the claims API schemas (generated from openapi.json, never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ClaimName = S["ClaimNameOut"];
export type ClaimPayer = S["ClaimPayerOut"];
export type ClaimUser = S["ClaimUserOut"];
export type ClaimReason = S["ClaimReasonOut"];
export type ClaimPatient = S["ClaimPatientOut"];
export type ClaimOptions = S["ClaimOptionsOut"];
export type ClaimStages = S["ClaimStagesOut"];
export type ClaimAging = S["ClaimAgingOut"];
export type ClaimReceivable = S["ClaimReceivableOut"];
export type ClaimReceivables = S["ClaimReceivablesOut"];
export type ClaimAgingRow = S["ClaimAgingRowOut"];
export type ClaimAgingReport = S["ClaimAgingReportOut"];
export type ClaimAccruedLine = S["ClaimAccruedLineOut"];
export type ClaimAccrued = S["ClaimAccruedOut"];
export type ClaimBuildIn = S["ClaimBuildIn"];
export type ClaimSummary = S["ClaimSummaryOut"];
export type ClaimDetail = S["ClaimDetailOut"];
export type ClaimLine = S["ClaimLineOut"];
export type ClaimPaymentRef = S["ClaimPaymentRefOut"];
export type ClaimResponseIn = S["ClaimResponseIn"];
export type ClaimResolveIn = S["ClaimResolveIn"];
export type ClaimShortfallIn = S["ClaimShortfallIn"];
export type ClaimPrint = S["ClaimPrintOut"];
export type ClaimPayable = S["ClaimPayableOut"];
export type ClaimPayerPaymentIn = S["ClaimPayerPaymentIn"];
export type ClaimPayerPayment = S["ClaimPayerPaymentOut"];

export type ClaimStatus = ClaimSummary["status"];
export type ClaimLineStage = ClaimLine["stage"];
export type ClaimOutcome = ClaimResponseIn["outcome"];
export type PayerPaymentMethod = ClaimPayerPayment["method"];
export type PayerPaymentStanding = ClaimPayerPayment["standing"];

export const CLAIM_STATUSES: readonly ClaimStatus[] = ["draft", "submitted", "responded", "closed", "void"];
export const AGING_FIELDS = ["days_0_30", "days_31_60", "days_61_90", "days_over_90"] as const;
export type AgingField = (typeof AGING_FIELDS)[number];
