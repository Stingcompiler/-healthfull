import { useCallback } from "react";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { PatientSummary, UserRef } from "../types";

interface Named {
  name_ar: string;
  name_en: string;
}

interface Labelled {
  label_ar: string;
  label_en: string;
}

/** Picks bilingual fields for the current language (ARCHITECTURE 4.11, with fallback). */
export function useNames() {
  const language = useLanguage();
  const name = useCallback(
    (row: Named | null | undefined): string => (row ? pickName({ ar: row.name_ar, en: row.name_en }, language) : ""),
    [language],
  );
  const label = useCallback(
    (row: Labelled | null | undefined): string =>
      row ? pickName({ ar: row.label_ar, en: row.label_en }, language) : "",
    [language],
  );
  const user = useCallback(
    (row: UserRef | null | undefined): string =>
      row ? pickName({ ar: row.full_name_ar, en: row.full_name_en }, language) || row.username : "",
    [language],
  );
  const patient = useCallback(
    (row: PatientSummary): string => pickName({ ar: row.full_name_ar, en: row.full_name_en }, language),
    [language],
  );
  const text = useCallback((ar: string, en: string): string => pickName({ ar, en }, language), [language]);
  const list = useCallback(
    (items: readonly string[]): string =>
      new Intl.ListFormat(language === "ar" ? "ar" : "en", { type: "unit", style: "short" }).format(items),
    [language],
  );
  return { name, label, user, patient, text, list, language };
}
