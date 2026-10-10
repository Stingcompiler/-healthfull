/** Named aliases of the lab API schemas (generated from openapi.json, never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type LabUserRef = S["LabUserRefOut"];
export type LabReason = S["LabReasonOut"];
export type LabPatient = S["LabPatientOut"];
export type LabTestRef = S["LabTestRefOut"];
export type LabSample = S["LabSampleOut"];
export type WorklistRow = S["LabWorklistRowOut"];
export type WorklistPage = S["LabWorklistPageOut"];
export type LabResult = S["LabResultOut"];
export type EntryParameter = S["LabEntryParameterOut"];
export type AppliedRange = S["LabAppliedRangeOut"];
export type ResultVersion = S["LabVersionOut"];
export type ResultValue = S["LabValueOut"];
export type LabLine = S["LabLineOut"];
export type LabLabel = S["LabLabelOut"];
export type LabPrint = S["LabPrintOut"];
export type ApprovalRow = S["LabApprovalRowOut"];
export type LabTest = S["LabTestOut"];
export type LabTestListItem = S["LabTestListItemOut"];
export type LabParameter = S["LabParameterOut"];
export type LabRange = S["LabRangeOut"];
export type ServiceOption = S["LabServiceOptionOut"];
export type TatReport = S["LabTatOut"];
export type TatStats = S["LabTatStatsOut"];
export type LabTestIn = S["LabTestIn"];
export type LabTestPatch = S["LabTestPatch"];
export type LabParameterIn = S["LabParameterIn"];
export type LabParameterPatch = S["LabParameterPatch"];
export type LabRangeIn = S["LabRangeIn"];
export type ApproverIn = S["LabApproverIn"];

export type Stage = WorklistRow["stage"];
export type WorklistFilter = NonNullable<S["LabWorklistParams"]["status"]>;
export type Flag = ResultValue["flag"];
export type SampleType = LabTestRef["sample_type"];
export type ValueType = EntryParameter["value_type"];
export type RangeSex = LabRange["sex"];

export const SAMPLE_TYPES: readonly SampleType[] = [
  "whole_blood",
  "serum",
  "plasma",
  "urine",
  "stool",
  "swab",
  "sputum",
  "csf",
  "fluid",
  "other",
];
export const VALUE_TYPES: readonly ValueType[] = ["numeric", "text", "choice", "pos_neg"];
export const RANGE_SEXES: readonly RangeSex[] = ["any", "male", "female"];
