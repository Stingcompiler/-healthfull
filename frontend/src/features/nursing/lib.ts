/** Display helpers for the nursing screens: shaping API rows for shared components. No rules. */
import type { PatientCardPatient } from "@/components/PatientCard";
import { pickName } from "@/lib/names";
import type { Language } from "@/lib/preferences";

interface PatientLike {
  file_no: string;
  full_name_ar: string;
  full_name_en: string;
  sex: "male" | "female" | "unknown";
  date_of_birth?: string | null;
  phone: string;
  is_incomplete: boolean;
}

interface Labelled {
  label_ar: string;
  label_en: string;
}

interface Named {
  name_ar: string;
  name_en: string;
}

export function nameOf(row: Named, language: Language): string {
  return pickName({ ar: row.name_ar, en: row.name_en }, language);
}

export function patientName(patient: PatientLike, language: Language): string {
  return pickName({ ar: patient.full_name_ar, en: patient.full_name_en }, language);
}

/**
 * PatientCard props. `allergies` undefined hides the allergy badge; an array shows the
 * active allergies (empty: none known on this file).
 */
export function toPatientCard(
  patient: PatientLike,
  language: Language,
  allergies?: readonly Labelled[],
  payer?: Named | null,
): PatientCardPatient {
  return {
    nameAr: patient.full_name_ar || patient.full_name_en,
    nameEn: patient.full_name_en || null,
    fileNo: patient.file_no,
    sex: patient.sex,
    birthDate: patient.date_of_birth ?? null,
    phone: patient.phone === "" ? null : patient.phone,
    ...(allergies === undefined
      ? {}
      : { allergies: allergies.map((a) => pickName({ ar: a.label_ar, en: a.label_en }, language)) }),
    coverage: payer ? { nameAr: payer.name_ar, nameEn: payer.name_en } : null,
    incomplete: patient.is_incomplete,
  };
}
