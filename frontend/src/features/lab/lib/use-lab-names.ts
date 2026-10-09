import { useCallback } from "react";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { LabPatient, LabReason, LabTestRef, LabUserRef } from "../types";

/** Picks bilingual fields for a language (the UI's by default; a printout may choose another). */
export function useLabNames(lang?: "ar" | "en") {
  const ui = useLanguage();
  const language = lang ?? ui;
  const text = useCallback((ar: string, en: string): string => pickName({ ar, en }, language), [language]);
  const test = useCallback(
    (row: Pick<LabTestRef, "name_ar" | "name_en">): string => pickName({ ar: row.name_ar, en: row.name_en }, language),
    [language],
  );
  const patient = useCallback(
    (row: Pick<LabPatient, "full_name_ar" | "full_name_en">): string =>
      pickName({ ar: row.full_name_ar, en: row.full_name_en }, language),
    [language],
  );
  const user = useCallback(
    (row: LabUserRef | null | undefined): string =>
      row ? pickName({ ar: row.full_name_ar, en: row.full_name_en }, language) || row.username : "",
    [language],
  );
  const reason = useCallback(
    (row: LabReason | null | undefined): string =>
      row ? pickName({ ar: row.label_ar, en: row.label_en }, language) : "",
    [language],
  );
  const list = useCallback(
    (items: readonly string[]): string =>
      new Intl.ListFormat(language === "ar" ? "ar" : "en", { type: "unit", style: "short" }).format(items),
    [language],
  );
  return { text, test, patient, user, reason, list, language };
}
