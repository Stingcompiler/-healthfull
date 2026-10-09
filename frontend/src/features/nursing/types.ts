/** Nursing API shapes, all from the generated OpenAPI schema (never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ProcedureLine = S["ProcedureLineOut"];
export type NursingVisit = S["NursingVisitOut"];
export type NursingChart = S["NursingChartOut"];
export type NursingNote = S["NursingNoteOut"];
export type NursingNoteInput = S["NursingNoteIn"];
export type NursingNoteKind = NursingNoteInput["kind"];
export type NursingProcedure = S["NursingProcedureOut"];
export type NursingAdmission = S["NursingAdmissionOut"];
export type ClinicPatient = S["ClinicPatientOut"];
export type AllergyChip = S["AllergyChipOut"];
export type Vitals = S["VitalsOut"];
export type VitalsInput = S["VitalsIn"];
export type BedBoard = S["InpatientBoardOut"];
export type Ward = S["InpatientWardOut"];
export type Bed = S["InpatientBedOut"];
export type BedStatus = Bed["status"];
export type Occupant = S["InpatientOccupantOut"];
export type Admission = S["InpatientAdmissionOut"];
export type AdmitInput = S["InpatientAdmitIn"];
export type PatientRow = S["PatientListOut"];
export type VisitRow = S["VisitOut"];
export type VisitDoctor = S["VisitDoctorOut"];
