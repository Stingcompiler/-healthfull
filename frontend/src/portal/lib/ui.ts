import { useCallback } from "react";

import { localeFor } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import type { Language } from "@/lib/preferences";

/** Picks the bilingual field for the UI language, with fallback (ARCHITECTURE 4.11). */
export function usePick(): (ar: string | null | undefined, en: string | null | undefined) => string {
  const language = useLanguage();
  return useCallback((ar, en) => pickName({ ar, en }, language), [language]);
}

/** The doctor's specialty and department on one line ("Cardiology · Internal medicine"). */
export function useDoctorDetail(): (d: {
  specialty_ar: string;
  specialty_en: string;
  department_ar: string;
  department_en: string;
}) => string {
  const pick = usePick();
  return useCallback(
    (d) =>
      [...new Set([pick(d.specialty_ar, d.specialty_en), pick(d.department_ar, d.department_en)].filter(Boolean))].join(
        " · ",
      ),
    [pick],
  );
}

/** A calendar day from the API ("2026-10-12"), shown as e.g. "Mon, 12 Oct" in the UI language. */
export function formatDay(day: string, language: Language): string {
  return new Intl.DateTimeFormat(localeFor(language), {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

/** A calendar day split for a two-line day chip: "Mon" over "12 Oct", in the UI language. */
export function dayParts(day: string, language: Language): { weekday: string; date: string } {
  const at = new Date(`${day}T00:00:00Z`);
  const locale = localeFor(language);
  return {
    weekday: new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" }).format(at),
    date: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" }).format(at),
  };
}

/** The public URL a receipt's QR opens to check it (FEATURES 15.1, ADR 0016). */
export function receiptVerifyUrl(token: string, number: string): string {
  return `${window.location.origin}/verify/${token}?r=${encodeURIComponent(number)}`;
}
