/** Display helpers for the clinic screens: shaping API rows for shared components. No rules. */
import { useTranslation } from "react-i18next";

import type { PatientCardPatient } from "@/components/PatientCard";
import type { ServiceLineState } from "@/components/status";
import { isApiError } from "@/lib/api/errors";
import { pickName } from "@/lib/names";
import type { Language } from "@/lib/preferences";

import type { AllergyAlert, AllergyChip, DoctorStatus, PatientBrief, VisitBrief } from "./types";

interface Labelled {
  label_ar: string;
  label_en: string;
}

export function allergyLabel(allergy: Labelled, language: Language): string {
  return pickName({ ar: allergy.label_ar, en: allergy.label_en }, language);
}

/** PatientCard props: allergies null = never recorded, [] = none known. */
export function toPatientCard(
  patient: PatientBrief,
  allergies: readonly AllergyChip[] | readonly Labelled[],
  recorded: boolean,
  payer: VisitBrief["payer"] | undefined,
  language: Language,
): PatientCardPatient {
  return {
    nameAr: patient.full_name_ar || patient.full_name_en,
    nameEn: patient.full_name_en || null,
    fileNo: patient.file_no,
    sex: patient.sex,
    birthDate: patient.date_of_birth ?? null,
    phone: patient.phone || null,
    allergies: recorded || allergies.length > 0 ? allergies.map((a) => allergyLabel(a, language)) : null,
    coverage: payer ? { nameAr: payer.name_ar, nameEn: payer.name_en } : null,
    incomplete: patient.is_incomplete,
  };
}

export function patientName(patient: PatientBrief, language: Language): string {
  return pickName({ ar: patient.full_name_ar, en: patient.full_name_en }, language);
}

/**
 * The shared service-line badge for a doctor status. "In progress" has no badge of its own in
 * the shared palette: it is shown as paid plus an "in progress" marker (see OrderLineCard).
 */
export function lineBadgeState(status: DoctorStatus): ServiceLineState {
  switch (status) {
    case "requested":
      return "requested";
    case "paid":
    case "in_progress":
      return "paid";
    case "done":
      return "performed";
    case "cancelled":
      return "cancelled";
  }
}

/** The allergy matches of a 409 ALLERGY_CONFLICT, or null for any other error. */
export function allergyConflict(error: unknown): AllergyAlert[] | null {
  if (!isApiError(error) || error.code !== "ALLERGY_CONFLICT") return null;
  const alerts = error.details.alerts;
  if (!Array.isArray(alerts)) return [];
  return alerts.filter(
    (a): a is AllergyAlert => typeof a === "object" && a !== null && "service_id" in a && "allergen" in a,
  );
}

/**
 * Prescription frequencies for display: the words of a known code in the current language
 * ("three times a day", "ثلاث مرات يومياً"); unknown codes show as they are.
 */
export function useFrequencyText(): (code: string) => string {
  const { t, i18n } = useTranslation("clinic");
  return (code: string) => {
    if (!code) return "";
    if (!i18n.exists(`clinic:frequency.${code}`)) return code;
    return t(`frequency.${code}` as "frequency.OD");
  };
}
