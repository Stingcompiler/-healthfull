/** Presentation helpers for patient files (no business rules: the server decides). */
import type { PatientCardPatient } from "@/components/PatientCard";
import { CENTER_TIME_ZONE } from "@/lib/format";
import type { Language } from "@/lib/preferences";
import { pickName } from "@/lib/names";

import type { PatientBrief, PatientFile, PatientListItem, PatientProfile } from "./types";

type Named = Pick<PatientBrief, "full_name_ar" | "full_name_en">;

/** The patient's name in the UI language, falling back to the other script. */
export function patientName(patient: Named, language: Language): string {
  return pickName({ ar: patient.full_name_ar, en: patient.full_name_en }, language);
}

/** What the shared PatientCard shows for a file (allergies only when the profile has them). */
export function toCardPatient(
  patient: PatientListItem | PatientFile,
  profile?: Pick<PatientProfile, "allergies"> | null,
  language: Language = "ar",
): PatientCardPatient {
  const allergies = profile?.allergies.map((a) =>
    language === "ar" ? a.label_ar || a.label_en : a.label_en || a.label_ar,
  );
  return {
    nameAr: patient.full_name_ar || patient.full_name_en,
    nameEn: patient.full_name_en || null,
    fileNo: patient.file_no,
    sex: patient.sex,
    birthDate: patient.date_of_birth,
    phone: patient.phone || null,
    // An empty list means "nothing recorded", never "no known allergies".
    allergies: allergies && allergies.length > 0 ? allergies : null,
    coverage: patient.coverage
      ? {
          nameAr: patient.coverage.payer_name_ar,
          nameEn: patient.coverage.payer_name_en,
          cardNo: patient.coverage.card_number || null,
        }
      : null,
    incomplete: patient.is_incomplete,
  };
}

/** Today's date (YYYY-MM-DD) in the center's time zone. */
export function centerToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: CENTER_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Shift a YYYY-MM-DD date by whole days. */
export function addDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
  return date.toISOString().slice(0, 10);
}
